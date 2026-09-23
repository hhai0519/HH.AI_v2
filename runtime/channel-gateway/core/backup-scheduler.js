'use strict';

/**
 * runtime/channel-gateway/core/backup-scheduler.js
 *
 * Operational Periodic Verified SQLite Backup Scheduler (TG-MVP-09 / T11-main).
 *
 * Responsibilities:
 * - Single Gateway in-process scheduler capability.
 * - Periodic freshness monitoring of canonical verified SQLite backup artifacts.
 * - In-flight / re-entrancy guard to prevent overlapping backup operations.
 * - Non-fatal failure semantics: periodic scan or backup failure logs bounded non-secret
 *   diagnostics, leaves service running, and retries on the next normal tick.
 * - Zero third-party dependencies.
 * - Zero retention / cleanup / deletion logic (strictly deferred to TG-MVP-09A).
 */

const fs = require('node:fs');
const path = require('node:path');

/** Fixed program constants: 24h freshness threshold, 1h check tick */
const BACKUP_FRESHNESS_THRESHOLD_MS = 86_400_000;
const BACKUP_CHECK_INTERVAL_MS = 3_600_000;

/**
 * Canonical backup filename pattern:
 * channel-gateway-state.backup-v{positive integer}-{uuid-v4}.sqlite3
 * Strictly aligned with T11A crypto.randomUUID() RFC 4122 v4 contract:
 * xxxxxxxx-xxxx-4xxx-[89ab]xxx-xxxxxxxxxxxx (case-insensitive hex).
 */
const CANONICAL_BACKUP_NAME_REGEX =
  /^channel-gateway-state\.backup-v([1-9]\d*)-([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})\.sqlite3$/;

/**
 * Whitelist pattern for safe error codes/tokens (letters, digits, underscore, dot, hyphen up to 64 chars).
 */
const SAFE_TOKEN_REGEX = /^[A-Za-z0-9_.-]{1,64}$/;

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
  #logger;
  #intervalId = null;
  #started = false;
  #inFlight = false;

  /**
   * @param {object} options
   * @param {object} options.repository State repository implementing createVerifiedBackup()
   * @param {string} options.stateRoot Absolute path to canonical stateRoot directory
   * @param {function(): number} [options.now=Date.now] Deterministic timestamp provider
   * @param {function(function(): void, number): any} [options.setIntervalFn=global.setInterval] Timer scheduler
   * @param {function(any): void} [options.clearIntervalFn=global.clearInterval] Timer clearer
   * @param {object} [options.fs=node:fs] File system module
   * @param {object} [options.logger=console] Logger instance
   */
  constructor(options = {}) {
    if (!options || typeof options !== 'object') {
      throw new TypeError('BackupScheduler options must be an object (fail-closed)');
    }

    const {
      repository,
      stateRoot,
      now = Date.now,
      setIntervalFn = global.setInterval,
      clearIntervalFn = global.clearInterval,
      fs: fsImpl = fs,
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
    if (!logger || typeof logger !== 'object' || typeof logger.error !== 'function') {
      throw new TypeError(
        'BackupScheduler logger must be an object with an error method (fail-closed)'
      );
    }

    this.#repository = repository;
    this.#stateRoot = stateRoot;
    this.#now = now;
    this.#setIntervalFn = setIntervalFn;
    this.#clearIntervalFn = clearIntervalFn;
    this.#fs = fsImpl;
    this.#logger = logger;
  }

  get isStarted() {
    return this.#started;
  }

  get inFlight() {
    return this.#inFlight;
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
   * Scans canonical backup artifacts in stateRoot, evaluates freshness,
   * and creates a verified backup if overdue.
   */
  #performFreshnessCheckAndBackup() {
    const nowMs = this.#now();

    let entries;
    try {
      entries = this.#fs.readdirSync(this.#stateRoot);
    } catch (err) {
      this.#logError('ScanFreshness', err);
      return;
    }

    let latestBackupMtimeMs = null;

    for (const entry of entries) {
      const filename = typeof entry === 'string' ? entry : entry.name;
      if (typeof filename !== 'string' || !CANONICAL_BACKUP_NAME_REGEX.test(filename)) {
        continue;
      }

      const fullPath = path.join(this.#stateRoot, filename);
      let stat;
      try {
        stat = this.#fs.lstatSync(fullPath);
      } catch (err) {
        this.#logWarn('StatCandidate', err);
        continue;
      }

      // Symlinks are strictly ignored
      if (typeof stat.isSymbolicLink === 'function' && stat.isSymbolicLink()) {
        continue;
      }

      // Non-regular files (e.g. directories) are strictly ignored
      if (typeof stat.isFile === 'function' && !stat.isFile()) {
        continue;
      }

      let mtimeMs = null;
      if (typeof stat.mtimeMs === 'number' && Number.isFinite(stat.mtimeMs)) {
        mtimeMs = stat.mtimeMs;
      } else if (stat.mtime instanceof Date) {
        mtimeMs = stat.mtime.getTime();
      }

      // Invalid mtime (non-finite or non-positive) is ignored
      if (mtimeMs === null || !Number.isFinite(mtimeMs) || mtimeMs <= 0) {
        continue;
      }

      // Future-dated mtime is ignored (does not suppress backup)
      if (mtimeMs > nowMs) {
        continue;
      }

      if (latestBackupMtimeMs === null || mtimeMs > latestBackupMtimeMs) {
        latestBackupMtimeMs = mtimeMs;
      }
    }

    const isDue =
      latestBackupMtimeMs === null ||
      nowMs - latestBackupMtimeMs >= BACKUP_FRESHNESS_THRESHOLD_MS;

    if (!isDue) {
      return;
    }

    try {
      const result = this.#repository.createVerifiedBackup();
      validateBackupResult(result);
    } catch (err) {
      this.#logError('PerformBackup', err);
    }
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
