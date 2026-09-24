'use strict';

/**
 * runtime/channel-gateway/core/backup-scheduler.js
 *
 * Operational Periodic Verified SQLite Backup Scheduler & Hygiene Integration
 * (TG-MVP-09 / TG-MVP-09A / T11-main).
 *
 * Responsibilities:
 * - Single Gateway in-process scheduler capability.
 * - Periodic freshness monitoring of canonical verified SQLite backup artifacts in stateRoot/backups/.
 * - Legacy root-level backup artifact safe transition to stateRoot/backups/.
 * - Preflight free disk space safety check (2x live DB size required).
 * - Verified SQLite backup execution via repository.createVerifiedBackup().
 * - Deterministic retention & capacity cleanup (1GB maxTotalBytes / latest 3 minKeepCount).
 * - Atomic write of stateRoot/backup-health.json on each check cycle.
 * - In-flight / re-entrancy guard to prevent overlapping backup operations.
 * - Non-fatal failure semantics with bounded non-secret diagnostics.
 * - Zero third-party dependencies.
 */

const fs = require('node:fs');
const path = require('node:path');

const {
  BACKUP_DIRECTORY_NAME,
  BACKUP_HEALTH_FILENAME,
  CANONICAL_BACKUP_NAME_REGEX,
  DEFAULT_MAX_TOTAL_BYTES,
  DEFAULT_MIN_KEEP_COUNT,
  NO_SUCCESS_ALERT_MS,
  CONSECUTIVE_FAILURE_ALERT_THRESHOLD,
  FREE_SPACE_REQUIRED_MULTIPLIER,
  SAFE_TOKEN_REGEX,
  ensureBackupsDirectory,
  migrateLegacyBackups,
  inventoryAndCleanupBackups,
  checkFreeSpaceForBackup,
  evaluateHealthState,
  writeBackupHealthAtomic,
} = require('./backup-hygiene');

/** Fixed program constants: 24h freshness threshold, 1h check tick */
const BACKUP_FRESHNESS_THRESHOLD_MS = 86_400_000;
const BACKUP_CHECK_INTERVAL_MS = 3_600_000;

/**
 * Formats a bounded diagnostic string containing ONLY:
 * - fixed category
 * - bounded error name
 * - bounded safe error code (if matching SAFE_TOKEN_REGEX)
 *
 * Strictly NEVER reflects raw err.message, err.stack, raw Error objects,
 * absolute paths, tokens, credentials, or DB contents.
 *
 * @param {string} category
 * @param {any} err
 * @returns {string}
 */
function formatBoundedDiagnostic(category, err) {
  let name = 'Error';
  let code = null;

  if (err && typeof err === 'object') {
    if (typeof err.name === 'string' && SAFE_TOKEN_REGEX.test(err.name)) {
      name = err.name;
    }
    if (typeof err.code === 'string' && SAFE_TOKEN_REGEX.test(err.code)) {
      code = err.code;
    }
  } else if (typeof err === 'string' && SAFE_TOKEN_REGEX.test(err)) {
    code = err;
  }

  return code
    ? `[BackupScheduler] ${category}: name=${name}, code=${code}`
    : `[BackupScheduler] ${category}: name=${name}`;
}

/**
 * Validates the return contract of createVerifiedBackup().
 * F1 Contract requirements:
 * - non-null object
 * - result.success === true
 * - result.backupPath is a non-empty string
 * - result.sourceSchemaVersion is a positive integer
 * - result.integrity === 'ok'
 *
 * @param {any} result
 */
function validateBackupResult(result) {
  if (!result || typeof result !== 'object') {
    const err = new Error('Invalid verified backup result: must be a non-null object');
    err.code = 'INVALID_BACKUP_RESULT';
    throw err;
  }
  if (result.success !== true) {
    const err = new Error('Invalid verified backup result: success must be true');
    err.code = 'BACKUP_UNSUCCESSFUL';
    throw err;
  }
  if (typeof result.backupPath !== 'string' || result.backupPath.trim().length === 0) {
    const err = new Error('Invalid verified backup result: backupPath must be a non-empty string');
    err.code = 'INVALID_BACKUP_PATH';
    throw err;
  }
  if (
    typeof result.sourceSchemaVersion !== 'number' ||
    !Number.isSafeInteger(result.sourceSchemaVersion) ||
    result.sourceSchemaVersion <= 0
  ) {
    const err = new Error(
      'Invalid verified backup result: sourceSchemaVersion must be a positive integer'
    );
    err.code = 'INVALID_SOURCE_SCHEMA_VERSION';
    throw err;
  }
  if (result.integrity !== 'ok') {
    const err = new Error('Invalid verified backup result: integrity must be "ok"');
    err.code = 'INVALID_BACKUP_INTEGRITY';
    throw err;
  }
}

class BackupScheduler {
  #repository;
  #stateRoot;
  #now;
  #setIntervalFn;
  #clearIntervalFn;
  #fs;
  #statfsSync;
  #logger;
  #backupPolicy;
  #consecutiveFailures = 0;
  #lastSuccessAt = null;
  #intervalId = null;
  #started = false;
  #inFlight = false;

  /**
   * @param {object} options
   * @param {object} options.repository State repository implementing createVerifiedBackup()
   * @param {string} options.stateRoot Absolute path to canonical stateRoot directory
   * @param {object} [options.backupPolicy] Backup retention policy
   * @param {number} [options.backupPolicy.maxTotalBytes=1_000_000_000] Maximum total capacity in bytes
   * @param {number} [options.backupPolicy.minKeepCount=3] Minimum backups to protect
   * @param {function(): number} [options.now=Date.now] Deterministic timestamp provider
   * @param {function(function(): void, number): any} [options.setIntervalFn=global.setInterval] Timer scheduler
   * @param {function(any): void} [options.clearIntervalFn=global.clearInterval] Timer clearer
   * @param {object} [options.fs=node:fs] File system module
   * @param {function(string): object} [options.statfsSync] Volume statistics provider
   * @param {object} [options.logger=console] Logger instance
   */
  constructor(options = {}) {
    if (!options || typeof options !== 'object') {
      throw new TypeError('BackupScheduler options must be an object (fail-closed)');
    }

    const {
      repository,
      stateRoot,
      backupPolicy = {},
      now = Date.now,
      setIntervalFn = global.setInterval,
      clearIntervalFn = global.clearInterval,
      fs: fsImpl = fs,
      statfsSync = null,
      logger = console,
    } = options;

    if (!repository || typeof repository !== 'object') {
      throw new TypeError('BackupScheduler repository must be provided as an object (fail-closed)');
    }
    if (typeof repository.createVerifiedBackup !== 'function') {
      throw new TypeError(
        'BackupScheduler repository must implement createVerifiedBackup() (fail-closed)'
      );
    }

    if (typeof stateRoot !== 'string' || stateRoot.trim().length === 0) {
      throw new TypeError('BackupScheduler stateRoot must be a non-empty string (fail-closed)');
    }
    if (!path.isAbsolute(stateRoot)) {
      throw new Error(
        `BackupScheduler stateRoot must be an absolute path: '${stateRoot}' (fail-closed)`
      );
    }

    if (typeof now !== 'function') {
      throw new TypeError('BackupScheduler now must be a function (fail-closed)');
    }
    if (typeof setIntervalFn !== 'function') {
      throw new TypeError('BackupScheduler setIntervalFn must be a function (fail-closed)');
    }
    if (typeof clearIntervalFn !== 'function') {
      throw new TypeError('BackupScheduler clearIntervalFn must be a function (fail-closed)');
    }
    if (
      !fsImpl ||
      typeof fsImpl !== 'object' ||
      typeof fsImpl.readdirSync !== 'function' ||
      typeof fsImpl.lstatSync !== 'function'
    ) {
      throw new TypeError(
        'BackupScheduler fs implementation must provide readdirSync and lstatSync (fail-closed)'
      );
    }
    if (statfsSync !== null && typeof statfsSync !== 'function') {
      throw new TypeError('BackupScheduler statfsSync must be a function if provided (fail-closed)');
    }
    if (!logger || typeof logger !== 'object' || typeof logger.error !== 'function') {
      throw new TypeError(
        'BackupScheduler logger must be an object with an error method (fail-closed)'
      );
    }

    // Policy validation
    let maxTotalBytes = DEFAULT_MAX_TOTAL_BYTES;
    let minKeepCount = DEFAULT_MIN_KEEP_COUNT;
    if (backupPolicy !== undefined) {
      if (!backupPolicy || typeof backupPolicy !== 'object' || Array.isArray(backupPolicy)) {
        throw new TypeError('BackupScheduler backupPolicy must be a plain object (fail-closed)');
      }
      if (backupPolicy.maxTotalBytes !== undefined) {
        if (
          typeof backupPolicy.maxTotalBytes !== 'number' ||
          !Number.isSafeInteger(backupPolicy.maxTotalBytes) ||
          backupPolicy.maxTotalBytes <= 0
        ) {
          throw new TypeError('backupPolicy.maxTotalBytes must be a positive safe integer (fail-closed)');
        }
        maxTotalBytes = backupPolicy.maxTotalBytes;
      }
      if (backupPolicy.minKeepCount !== undefined) {
        if (
          typeof backupPolicy.minKeepCount !== 'number' ||
          !Number.isSafeInteger(backupPolicy.minKeepCount) ||
          backupPolicy.minKeepCount < 1
        ) {
          throw new TypeError('backupPolicy.minKeepCount must be a safe integer >= 1 (fail-closed)');
        }
        minKeepCount = backupPolicy.minKeepCount;
      }
    }

    this.#repository = repository;
    this.#stateRoot = stateRoot;
    this.#now = now;
    this.#setIntervalFn = setIntervalFn;
    this.#clearIntervalFn = clearIntervalFn;
    this.#fs = fsImpl;
    this.#statfsSync =
      statfsSync ||
      (typeof fsImpl.statfsSync === 'function'
        ? fsImpl.statfsSync.bind(fsImpl)
        : typeof fs.statfsSync === 'function'
        ? fs.statfsSync.bind(fs)
        : null);
    this.#logger = logger;
    this.#backupPolicy = { maxTotalBytes, minKeepCount };
  }

  get isStarted() {
    return this.#started;
  }

  get inFlight() {
    return this.#inFlight;
  }

  get consecutiveFailures() {
    return this.#consecutiveFailures;
  }

  get backupPolicy() {
    return { ...this.#backupPolicy };
  }

  get lastSuccessAt() {
    return this.#lastSuccessAt;
  }

  /**
   * Start the backup scheduler.
   * Performs an immediate overdue check, then schedules periodic 1h ticks.
   * Fails closed if already started.
   */
  start() {
    if (this.#started) {
      throw new Error(
        'BackupScheduler is already started (cannot start duplicate scheduler)'
      );
    }
    this.#started = true;

    // Immediate overdue check at startup (non-fatal if check fails)
    this.#runCheckCycle();

    // Schedule periodic 1h tick
    this.#intervalId = this.#setIntervalFn(() => {
      this.#runCheckCycle();
    }, BACKUP_CHECK_INTERVAL_MS);
  }

  /**
   * Stop the backup scheduler.
   * Idempotent; clears interval and does not trigger shutdown backups.
   */
  stop() {
    if (!this.#started) {
      return;
    }
    this.#started = false;
    if (this.#intervalId !== null) {
      this.#clearIntervalFn(this.#intervalId);
      this.#intervalId = null;
    }
  }

  /**
   * Internal wrapper managing re-entrancy / overlap guard.
   */
  #runCheckCycle() {
    if (!this.#started) {
      return;
    }
    if (this.#inFlight) {
      // Overlapping check / operation in-flight: skip
      return;
    }

    this.#inFlight = true;
    try {
      this.#performFreshnessCheckAndBackup();
    } catch (err) {
      this.#logError('UnexpectedCycleError', err);
    } finally {
      this.#inFlight = false;
    }
  }

  /**
   * Orchestrates the complete backup hygiene cycle:
   * 1. Ensure stateRoot/backups directory exists.
   * 2. Scan freshness against canonical backups in stateRoot/backups/.
   * 3. Migrate any legacy root-level backups to stateRoot/backups/.
   * 4. If due: preflight free disk space check (2x live DB size).
   * 5. If space check passes: execute repository.createVerifiedBackup().
   * 6. If backup succeeded: run inventory & cleanup (oldest-first, protecting newest minKeepCount).
   * 7. Evaluate health state & atomically update stateRoot/backup-health.json.
   */
  #performFreshnessCheckAndBackup() {
    const nowMs = this.#now();
    const cycleWarnings = [];
    const cycleAlerts = [];

    // 1. Ensure stateRoot/backups/ exists and is valid
    let backupRoot;
    try {
      backupRoot = ensureBackupsDirectory(this.#stateRoot, { fs: this.#fs });
    } catch (err) {
      this.#consecutiveFailures++;
      this.#logError('EnsureBackupsDir', err);
      const healthData = evaluateHealthState({
        nowMs,
        lastSuccessAt: this.#lastSuccessAt,
        consecutiveFailures: this.#consecutiveFailures,
        backupCount: 0,
        totalBytes: 0,
        maxTotalBytes: this.#backupPolicy.maxTotalBytes,
        minKeepCount: this.#backupPolicy.minKeepCount,
        extraReasonCodes: ['BACKUP_DIRECTORY_UNAVAILABLE'],
      });
      writeBackupHealthAtomic(this.#stateRoot, healthData, {
        fs: this.#fs,
        logger: this.#logger,
      });
      return;
    }

    // 2. Scan freshness candidates in backupRoot
    let entries;
    try {
      entries = this.#fs.readdirSync(backupRoot);
    } catch (err) {
      this.#consecutiveFailures++;
      this.#logError('ScanFreshness', err);
      const healthData = evaluateHealthState({
        nowMs,
        lastSuccessAt: this.#lastSuccessAt,
        consecutiveFailures: this.#consecutiveFailures,
        backupCount: 0,
        totalBytes: 0,
        maxTotalBytes: this.#backupPolicy.maxTotalBytes,
        minKeepCount: this.#backupPolicy.minKeepCount,
        extraReasonCodes: ['BACKUP_DIRECTORY_UNAVAILABLE'],
      });
      writeBackupHealthAtomic(this.#stateRoot, healthData, {
        fs: this.#fs,
        logger: this.#logger,
      });
      return;
    }

    // 3. Migrate legacy root-level backups
    try {
      const migrationRes = migrateLegacyBackups(this.#stateRoot, backupRoot, {
        fs: this.#fs,
        logger: this.#logger,
      });
      if (migrationRes && Array.isArray(migrationRes.warnings)) {
        cycleWarnings.push(...migrationRes.warnings);
      }
    } catch (_) {
      cycleWarnings.push('LEGACY_BACKUP_MIGRATION_FAILED');
    }

    // 4. Evaluate candidates and freshness
    let latestBackupMtimeMs = null;
    const eligibleBackups = [];

    for (const entry of entries) {
      const filename = typeof entry === 'string' ? entry : entry.name;
      if (typeof filename !== 'string' || !CANONICAL_BACKUP_NAME_REGEX.test(filename)) {
        cycleWarnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
        continue;
      }

      const fullPath = path.join(backupRoot, filename);
      let stat;
      try {
        stat = this.#fs.lstatSync(fullPath);
      } catch (err) {
        this.#logWarn('StatCandidate', err);
        cycleWarnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
        continue;
      }

      if (typeof stat.isSymbolicLink === 'function' && stat.isSymbolicLink()) {
        cycleWarnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
        continue;
      }
      if (typeof stat.isFile === 'function' && !stat.isFile()) {
        cycleWarnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
        continue;
      }

      let mtimeMs = null;
      if (typeof stat.mtimeMs === 'number' && Number.isFinite(stat.mtimeMs)) {
        mtimeMs = stat.mtimeMs;
      } else if (stat.mtime instanceof Date) {
        mtimeMs = stat.mtime.getTime();
      }

      if (mtimeMs === null || !Number.isFinite(mtimeMs) || mtimeMs <= 0) {
        continue;
      }
      if (mtimeMs > nowMs) {
        continue;
      }

      const size = typeof stat.size === 'number' && Number.isFinite(stat.size) ? stat.size : 0;
      eligibleBackups.push({ filename, fullPath, mtimeMs, size });

      if (latestBackupMtimeMs === null || mtimeMs > latestBackupMtimeMs) {
        latestBackupMtimeMs = mtimeMs;
      }
    }

    if (latestBackupMtimeMs !== null) {
      this.#lastSuccessAt = latestBackupMtimeMs;
    }

    const isDue =
      latestBackupMtimeMs === null ||
      nowMs - latestBackupMtimeMs >= BACKUP_FRESHNESS_THRESHOLD_MS;

    let verifiedBackupSucceeded = false;
    let justCreatedPath = null;

    if (isDue) {
      // 5. Preflight free space check
      const liveDbPath =
        (this.#repository && typeof this.#repository.databasePath === 'string' && this.#repository.databasePath) ||
        path.join(this.#stateRoot, 'channel-gateway-state.sqlite3');

      const spaceCheck = checkFreeSpaceForBackup(backupRoot, liveDbPath, {
        fs: this.#fs,
        logger: this.#logger,
        statfsSync: this.#statfsSync,
      });

      if (!spaceCheck.ok) {
        this.#consecutiveFailures++;
        if (spaceCheck.reason) {
          cycleAlerts.push(spaceCheck.reason);
        }
      } else {
        // Space check passed: attempt verified backup
        try {
          const result = this.#repository.createVerifiedBackup();
          validateBackupResult(result);

          // Path containment & validity check
          const basename = path.basename(result.backupPath);
          if (!CANONICAL_BACKUP_NAME_REGEX.test(basename)) {
            throw new Error('Created backup filename is not canonical');
          }
          const parentDir = path.dirname(result.backupPath);
          let canonicalParent = parentDir;
          let canonicalBackupRoot = backupRoot;
          try {
            canonicalParent = this.#fs.realpathSync(parentDir);
            canonicalBackupRoot = this.#fs.realpathSync(backupRoot);
          } catch (_) {}
          if (canonicalParent !== canonicalBackupRoot) {
            throw new Error('Created backup is not confined to backups directory');
          }

          const stat = this.#fs.lstatSync(result.backupPath);
          if (typeof stat.isSymbolicLink === 'function' && stat.isSymbolicLink()) {
            throw new Error('Created backup is a symlink');
          }
          if (typeof stat.isFile === 'function' && !stat.isFile()) {
            throw new Error('Created backup is not a regular file');
          }

          verifiedBackupSucceeded = true;
          justCreatedPath = result.backupPath;
          this.#consecutiveFailures = 0;
          this.#lastSuccessAt = nowMs;
          latestBackupMtimeMs = nowMs;
        } catch (err) {
          this.#consecutiveFailures++;
          this.#logError('PerformBackup', err);
        }
      }
    }

    // 6. Post-backup inventory & cleanup (if backup succeeded this cycle)
    let inventoryRes;
    if (verifiedBackupSucceeded) {
      inventoryRes = inventoryAndCleanupBackups(backupRoot, {
        fs: this.#fs,
        logger: this.#logger,
        maxTotalBytes: this.#backupPolicy.maxTotalBytes,
        minKeepCount: this.#backupPolicy.minKeepCount,
        justCreatedPath,
        verifiedBackupSucceededThisCycle: true,
      });
      if (inventoryRes.warnings) cycleWarnings.push(...inventoryRes.warnings);
      if (inventoryRes.alerts) cycleAlerts.push(...inventoryRes.alerts);
    } else {
      inventoryRes = inventoryAndCleanupBackups(backupRoot, {
        fs: this.#fs,
        logger: this.#logger,
        maxTotalBytes: this.#backupPolicy.maxTotalBytes,
        minKeepCount: this.#backupPolicy.minKeepCount,
        verifiedBackupSucceededThisCycle: false,
      });
      if (inventoryRes.warnings) cycleWarnings.push(...inventoryRes.warnings);
      if (inventoryRes.alerts) cycleAlerts.push(...inventoryRes.alerts);
    }

    // 7. Health evaluation & atomic file write
    const extraReasonCodes = [...cycleWarnings, ...cycleAlerts];
    const healthData = evaluateHealthState({
      nowMs,
      lastSuccessAt: this.#lastSuccessAt,
      consecutiveFailures: this.#consecutiveFailures,
      backupCount: inventoryRes.backupCount,
      totalBytes: inventoryRes.totalBytes,
      maxTotalBytes: this.#backupPolicy.maxTotalBytes,
      minKeepCount: this.#backupPolicy.minKeepCount,
      extraReasonCodes,
    });

    writeBackupHealthAtomic(this.#stateRoot, healthData, {
      fs: this.#fs,
      logger: this.#logger,
    });
  }

  #logError(category, err) {
    this.#logger.error(formatBoundedDiagnostic(category, err));
  }

  #logWarn(category, err) {
    const diagnostic = formatBoundedDiagnostic(category, err);
    if (typeof this.#logger.warn === 'function') {
      this.#logger.warn(diagnostic);
    } else {
      this.#logger.error(diagnostic);
    }
  }
}

module.exports = {
  BackupScheduler,
  BACKUP_FRESHNESS_THRESHOLD_MS,
  BACKUP_CHECK_INTERVAL_MS,
  CANONICAL_BACKUP_NAME_REGEX,
  validateBackupResult,
  formatBoundedDiagnostic,
};
