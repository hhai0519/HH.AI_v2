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
 * channel-gateway-state.backup-v{positive integer}-{uuid}.sqlite3
 * Matches T11A crypto.randomUUID() naming contract.
 */
const CANONICAL_BACKUP_NAME_REGEX =
  /^channel-gateway-state\.backup-v([1-9]\d*)-([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.sqlite3$/;

/**
 * Redact sensitive info (such as absolute system/user paths or credentials)
 * from bounded log messages to comply with kernel and repository safety contracts.
 *
 * @param {string} msg
 * @returns {string}
 */
function sanitizeLogMessage(msg) {
  if (typeof msg !== 'string') {
    return 'Unknown diagnostic message';
  }
  let cleaned = msg;
  // Redact Windows absolute drive paths (e.g. C:\Users\...)
  cleaned = cleaned.replace(/[a-zA-Z]:\\[^\s:;,)'"]+/g, '[REDACTED_PATH]');
  // Redact UNC paths (e.g. \\server\share\...)
  cleaned = cleaned.replace(/\\\\[^\s:;,)'"]+/g, '[REDACTED_PATH]');
  // Redact POSIX absolute paths (e.g. /home/user/...)
  cleaned = cleaned.replace(/(^|\s)\/[^\s:;,)'"]+/g, '$1[REDACTED_PATH]');
  // Redact potential secret/token assignments
  cleaned = cleaned.replace(/(token|secret|password|key|bearer)\s*[:=]\s*\S+/gi, '$1=[REDACTED]');
  return cleaned;
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
      this.#logError('Unexpected error during backup check cycle', err);
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
      this.#logError('Failed to read stateRoot directory', err);
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
        this.#logWarn('Candidate entry inspection failure; ignoring entry for freshness', err);
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
      this.#repository.createVerifiedBackup();
    } catch (err) {
      this.#logError('Failed to create verified backup', err);
    }
  }

  #logError(category, err) {
    const errorName = err && typeof err.name === 'string' ? err.name : 'Error';
    const rawMessage = err && typeof err.message === 'string' ? err.message : String(err);
    const safeMessage = sanitizeLogMessage(rawMessage);
    this.#logger.error(`[BackupScheduler] ${category}: ${errorName} - ${safeMessage}`);
  }

  #logWarn(category, err) {
    const errorName = err && typeof err.name === 'string' ? err.name : 'Warning';
    const rawMessage = err && typeof err.message === 'string' ? err.message : String(err);
    const safeMessage = sanitizeLogMessage(rawMessage);
    if (typeof this.#logger.warn === 'function') {
      this.#logger.warn(`[BackupScheduler] ${category}: ${errorName} - ${safeMessage}`);
    } else {
      this.#logger.error(`[BackupScheduler] ${category}: ${errorName} - ${safeMessage}`);
    }
  }
}

module.exports = {
  BackupScheduler,
  BACKUP_FRESHNESS_THRESHOLD_MS,
  BACKUP_CHECK_INTERVAL_MS,
};
