'use strict';

/**
 * runtime/channel-gateway/core/backup-hygiene.js
 *
 * Operational SQLite Backup Filesystem Hygiene Module (TG-MVP-09A).
 *
 * Responsibilities:
 * - Single authority for canonical backup naming regex and backup hygiene constants.
 * - Gateway-owned child directory management (`stateRoot/backups/`).
 * - Safe same-volume legacy root backup migration (idempotent, no-overwrite, no-fallback).
 * - Capacity inventory & deterministic retention cleanup (oldest-first, newest-3 protected).
 * - Pre-backup free-space verification (Node built-in fs.statfsSync, 2x DB size safety margin).
 * - Comprehensive health evaluation (OK, WARN, ALERT states, 48h alert, 3-consecutive-failure alert).
 * - Scoped bounded atomic health JSON writer with strict privacy protection:
 *   NEVER leaks file paths, database paths, error messages, stack traces, or message content.
 * - Zero third-party dependencies (Node.js built-ins node:fs, node:path only).
 */

const fs = require('node:fs');
const path = require('node:path');

const BACKUP_DIRECTORY_NAME = 'backups';
const BACKUP_HEALTH_FILENAME = 'backup-health.json';

/**
 * Canonical backup filename pattern:
 * channel-gateway-state.backup-v{positive integer}-{uuid-v4}.sqlite3
 * Strictly aligned with crypto.randomUUID() RFC 4122 v4 contract:
 * xxxxxxxx-xxxx-4xxx-[89ab]xxx-xxxxxxxxxxxx (case-insensitive hex).
 */
const CANONICAL_BACKUP_NAME_REGEX =
  /^channel-gateway-state\.backup-v([1-9]\d*)-([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})\.sqlite3$/;

/** User & Macro authoritative capacity defaults: 1GB exact (1,000,000,000 bytes), keep 3 */
const DEFAULT_MAX_TOTAL_BYTES = 1_000_000_000;
const DEFAULT_MIN_KEEP_COUNT = 3;

/** Operational thresholds */
const NO_SUCCESS_ALERT_MS = 172_800_000; // 48 hours
const CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3;
const FREE_SPACE_REQUIRED_MULTIPLIER = 2;

/** Whitelist pattern for safe error codes/tokens (letters, digits, underscore, dot, hyphen up to 64 chars) */
const SAFE_TOKEN_REGEX = /^[A-Za-z0-9_.-]{1,64}$/;

/**
 * Formats a bounded non-secret diagnostic string containing ONLY:
 * - fixed category
 * - bounded safe error name
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
    ? `[BackupHygiene] ${category}: name=${name}, code=${code}`
    : `[BackupHygiene] ${category}: name=${name}`;
}

/**
 * Checks whether childPath is strictly located inside parentPath.
 *
 * @param {string} childPath
 * @param {string} parentPath
 * @returns {boolean}
 */
function isPathInside(childPath, parentPath) {
  const resolvedParent = path.resolve(parentPath);
  const resolvedChild = path.resolve(childPath);

  const rel = path.relative(resolvedParent, resolvedChild);

  if (rel === '') {
    return true;
  }

  if (rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel)) {
    return false;
  }

  return true;
}

/**
 * Ensures the Gateway-owned `backups` child directory exists directly under canonical stateRoot.
 *
 * Rules (M2 / Section 12):
 * - stateRoot itself is NEVER auto-created (Zero Directory Auto-Create).
 * - Only the exact internal child `backups` is created (recursive = false).
 * - If absent, creates with recursive=false.
 * - If present, verifies it is a directory, not a symlink, and canonical realpath is inside stateRoot.
 * - Fails closed on any invalidity or path escape.
 *
 * @param {string} canonicalStateRoot - Validated canonical stateRoot path.
 * @param {object} [options={}] - Optional injected dependencies.
 * @param {object} [options.fs] - Injected filesystem module.
 * @returns {string} Canonical backupRoot path.
 * @throws {Error} If stateRoot does not exist, or backups child is invalid / escapes.
 */
function resolveFs(options) {
  if (options && options.fs) return options.fs;
  if (options && typeof options.readdirSync === 'function') return options;
  return fs;
}

function ensureBackupsDirectory(canonicalStateRoot, options = {}) {
  if (typeof canonicalStateRoot !== 'string' || !canonicalStateRoot.trim()) {
    throw new Error('canonicalStateRoot must be a non-empty string (fail-closed)');
  }

  const fsModule = resolveFs(options);
  const backupRoot = path.join(canonicalStateRoot, BACKUP_DIRECTORY_NAME);

  // Pre-check nominal containment
  if (!isPathInside(backupRoot, canonicalStateRoot)) {
    throw new Error(
      `Backup directory path escapes canonical state root: '${backupRoot}' is outside '${canonicalStateRoot}'`
    );
  }

  let stat = null;
  try {
    const s = fsModule.lstatSync(backupRoot);
    if (s) {
      stat = s;
    }
  } catch (err) {
    if (!err || err.code !== 'ENOENT') {
      throw new Error(`Failed to inspect backup directory: ${err ? err.code || err.name : 'UnknownError'}`);
    }
  }

  if (!stat && typeof fsModule.mkdirSync === 'function') {
    // Attempt single directory creation (recursive=false)
    try {
      fsModule.mkdirSync(backupRoot, { recursive: false });
    } catch (err) {
      throw new Error(`Failed to create backup directory: ${err ? err.code || err.name : 'UnknownError'}`);
    }

    try {
      const s = fsModule.lstatSync(backupRoot);
      if (s) {
        stat = s;
      }
    } catch (err) {
      throw new Error(`Backup directory absent after creation: ${err ? err.code || err.name : 'UnknownError'}`);
    }
  }

  if (stat) {
    if (typeof stat.isSymbolicLink === 'function' && stat.isSymbolicLink()) {
      throw new Error('Backup directory must not be a symbolic link (fail-closed)');
    }

    if (typeof stat.isDirectory === 'function' && !stat.isDirectory()) {
      throw new Error('Backup directory must be a directory (fail-closed)');
    }
  }

  // Canonical realpath containment check
  let canonicalBackupRoot = backupRoot;
  if (typeof fsModule.realpathSync === 'function') {
    try {
      canonicalBackupRoot = fsModule.realpathSync(backupRoot);
    } catch (err) {
      throw new Error(`Failed to resolve realpath for backup directory: ${err ? err.code || err.name : 'UnknownError'}`);
    }
  }

  if (!isPathInside(canonicalBackupRoot, canonicalStateRoot)) {
    throw new Error('Backup directory canonical realpath escapes canonical state root (fail-closed)');
  }

  return canonicalBackupRoot;
}

/**
 * Safely moves legacy root-level canonical backups into `stateRoot/backups/`.
 *
 * Rules (M3 / Section 14):
 * - Direct children of stateRoot only.
 * - Only files matching CANONICAL_BACKUP_NAME_REGEX.
 * - Must be regular file, non-symlink, and realpath directly within canonical stateRoot.
 * - Destination must NOT already exist.
 * - If collision: never overwrite, preserve source, record warning, no raw path log.
 * - If rename fails: preserve source, record warning, continue without crash.
 * - Never copies, never unlinks source separately, never touches non-canonical files.
 *
 * @param {string} canonicalStateRoot
 * @param {string} canonicalBackupRoot
 * @param {object} [options={}]
 * @returns {{ migratedCount: number, warnings: string[] }}
 */
function migrateLegacyBackups(canonicalStateRoot, canonicalBackupRoot, options = {}) {
  const fsModule = resolveFs(options);
  const logger = options.logger || console;
  const warnings = [];
  let migratedCount = 0;

  let entries = [];
  try {
    entries = fsModule.readdirSync(canonicalStateRoot);
  } catch (err) {
    const diagnostic = formatBoundedDiagnostic('LegacyMigrationReaddir', err);
    if (typeof logger.warn === 'function') {
      logger.warn(diagnostic);
    }
    warnings.push('LEGACY_BACKUP_MIGRATION_FAILED');
    return { migratedCount, warnings };
  }

  for (const entry of entries) {
    const filename = typeof entry === 'string' ? entry : entry.name;
    if (typeof filename !== 'string' || !CANONICAL_BACKUP_NAME_REGEX.test(filename)) {
      continue;
    }

    const sourcePath = path.join(canonicalStateRoot, filename);
    const destPath = path.join(canonicalBackupRoot, filename);

    let srcStat;
    try {
      srcStat = fsModule.lstatSync(sourcePath);
    } catch (err) {
      continue;
    }

    if (typeof srcStat.isSymbolicLink === 'function' && srcStat.isSymbolicLink()) {
      continue;
    }
    if (typeof srcStat.isFile === 'function' && !srcStat.isFile()) {
      continue;
    }

    // Canonical source containment
    try {
      const srcReal = fsModule.realpathSync(sourcePath);
      if (path.dirname(srcReal) !== canonicalStateRoot) {
        continue;
      }
    } catch (_) {
      continue;
    }

    // Destination existence check (no overwrite)
    let destStat = null;
    try {
      destStat = fsModule.lstatSync(destPath);
    } catch (err) {
      if (!err || err.code !== 'ENOENT') {
        const diag = formatBoundedDiagnostic('LegacyMigrationDestCheck', err);
        if (typeof logger.warn === 'function') logger.warn(diag);
        warnings.push('LEGACY_BACKUP_MIGRATION_FAILED');
        continue;
      }
    }

    if (destStat !== null) {
      // Collision: refuse overwrite, preserve source, record warning
      const diag = formatBoundedDiagnostic('LegacyMigrationCollision', { name: 'Collision', code: 'EEXIST' });
      if (typeof logger.warn === 'function') logger.warn(diag);
      warnings.push('LEGACY_BACKUP_COLLISION');
      continue;
    }

    // Attempt atomic same-volume rename
    try {
      fsModule.renameSync(sourcePath, destPath);
      migratedCount++;
    } catch (renameErr) {
      // Rename failure: preserve source, record warning, no fallback destructive ops
      const diag = formatBoundedDiagnostic('LegacyMigrationRename', renameErr);
      if (typeof logger.warn === 'function') logger.warn(diag);
      warnings.push('LEGACY_BACKUP_MIGRATION_FAILED');
    }
  }

  return { migratedCount, warnings };
}

/**
 * Inventories canonical backups in `backups/` and executes retention cleanup.
 *
 * Rules (M5-M8, M14, M15 / Section 18):
 * - Direct children of backupRoot only.
 * - Eligible backup: canonical filename, regular file, non-symlink, contained.
 * - Unknown files: NEVER deleted, recorded as UNKNOWN_BACKUP_DIRECTORY_ENTRY warning.
 * - Sort order: mtime ascending (oldest first); tie-break: filename lexical ascending.
 * - Protected: newest `minKeepCount` backups + `justCreatedPath`.
 * - If protected backups exceed `maxTotalBytes`: preserve all protected, WARN with MIN_KEEP_CAPACITY_CONFLICT.
 * - If any single backup exceeds `maxTotalBytes`: preserve, ALERT with SINGLE_BACKUP_EXCEEDS_CAPACITY.
 * - Deletion executed ONLY if `verifiedBackupSucceededThisCycle === true`.
 * - Unlink failure: WARN with BACKUP_DELETE_FAILED, continue safely without tight-loop.
 *
 * @param {string} canonicalBackupRoot
 * @param {object} [options={}]
 * @returns {object} Inventory & cleanup result.
 */
function inventoryAndCleanupBackups(canonicalBackupRoot, options = {}) {
  const fsModule = resolveFs(options);
  const logger = options.logger || console;
  const maxTotalBytes =
    typeof options.maxTotalBytes === 'number' && options.maxTotalBytes > 0
      ? options.maxTotalBytes
      : DEFAULT_MAX_TOTAL_BYTES;
  const minKeepCount =
    typeof options.minKeepCount === 'number' && options.minKeepCount >= 1
      ? options.minKeepCount
      : DEFAULT_MIN_KEEP_COUNT;
  const justCreatedPath = options.justCreatedPath || null;
  const verifiedBackupSucceededThisCycle = options.verifiedBackupSucceededThisCycle === true;

  const warnings = [];
  const alerts = [];
  const eligibleBackups = [];

  let entries = [];
  try {
    entries = fsModule.readdirSync(canonicalBackupRoot);
  } catch (err) {
    const diag = formatBoundedDiagnostic('InventoryReaddir', err);
    if (typeof logger.warn === 'function') logger.warn(diag);
    return {
      backupCount: 0,
      totalBytes: 0,
      eligibleBackups: [],
      deletedBackups: [],
      warnings: ['UNKNOWN_BACKUP_DIRECTORY_ENTRY'],
      alerts: [],
    };
  }

  for (const entry of entries) {
    const filename = typeof entry === 'string' ? entry : entry.name;
    const fullPath = path.join(canonicalBackupRoot, filename);

    if (typeof filename !== 'string' || !CANONICAL_BACKUP_NAME_REGEX.test(filename)) {
      // Non-canonical entry: never delete, record warning
      warnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
      continue;
    }

    let stat;
    try {
      stat = fsModule.lstatSync(fullPath);
    } catch (err) {
      warnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
      continue;
    }

    if (typeof stat.isSymbolicLink === 'function' && stat.isSymbolicLink()) {
      warnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
      continue;
    }

    if (typeof stat.isFile === 'function' && !stat.isFile()) {
      warnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
      continue;
    }

    // Realpath containment check
    try {
      const real = fsModule.realpathSync(fullPath);
      if (!isPathInside(real, canonicalBackupRoot)) {
        warnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
        continue;
      }
    } catch (_) {
      warnings.push('UNKNOWN_BACKUP_DIRECTORY_ENTRY');
      continue;
    }

    let mtimeMs = null;
    if (typeof stat.mtimeMs === 'number' && Number.isFinite(stat.mtimeMs)) {
      mtimeMs = stat.mtimeMs;
    } else if (stat.mtime instanceof Date) {
      mtimeMs = stat.mtime.getTime();
    }
    if (mtimeMs === null || !Number.isFinite(mtimeMs)) {
      mtimeMs = 0;
    }

    const size = typeof stat.size === 'number' && Number.isFinite(stat.size) ? stat.size : 0;

    eligibleBackups.push({
      filename,
      fullPath,
      mtimeMs,
      size,
    });
  }

  // Sort: primary mtimeMs ascending, secondary filename lexical ascending
  eligibleBackups.sort((a, b) => {
    if (a.mtimeMs !== b.mtimeMs) {
      return a.mtimeMs - b.mtimeMs;
    }
    return a.filename.localeCompare(b.filename);
  });

  let currentTotalBytes = eligibleBackups.reduce((acc, b) => acc + b.size, 0);

  // Check single file exceeding maxTotalBytes
  for (const b of eligibleBackups) {
    if (b.size > maxTotalBytes) {
      alerts.push('SINGLE_BACKUP_EXCEEDS_CAPACITY');
      break;
    }
  }

  // Determine protected set: newest minKeepCount + justCreatedPath
  const protectedPaths = new Set();
  const protectedSlice = eligibleBackups.slice(-minKeepCount);
  for (const p of protectedSlice) {
    protectedPaths.add(p.fullPath);
  }
  if (justCreatedPath) {
    protectedPaths.add(justCreatedPath);
  }

  // Check min-keep capacity conflict: protected backups alone exceed capacity
  const protectedBytes = eligibleBackups
    .filter((b) => protectedPaths.has(b.fullPath))
    .reduce((acc, b) => acc + b.size, 0);

  if (protectedBytes > maxTotalBytes) {
    warnings.push('MIN_KEEP_CAPACITY_CONFLICT');
  }

  const deletedBackups = [];

  // Deletion logic: executed ONLY if verified new backup succeeded this cycle
  if (verifiedBackupSucceededThisCycle && currentTotalBytes > maxTotalBytes) {
    for (const backup of eligibleBackups) {
      if (currentTotalBytes <= maxTotalBytes) {
        break;
      }
      if (protectedPaths.has(backup.fullPath)) {
        continue;
      }

      try {
        fsModule.unlinkSync(backup.fullPath);
        currentTotalBytes -= backup.size;
        deletedBackups.push(backup);
      } catch (unlinkErr) {
        const diag = formatBoundedDiagnostic('DeleteBackup', unlinkErr);
        if (typeof logger.warn === 'function') logger.warn(diag);
        warnings.push('BACKUP_DELETE_FAILED');
      }
    }
  }

  const survivingBackups = eligibleBackups.filter((b) => !deletedBackups.some((d) => d.fullPath === b.fullPath));
  const finalTotalBytes = survivingBackups.reduce((acc, b) => acc + b.size, 0);

  return {
    backupCount: survivingBackups.length,
    totalBytes: finalTotalBytes,
    eligibleBackups: survivingBackups,
    deletedBackups,
    warnings,
    alerts,
  };
}

/**
 * Checks available free disk space on the backupRoot volume using fs.statfsSync.
 *
 * Rules (M9 / Section 17):
 * - Live DB path: repository.databasePath.
 * - Required free space: availableBytes >= currentDatabaseSizeBytes * 2.
 * - If space insufficient: skip backup, ALERT with INSUFFICIENT_FREE_SPACE.
 * - If statfs/db-stat fails: skip backup, ALERT with FREE_SPACE_CHECK_FAILED.
 * - Bounded non-secret diagnostics only (no paths, no raw messages).
 *
 * @param {string} backupRoot
 * @param {string} liveDbPath
 * @param {object} [options={}]
 * @returns {{ ok: boolean, reason?: string, availableBytes?: number, requiredBytes?: number }}
 */
function checkFreeSpaceForBackup(backupRoot, liveDbPath, options = {}) {
  const fsModule = resolveFs(options);
  const logger = options.logger || console;
  const statfsSyncFn =
    typeof options.statfsSync === 'function'
      ? options.statfsSync
      : typeof fsModule.statfsSync === 'function'
      ? fsModule.statfsSync.bind(fsModule)
      : null;
  const multiplier =
    typeof options.multiplier === 'number' && options.multiplier > 0
      ? options.multiplier
      : FREE_SPACE_REQUIRED_MULTIPLIER;

  if (typeof liveDbPath !== 'string' || !liveDbPath.trim()) {
    const diag = formatBoundedDiagnostic('LiveDbPath', { name: 'InvalidPath', code: 'EINVAL' });
    if (typeof logger.error === 'function') logger.error(diag);
    return { ok: false, reason: 'FREE_SPACE_CHECK_FAILED' };
  }

  let dbSize = 0;
  try {
    const stat = fsModule.statSync(liveDbPath);
    dbSize = typeof stat.size === 'number' ? stat.size : 0;
  } catch (err) {
    const diag = formatBoundedDiagnostic('StatLiveDb', err);
    if (typeof logger.error === 'function') logger.error(diag);
    return { ok: false, reason: 'FREE_SPACE_CHECK_FAILED' };
  }

  if (!statfsSyncFn) {
    const diag = formatBoundedDiagnostic('StatfsSync', { name: 'MissingStatfs', code: 'ENOSYS' });
    if (typeof logger.error === 'function') logger.error(diag);
    return { ok: false, reason: 'FREE_SPACE_CHECK_FAILED' };
  }

  let statfsResult;
  try {
    statfsResult = statfsSyncFn(backupRoot);
  } catch (err) {
    const diag = formatBoundedDiagnostic('Statfs', err);
    if (typeof logger.error === 'function') logger.error(diag);
    return { ok: false, reason: 'FREE_SPACE_CHECK_FAILED' };
  }

  if (!statfsResult || typeof statfsResult !== 'object') {
    const diag = formatBoundedDiagnostic('StatfsPayload', { name: 'InvalidPayload', code: 'EINVAL' });
    if (typeof logger.error === 'function') logger.error(diag);
    return { ok: false, reason: 'FREE_SPACE_CHECK_FAILED' };
  }

  const bsize =
    typeof statfsResult.bsize === 'bigint'
      ? Number(statfsResult.bsize)
      : typeof statfsResult.bsize === 'number'
      ? statfsResult.bsize
      : 4096;

  const bavail =
    typeof statfsResult.bavail === 'bigint'
      ? Number(statfsResult.bavail)
      : typeof statfsResult.bavail === 'number'
      ? statfsResult.bavail
      : 0;

  const availableBytes = bavail * bsize;
  const requiredBytes = dbSize * multiplier;

  if (!Number.isFinite(availableBytes) || availableBytes < 0) {
    const diag = formatBoundedDiagnostic('StatfsCalc', { name: 'InvalidBytes', code: 'ERANGE' });
    if (typeof logger.error === 'function') logger.error(diag);
    return { ok: false, reason: 'FREE_SPACE_CHECK_FAILED' };
  }

  if (availableBytes < requiredBytes) {
    const diag = formatBoundedDiagnostic('FreeSpaceCheck', { name: 'InsufficientSpace', code: 'ENOSPC' });
    if (typeof logger.error === 'function') logger.error(diag);
    return {
      ok: false,
      reason: 'INSUFFICIENT_FREE_SPACE',
      availableBytes,
      requiredBytes,
    };
  }

  return {
    ok: true,
    availableBytes,
    requiredBytes,
  };
}

/**
 * Evaluates the overall backup health state based on operational conditions.
 *
 * Rules (M11, M12 / Section 19):
 * - Health levels: OK, WARN, ALERT (ALERT > WARN > OK).
 * - NO_SUCCESSFUL_BACKUP_48H: ALERT if lastSuccessAt is null or age >= 48h.
 * - CONSECUTIVE_BACKUP_FAILURES: ALERT if consecutiveFailures >= 3.
 * - Alerts: SINGLE_BACKUP_EXCEEDS_CAPACITY, INSUFFICIENT_FREE_SPACE, FREE_SPACE_CHECK_FAILED.
 * - Warnings: MIN_KEEP_CAPACITY_CONFLICT, BACKUP_DELETE_FAILED, UNKNOWN_BACKUP_DIRECTORY_ENTRY,
 *             LEGACY_BACKUP_COLLISION, LEGACY_BACKUP_MIGRATION_FAILED.
 * - reasonCodes: deterministic sorted unique array.
 *
 * @param {object} params
 * @returns {object} Health document.
 */
function evaluateHealthState(params) {
  const nowMs = typeof params.nowMs === 'number' ? params.nowMs : Date.now();
  const lastSuccessAt =
    typeof params.lastSuccessAt === 'number' && params.lastSuccessAt > 0
      ? params.lastSuccessAt
      : null;
  const consecutiveFailures =
    typeof params.consecutiveFailures === 'number' ? params.consecutiveFailures : 0;
  const backupCount = typeof params.backupCount === 'number' ? params.backupCount : 0;
  const totalBytes = typeof params.totalBytes === 'number' ? params.totalBytes : 0;
  const maxTotalBytes =
    typeof params.maxTotalBytes === 'number' ? params.maxTotalBytes : DEFAULT_MAX_TOTAL_BYTES;
  const minKeepCount =
    typeof params.minKeepCount === 'number' ? params.minKeepCount : DEFAULT_MIN_KEEP_COUNT;

  const rawCodes = Array.isArray(params.extraReasonCodes) ? [...params.extraReasonCodes] : [];

  // 48h health threshold check
  if (lastSuccessAt === null || nowMs - lastSuccessAt >= NO_SUCCESS_ALERT_MS) {
    rawCodes.push('NO_SUCCESSFUL_BACKUP_48H');
  }

  // Consecutive failure check
  if (consecutiveFailures >= CONSECUTIVE_FAILURE_ALERT_THRESHOLD) {
    rawCodes.push('CONSECUTIVE_BACKUP_FAILURES');
  }

  const reasonCodes = Array.from(new Set(rawCodes)).sort();

  const alertCodes = new Set([
    'NO_SUCCESSFUL_BACKUP_48H',
    'CONSECUTIVE_BACKUP_FAILURES',
    'SINGLE_BACKUP_EXCEEDS_CAPACITY',
    'INSUFFICIENT_FREE_SPACE',
    'FREE_SPACE_CHECK_FAILED',
  ]);

  let state = 'OK';
  for (const code of reasonCodes) {
    if (alertCodes.has(code)) {
      state = 'ALERT';
      break;
    }
  }

  if (state !== 'ALERT' && reasonCodes.length > 0) {
    state = 'WARN';
  }

  return {
    state,
    reasonCodes,
    lastSuccessAt,
    backupCount,
    totalBytes,
    maxTotalBytes,
    minKeepCount,
    updatedAt: nowMs,
  };
}

/**
 * Writes the backup health state document to `stateRoot/backup-health.json` atomically.
 *
 * Rules (M12, M13 / Section 20):
 * - Target: stateRoot/backup-health.json (NOT inside backups/).
 * - Temp file inside stateRoot with random suffix.
 * - UTF-8 formatted JSON.
 * - Atomic renameSync.
 * - Temp file best-effort cleanup on failure.
 * - Bounded diagnostics ONLY on error (NEVER logs target path, temp path, or raw message).
 *
 * @param {string} canonicalStateRoot
 * @param {object} healthData
 * @param {object} [options={}]
 * @returns {boolean} True if successfully written, false otherwise.
 */
function writeBackupHealthAtomic(canonicalStateRoot, healthData, options = {}) {
  const fsModule = resolveFs(options);
  const logger = options.logger || console;

  if (typeof canonicalStateRoot !== 'string' || !canonicalStateRoot.trim()) {
    const diag = formatBoundedDiagnostic('WriteHealth', { name: 'InvalidStateRoot', code: 'EINVAL' });
    if (typeof logger.error === 'function') logger.error(diag);
    return false;
  }

  if (typeof fsModule.writeFileSync !== 'function') {
    return false;
  }

  const targetPath = path.join(canonicalStateRoot, BACKUP_HEALTH_FILENAME);
  const randomSuffix = Math.random().toString(36).slice(2, 10);
  const tmpFilename = `${BACKUP_HEALTH_FILENAME}.${process.pid}.${Date.now()}.${randomSuffix}.tmp`;
  const tmpPath = path.join(canonicalStateRoot, tmpFilename);

  // Confinement check
  if (!isPathInside(tmpPath, canonicalStateRoot) || !isPathInside(targetPath, canonicalStateRoot)) {
    const diag = formatBoundedDiagnostic('WriteHealth', { name: 'PathEscape', code: 'EPERM' });
    if (typeof logger.error === 'function') logger.error(diag);
    return false;
  }

  const payload = JSON.stringify(healthData, null, 2);

  try {
    fsModule.writeFileSync(tmpPath, payload, 'utf8');
    fsModule.renameSync(tmpPath, targetPath);
    return true;
  } catch (err) {
    try {
      if (typeof fsModule.unlinkSync === 'function') {
        fsModule.unlinkSync(tmpPath);
      }
    } catch (_) {
      // Best-effort cleanup
    }
    const diag = formatBoundedDiagnostic('WriteHealth', err);
    if (typeof logger.error === 'function') logger.error(diag);
    return false;
  }
}

module.exports = {
  BACKUP_DIRECTORY_NAME,
  BACKUP_HEALTH_FILENAME,
  CANONICAL_BACKUP_NAME_REGEX,
  DEFAULT_MAX_TOTAL_BYTES,
  DEFAULT_MIN_KEEP_COUNT,
  NO_SUCCESS_ALERT_MS,
  CONSECUTIVE_FAILURE_ALERT_THRESHOLD,
  FREE_SPACE_REQUIRED_MULTIPLIER,
  SAFE_TOKEN_REGEX,
  formatBoundedDiagnostic,
  isPathInside,
  ensureBackupsDirectory,
  migrateLegacyBackups,
  inventoryAndCleanupBackups,
  checkFreeSpaceForBackup,
  evaluateHealthState,
  writeBackupHealthAtomic,
};
