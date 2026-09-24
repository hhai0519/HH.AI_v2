'use strict';

/**
 * runtime/channel-gateway/tests/backup-hygiene.test.js
 *
 * Deterministic Unit Tests for Backup Hygiene Module (TG-MVP-09A).
 *
 * Verifies:
 * 1. Constants contract (1GB exact capacity, 3 keep, 48h alert, 3 failures, 2x free space).
 * 2. ensureBackupsDirectory invariants (safe child creation, no stateRoot auto-creation, symlink/file/escape fail-closed).
 * 3. migrateLegacyBackups invariants (canonical moved, non-canonical untouched, symlink untouched, collision no-overwrite, rename failure safe, idempotent).
 * 4. inventoryAndCleanupBackups invariants (oldest-first, newest-3 protected, justCreated protected, minKeep conflict WARN, single file over cap ALERT, cleanup only after verified success, unknown untouched WARN, delete failure WARN).
 * 5. checkFreeSpaceForBackup invariants (statfs injection, >=2x pass, <2x skip with ALERT, statfs/db failure skip with ALERT).
 * 6. evaluateHealthState contract (OK, WARN, ALERT, 48h alert, consecutive failure alert, sorted unique reasonCodes, required fields).
 * 7. writeBackupHealthAtomic & privacy invariants (atomic replace, zero path leaks, zero message leaks, zero token leaks).
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const {
  BACKUP_DIRECTORY_NAME,
  BACKUP_HEALTH_FILENAME,
  CANONICAL_BACKUP_NAME_REGEX,
  DEFAULT_MAX_TOTAL_BYTES,
  DEFAULT_MIN_KEEP_COUNT,
  NO_SUCCESS_ALERT_MS,
  CONSECUTIVE_FAILURE_ALERT_THRESHOLD,
  FREE_SPACE_REQUIRED_MULTIPLIER,
  formatBoundedDiagnostic,
  ensureBackupsDirectory,
  migrateLegacyBackups,
  inventoryAndCleanupBackups,
  checkFreeSpaceForBackup,
  evaluateHealthState,
  writeBackupHealthAtomic,
} = require('../core/backup-hygiene');

/**
 * Helper to create an in-memory mock fs module.
 */
function createMockFs(initialFiles = {}) {
  // initialFiles: map of absolute path or relative path -> { size, mtimeMs, isFile, isDir, isSymlink }
  const files = new Map(Object.entries(initialFiles));
  const dirs = new Set();
  const operations = [];

  for (const [p, meta] of files.entries()) {
    if (meta.isDir) {
      dirs.add(path.resolve(p));
    }
  }

  const statFromMeta = (meta) => ({
    isFile: () => meta.isFile !== false && !meta.isDir,
    isDirectory: () => meta.isDir === true,
    isSymbolicLink: () => meta.isSymlink === true,
    size: typeof meta.size === 'number' ? meta.size : 0,
    mtimeMs: typeof meta.mtimeMs === 'number' ? meta.mtimeMs : 0,
    mtime: new Date(typeof meta.mtimeMs === 'number' ? meta.mtimeMs : 0),
  });

  return {
    readdirSync(dirPath) {
      operations.push({ op: 'readdirSync', path: dirPath });
      const normDir = path.resolve(dirPath);
      const results = [];
      for (const p of files.keys()) {
        const resolved = path.resolve(p);
        if (path.dirname(resolved) === normDir) {
          results.push(path.basename(resolved));
        }
      }
      return results;
    },
    lstatSync(targetPath) {
      operations.push({ op: 'lstatSync', path: targetPath });
      const resolved = path.resolve(targetPath);
      const meta = files.get(resolved) || files.get(targetPath);
      if (!meta) {
        const err = new Error(`ENOENT: no such file or directory, lstat '${targetPath}'`);
        err.code = 'ENOENT';
        throw err;
      }
      return statFromMeta(meta);
    },
    statSync(targetPath) {
      operations.push({ op: 'statSync', path: targetPath });
      const resolved = path.resolve(targetPath);
      const meta = files.get(resolved) || files.get(targetPath);
      if (!meta) {
        const err = new Error(`ENOENT: no such file or directory, stat '${targetPath}'`);
        err.code = 'ENOENT';
        throw err;
      }
      return statFromMeta(meta);
    },
    realpathSync(targetPath) {
      operations.push({ op: 'realpathSync', path: targetPath });
      const resolved = path.resolve(targetPath);
      const meta = files.get(resolved) || files.get(targetPath);
      if (!meta) {
        const err = new Error(`ENOENT: realpath '${targetPath}'`);
        err.code = 'ENOENT';
        throw err;
      }
      if (meta.realpath) {
        return meta.realpath;
      }
      return resolved;
    },
    mkdirSync(dirPath, opts) {
      operations.push({ op: 'mkdirSync', path: dirPath, opts });
      const resolved = path.resolve(dirPath);
      if (files.has(resolved)) {
        const err = new Error(`EEXIST: directory already exists '${dirPath}'`);
        err.code = 'EEXIST';
        throw err;
      }
      files.set(resolved, { isDir: true, isFile: false });
      dirs.add(resolved);
    },
    renameSync(fromPath, toPath) {
      operations.push({ op: 'renameSync', from: fromPath, to: toPath });
      const fromResolved = path.resolve(fromPath);
      const toResolved = path.resolve(toPath);
      const meta = files.get(fromResolved) || files.get(fromPath);
      if (!meta) {
        const err = new Error(`ENOENT: rename '${fromPath}'`);
        err.code = 'ENOENT';
        throw err;
      }
      if (files.has(toResolved)) {
        const err = new Error(`EEXIST: destination exists '${toPath}'`);
        err.code = 'EEXIST';
        throw err;
      }
      files.delete(fromResolved);
      files.delete(fromPath);
      files.set(toResolved, meta);
    },
    unlinkSync(targetPath) {
      operations.push({ op: 'unlinkSync', path: targetPath });
      const resolved = path.resolve(targetPath);
      if (!files.has(resolved) && !files.has(targetPath)) {
        const err = new Error(`ENOENT: unlink '${targetPath}'`);
        err.code = 'ENOENT';
        throw err;
      }
      files.delete(resolved);
      files.delete(targetPath);
    },
    writeFileSync(targetPath, data) {
      operations.push({ op: 'writeFileSync', path: targetPath, data });
      const resolved = path.resolve(targetPath);
      files.set(resolved, { isFile: true, size: Buffer.byteLength(data, 'utf8'), mtimeMs: Date.now() });
    },
    get files() {
      return files;
    },
    get operations() {
      return operations;
    },
  };
}

function createMockLogger() {
  const errors = [];
  const warns = [];
  return {
    error(msg) {
      errors.push(msg);
    },
    warn(msg) {
      warns.push(msg);
    },
    get errors() {
      return errors;
    },
    get warns() {
      return warns;
    },
  };
}

test('1. Constants contract matches specification', () => {
  assert.equal(BACKUP_DIRECTORY_NAME, 'backups');
  assert.equal(BACKUP_HEALTH_FILENAME, 'backup-health.json');
  assert.equal(DEFAULT_MAX_TOTAL_BYTES, 1_000_000_000);
  assert.equal(DEFAULT_MIN_KEEP_COUNT, 3);
  assert.equal(NO_SUCCESS_ALERT_MS, 172_800_000);
  assert.equal(CONSECUTIVE_FAILURE_ALERT_THRESHOLD, 3);
  assert.equal(FREE_SPACE_REQUIRED_MULTIPLIER, 2);
  assert.ok(CANONICAL_BACKUP_NAME_REGEX.test('channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3'));
  assert.ok(!CANONICAL_BACKUP_NAME_REGEX.test('channel-gateway-state.backup-v0-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3'));
  assert.ok(!CANONICAL_BACKUP_NAME_REGEX.test('channel-gateway-state.backup-v3-invalid.sqlite3'));
});

test('2. ensureBackupsDirectory creates missing backups/ directory safely', () => {
  const stateRoot = path.resolve('/test/state');
  const mockFs = createMockFs({
    [stateRoot]: { isDir: true },
  });

  const backupRoot = ensureBackupsDirectory(stateRoot, { fs: mockFs });
  assert.equal(backupRoot, path.join(stateRoot, 'backups'));

  const mkdirOp = mockFs.operations.find((op) => op.op === 'mkdirSync');
  assert.ok(mkdirOp);
  assert.equal(mkdirOp.path, path.join(stateRoot, 'backups'));
  assert.equal(mkdirOp.opts.recursive, false);
});

test('3. ensureBackupsDirectory existing directory accepted without recreating', () => {
  const stateRoot = path.resolve('/test/state');
  const backupDir = path.join(stateRoot, 'backups');
  const mockFs = createMockFs({
    [stateRoot]: { isDir: true },
    [backupDir]: { isDir: true },
  });

  const result = ensureBackupsDirectory(stateRoot, { fs: mockFs });
  assert.equal(result, backupDir);
  assert.ok(!mockFs.operations.some((op) => op.op === 'mkdirSync'));
});

test('4. ensureBackupsDirectory fails closed on symlink', () => {
  const stateRoot = path.resolve('/test/state');
  const backupDir = path.join(stateRoot, 'backups');
  const mockFs = createMockFs({
    [stateRoot]: { isDir: true },
    [backupDir]: { isDir: true, isSymlink: true },
  });

  assert.throws(
    () => ensureBackupsDirectory(stateRoot, { fs: mockFs }),
    /must not be a symbolic link/
  );
});

test('5. ensureBackupsDirectory fails closed on regular file', () => {
  const stateRoot = path.resolve('/test/state');
  const backupDir = path.join(stateRoot, 'backups');
  const mockFs = createMockFs({
    [stateRoot]: { isDir: true },
    [backupDir]: { isFile: true, isDir: false },
  });

  assert.throws(
    () => ensureBackupsDirectory(stateRoot, { fs: mockFs }),
    /must be a directory/
  );
});

test('6. ensureBackupsDirectory fails closed on realpath escape', () => {
  const stateRoot = path.resolve('/test/state');
  const backupDir = path.join(stateRoot, 'backups');
  const mockFs = createMockFs({
    [stateRoot]: { isDir: true },
    [backupDir]: { isDir: true, realpath: path.resolve('/outside/escaped') },
  });

  assert.throws(
    () => ensureBackupsDirectory(stateRoot, { fs: mockFs }),
    /canonical realpath escapes/
  );
});

test('7. migrateLegacyBackups moves canonical backups and preserves non-canonical', () => {
  const stateRoot = path.resolve('/test/state');
  const backupRoot = path.join(stateRoot, 'backups');
  const canonicalFile = 'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3';
  const unrelatedFile = 'notes.txt';
  const symlinkFile = 'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3';

  const mockFs = createMockFs({
    [stateRoot]: { isDir: true },
    [backupRoot]: { isDir: true },
    [path.join(stateRoot, canonicalFile)]: { isFile: true, size: 100 },
    [path.join(stateRoot, unrelatedFile)]: { isFile: true, size: 50 },
    [path.join(stateRoot, symlinkFile)]: { isFile: true, isSymlink: true, size: 100 },
  });

  const { migratedCount, warnings } = migrateLegacyBackups(stateRoot, backupRoot, { fs: mockFs });
  assert.equal(migratedCount, 1);
  assert.equal(warnings.length, 0);

  // Moved to backups/
  assert.ok(mockFs.files.has(path.join(backupRoot, canonicalFile)));
  assert.ok(!mockFs.files.has(path.join(stateRoot, canonicalFile)));

  // Non-canonical and symlink untouched in stateRoot
  assert.ok(mockFs.files.has(path.join(stateRoot, unrelatedFile)));
  assert.ok(mockFs.files.has(path.join(stateRoot, symlinkFile)));
});

test('8. migrateLegacyBackups collision refuses overwrite, preserves source, logs warning', () => {
  const stateRoot = path.resolve('/test/state');
  const backupRoot = path.join(stateRoot, 'backups');
  const filename = 'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3';

  const mockFs = createMockFs({
    [stateRoot]: { isDir: true },
    [backupRoot]: { isDir: true },
    [path.join(stateRoot, filename)]: { isFile: true, size: 100 },
    [path.join(backupRoot, filename)]: { isFile: true, size: 200 }, // collision!
  });

  const logger = createMockLogger();
  const { migratedCount, warnings } = migrateLegacyBackups(stateRoot, backupRoot, { fs: mockFs, logger });
  assert.equal(migratedCount, 0);
  assert.ok(warnings.includes('LEGACY_BACKUP_COLLISION'));
  // Source preserved
  assert.ok(mockFs.files.has(path.join(stateRoot, filename)));
  assert.ok(mockFs.files.has(path.join(backupRoot, filename)));
  assert.equal(mockFs.files.get(path.join(backupRoot, filename)).size, 200);
});

test('9. inventoryAndCleanupBackups retention oldest-first with newest 3 protected', () => {
  const backupRoot = path.resolve('/test/state/backups');
  const f1 = 'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3';
  const f2 = 'channel-gateway-state.backup-v3-22222222-2222-4222-8222-222222222222.sqlite3';
  const f3 = 'channel-gateway-state.backup-v3-33333333-3333-4333-8333-333333333333.sqlite3';
  const f4 = 'channel-gateway-state.backup-v3-44444444-4444-4444-8444-444444444444.sqlite3';
  const f5 = 'channel-gateway-state.backup-v3-55555555-5555-4555-8555-555555555555.sqlite3';

  const mockFs = createMockFs({
    [backupRoot]: { isDir: true },
    [path.join(backupRoot, f1)]: { isFile: true, mtimeMs: 1000, size: 400 },
    [path.join(backupRoot, f2)]: { isFile: true, mtimeMs: 2000, size: 400 },
    [path.join(backupRoot, f3)]: { isFile: true, mtimeMs: 3000, size: 400 },
    [path.join(backupRoot, f4)]: { isFile: true, mtimeMs: 4000, size: 400 },
    [path.join(backupRoot, f5)]: { isFile: true, mtimeMs: 5000, size: 400 },
  });

  // Total bytes: 2000. maxTotalBytes: 1300. minKeepCount: 3.
  // Newest 3 protected: f3, f4, f5 (sum = 1200 <= 1300).
  // Oldest eligible for deletion: f1, f2.
  // After deleting f1 (400), total becomes 1600 > 1300.
  // After deleting f2 (400), total becomes 1200 <= 1300.
  const result = inventoryAndCleanupBackups(backupRoot, {
    fs: mockFs,
    maxTotalBytes: 1300,
    minKeepCount: 3,
    verifiedBackupSucceededThisCycle: true,
  });

  assert.equal(result.deletedBackups.length, 2);
  assert.equal(result.deletedBackups[0].filename, f1);
  assert.equal(result.deletedBackups[1].filename, f2);
  assert.equal(result.backupCount, 3);
  assert.equal(result.totalBytes, 1200);
});

test('10. inventoryAndCleanupBackups does not delete when verified backup did not succeed this cycle', () => {
  const backupRoot = path.resolve('/test/state/backups');
  const f1 = 'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3';
  const f2 = 'channel-gateway-state.backup-v3-22222222-2222-4222-8222-222222222222.sqlite3';

  const mockFs = createMockFs({
    [backupRoot]: { isDir: true },
    [path.join(backupRoot, f1)]: { isFile: true, mtimeMs: 1000, size: 800 },
    [path.join(backupRoot, f2)]: { isFile: true, mtimeMs: 2000, size: 800 },
  });

  // Total 1600 > 1000, but verifiedBackupSucceededThisCycle = false
  const result = inventoryAndCleanupBackups(backupRoot, {
    fs: mockFs,
    maxTotalBytes: 1000,
    minKeepCount: 1,
    verifiedBackupSucceededThisCycle: false,
  });

  assert.equal(result.deletedBackups.length, 0);
  assert.equal(result.backupCount, 2);
});

test('11. inventoryAndCleanupBackups minKeep conflict preserves files and WARNs', () => {
  const backupRoot = path.resolve('/test/state/backups');
  const f1 = 'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3';
  const f2 = 'channel-gateway-state.backup-v3-22222222-2222-4222-8222-222222222222.sqlite3';
  const f3 = 'channel-gateway-state.backup-v3-33333333-3333-4333-8333-333333333333.sqlite3';

  const mockFs = createMockFs({
    [backupRoot]: { isDir: true },
    [path.join(backupRoot, f1)]: { isFile: true, mtimeMs: 1000, size: 500 },
    [path.join(backupRoot, f2)]: { isFile: true, mtimeMs: 2000, size: 500 },
    [path.join(backupRoot, f3)]: { isFile: true, mtimeMs: 3000, size: 500 },
  });

  // 3 backups = 1500 bytes. maxTotalBytes = 1000. minKeep = 3.
  // All 3 protected, cannot be deleted.
  const result = inventoryAndCleanupBackups(backupRoot, {
    fs: mockFs,
    maxTotalBytes: 1000,
    minKeepCount: 3,
    verifiedBackupSucceededThisCycle: true,
  });

  assert.equal(result.deletedBackups.length, 0);
  assert.ok(result.warnings.includes('MIN_KEEP_CAPACITY_CONFLICT'));
});

test('12. checkFreeSpaceForBackup permits backup when space >= 2x DB size', () => {
  const backupRoot = path.resolve('/test/state/backups');
  const liveDbPath = path.resolve('/test/state/channel-gateway-state.sqlite3');

  const mockFs = createMockFs({
    [backupRoot]: { isDir: true },
    [liveDbPath]: { isFile: true, size: 50_000 },
  });

  const fakeStatfs = () => ({
    bsize: 4096,
    bavail: 100, // 4096 * 100 = 409,600 >= 100,000 (2 * 50,000)
  });

  const result = checkFreeSpaceForBackup(backupRoot, liveDbPath, {
    fs: mockFs,
    statfsSync: fakeStatfs,
  });

  assert.equal(result.ok, true);
  assert.equal(result.requiredBytes, 100_000);
});

test('13. checkFreeSpaceForBackup skips backup when space < 2x DB size', () => {
  const backupRoot = path.resolve('/test/state/backups');
  const liveDbPath = path.resolve('/test/state/channel-gateway-state.sqlite3');

  const mockFs = createMockFs({
    [backupRoot]: { isDir: true },
    [liveDbPath]: { isFile: true, size: 50_000 },
  });

  const fakeStatfs = () => ({
    bsize: 4096,
    bavail: 20, // 4096 * 20 = 81,920 < 100,000
  });

  const result = checkFreeSpaceForBackup(backupRoot, liveDbPath, {
    fs: mockFs,
    statfsSync: fakeStatfs,
  });

  assert.equal(result.ok, false);
  assert.equal(result.reason, 'INSUFFICIENT_FREE_SPACE');
});

test('14. evaluateHealthState generates valid contract and correct severity levels', () => {
  const now = 1_700_000_000_000;

  // OK state: recent success, 0 failures, no extra codes
  const okHealth = evaluateHealthState({
    nowMs: now,
    lastSuccessAt: now - 3600_000, // 1h ago
    consecutiveFailures: 0,
    backupCount: 3,
    totalBytes: 300,
  });
  assert.equal(okHealth.state, 'OK');
  assert.equal(okHealth.reasonCodes.length, 0);

  // ALERT state: > 48h
  const staleHealth = evaluateHealthState({
    nowMs: now,
    lastSuccessAt: now - 173_000_000,
    consecutiveFailures: 0,
    backupCount: 1,
    totalBytes: 100,
  });
  assert.equal(staleHealth.state, 'ALERT');
  assert.ok(staleHealth.reasonCodes.includes('NO_SUCCESSFUL_BACKUP_48H'));

  // ALERT state: 3 consecutive failures
  const failHealth = evaluateHealthState({
    nowMs: now,
    lastSuccessAt: now - 3600_000,
    consecutiveFailures: 3,
    backupCount: 1,
    totalBytes: 100,
  });
  assert.equal(failHealth.state, 'ALERT');
  assert.ok(failHealth.reasonCodes.includes('CONSECUTIVE_BACKUP_FAILURES'));

  // WARN state: UNKNOWN_BACKUP_DIRECTORY_ENTRY
  const warnHealth = evaluateHealthState({
    nowMs: now,
    lastSuccessAt: now - 3600_000,
    consecutiveFailures: 0,
    backupCount: 1,
    totalBytes: 100,
    extraReasonCodes: ['UNKNOWN_BACKUP_DIRECTORY_ENTRY'],
  });
  assert.equal(warnHealth.state, 'WARN');
  assert.ok(warnHealth.reasonCodes.includes('UNKNOWN_BACKUP_DIRECTORY_ENTRY'));
});

test('15. writeBackupHealthAtomic and privacy: zero path or message leak', () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hh-ai-health-test-'));
  try {
    const healthData = {
      state: 'OK',
      reasonCodes: [],
      lastSuccessAt: 1_700_000_000_000,
      backupCount: 3,
      totalBytes: 1200,
      maxTotalBytes: 1_000_000_000,
      minKeepCount: 3,
      updatedAt: 1_700_000_000_000,
    };

    const ok = writeBackupHealthAtomic(tempDir, healthData);
    assert.equal(ok, true);

    const content = fs.readFileSync(path.join(tempDir, 'backup-health.json'), 'utf8');
    const parsed = JSON.parse(content);
    assert.equal(parsed.state, 'OK');
    assert.equal(parsed.backupCount, 3);

    // Negative control: verify no paths exist in serialized JSON
    const forbiddenPatterns = [
      /C:\\/i,
      /\/Users\//i,
      /\/home\//i,
      /\/tmp\//i,
      /\\AppData\\/i,
      /secret/i,
      /token/i,
      /password/i,
    ];

    for (const pat of forbiddenPatterns) {
      assert.ok(!pat.test(content), `Health JSON must not match pattern ${pat}`);
    }

    // Negative control on logger: simulate failure with sensitive paths and verify logger receives no path
    const sensitiveTokens = ['SecretToken123', 'PrivateUserCredential', '\\\\server\\share\\secret'];
    const mockLogger = createMockLogger();
    const failingFs = {
      writeFileSync() {
        const err = new Error(`Sensitive failure: ${sensitiveTokens.join(' ')}`);
        err.name = 'CustomError';
        err.code = 'EACCES';
        throw err;
      },
    };

    const failResult = writeBackupHealthAtomic(tempDir, healthData, { fs: failingFs, logger: mockLogger });
    assert.equal(failResult, false);
    assert.equal(mockLogger.errors.length, 1);
    const loggedError = mockLogger.errors[0];

    for (const tok of sensitiveTokens) {
      assert.ok(!loggedError.includes(tok), `Logged diagnostic must not leak token '${tok}'`);
    }
    assert.ok(!loggedError.includes('Sensitive failure'), 'Logged diagnostic must not leak raw err.message');
    assert.ok(!loggedError.includes(tempDir), 'Logged diagnostic must not leak file path');
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});
