'use strict';

/**
 * runtime/channel-gateway/tests/backup-scheduler.test.js
 *
 * Deterministic Unit Tests for BackupScheduler (TG-MVP-09 / T11-main).
 *
 * Invariants Verified:
 * 1. Fixed program constants: 86_400_000 ms freshness, 3_600_000 ms check interval.
 * 2. Fail-closed constructor validation (repository, absolute stateRoot, injected types).
 * 3. Freshness evaluation (no backup, <24h, ==24h, >24h, multiple backups max mtime).
 * 4. Filtering (unrelated files, malformed filenames, directories, symlinks, future/invalid mtime).
 * 5. Startup catch-up vs scheduled ticks with fake clock and fake timers.
 * 6. Overlap / re-entrancy prevention (F3: real re-entrant tick execution and skip).
 * 7. Non-fatal failure semantics and bounded non-secret logging (F2: no raw messages, paths, or secrets).
 * 8. Zero copy/move/retention/cleanup.
 * 9. F1: Verified backup return contract validation (success, backupPath, sourceSchemaVersion, integrity).
 * 10. F5: Strict crypto.randomUUID() RFC 4122 UUID-v4 naming contract.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const {
  BackupScheduler,
  BACKUP_FRESHNESS_THRESHOLD_MS,
  BACKUP_CHECK_INTERVAL_MS,
  CANONICAL_BACKUP_NAME_REGEX,
  validateBackupResult,
  formatBoundedDiagnostic,
} = require('../core/backup-scheduler');

// Synthetic absolute path for testing
const SYNTHETIC_STATE_ROOT =
  process.platform === 'win32'
    ? 'C:\\Synthetic\\Gateway\\StateRoot'
    : '/synthetic/gateway/state-root';

/**
 * Creates a deterministic fake clock and timer infrastructure.
 */
function createFakeEnv(initialTime = 1_700_000_000_000) {
  let currentTime = initialTime;
  let activeIntervals = [];
  let intervalIdCounter = 0;

  const now = () => currentTime;
  const advanceTime = (ms) => {
    currentTime += ms;
  };

  const setIntervalFn = (fn, delay) => {
    const id = ++intervalIdCounter;
    activeIntervals.push({ id, fn, delay });
    return id;
  };

  const clearIntervalFn = (id) => {
    activeIntervals = activeIntervals.filter((item) => item.id !== id);
  };

  const tickIntervals = () => {
    // Snapshot active intervals to avoid concurrent modification issues
    const current = [...activeIntervals];
    for (const item of current) {
      item.fn();
    }
  };

  return {
    now,
    advanceTime,
    setIntervalFn,
    clearIntervalFn,
    tickIntervals,
    get activeIntervals() {
      return activeIntervals;
    },
  };
}

/**
 * Creates a mock repository tracking calls to createVerifiedBackup().
 */
function createMockRepository(options = {}) {
  const calls = [];
  const {
    onBackup = null,
    throwError = null,
    returnValue = undefined,
    databasePath = path.join(SYNTHETIC_STATE_ROOT, 'channel-gateway-state.sqlite3'),
  } = options;

  return {
    databasePath,
    createVerifiedBackup(...args) {
      calls.push(args);
      if (typeof onBackup === 'function') {
        onBackup();
      }
      if (throwError) {
        throw throwError;
      }
      if ('returnValue' in options) {
        return options.returnValue;
      }
      return {
        success: true,
        backupPath: path.join(
          SYNTHETIC_STATE_ROOT,
          'backups',
          'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3'
        ),
        sourceSchemaVersion: 3,
        integrity: 'ok',
      };
    },
    get calls() {
      return calls;
    },
  };
}

/**
 * Creates an in-memory mock fs module.
 */
function createMockFs(initialFiles = {}) {
  // initialFiles: map of filename -> { mtimeMs, isFile: true, isSymlink: false, throwStat: null }
  const files = new Map(Object.entries(initialFiles));
  if (!files.has('backups')) {
    files.set('backups', { isFile: false, isDirectory: true, isSymlink: false });
  }
  if (!files.has('channel-gateway-state.sqlite3')) {
    files.set('channel-gateway-state.sqlite3', {
      isFile: true,
      isDirectory: false,
      isSymlink: false,
      size: 1000,
      mtimeMs: 1_700_000_000_000,
    });
  }
  const operations = [];

  return {
    readdirSync(dirPath) {
      operations.push({ op: 'readdirSync', path: dirPath });
      const isBackups =
        dirPath.endsWith('backups') || dirPath.endsWith('backups/') || dirPath.endsWith('backups\\');
      if (isBackups) {
        return Array.from(files.keys()).filter(
          (k) =>
            k !== 'backups' &&
            k !== 'channel-gateway-state.sqlite3' &&
            !k.endsWith('.tmp') &&
            k !== 'backup-health.json'
        );
      }
      return Array.from(files.keys()).filter((k) => !k.startsWith('channel-gateway-state.backup-'));
    },
    lstatSync(filePath) {
      operations.push({ op: 'lstatSync', path: filePath });
      const filename = path.basename(filePath);
      let fileData = files.get(filename);
      if (!fileData) {
        if (filename === 'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3') {
          fileData = {
            isFile: true,
            isDirectory: false,
            isSymlink: false,
            mtimeMs: 1_700_000_000_000,
            size: 1000,
          };
          files.set(filename, fileData);
        } else {
          const err = new Error('ENOENT: no such file or directory, stat ' + filePath);
          err.code = 'ENOENT';
          throw err;
        }
      }
      if (fileData.throwStat) {
        throw fileData.throwStat;
      }

      return {
        isFile: () => fileData.isFile !== false && fileData.isDirectory !== true,
        isDirectory: () => fileData.isDirectory === true,
        isSymbolicLink: () => fileData.isSymlink === true,
        mtimeMs: fileData.mtimeMs,
        mtime: fileData.mtime instanceof Date ? fileData.mtime : new Date(fileData.mtimeMs || 0),
        size: typeof fileData.size === 'number' ? fileData.size : 1000,
      };
    },
    statSync(filePath) {
      return this.lstatSync(filePath);
    },
    realpathSync(filePath) {
      operations.push({ op: 'realpathSync', path: filePath });
      return filePath;
    },
    statfsSync(targetPath) {
      operations.push({ op: 'statfsSync', path: targetPath });
      return {
        bavail: 1_000_000,
        bfree: 1_000_000,
        bsize: 4096,
      };
    },
    mkdirSync(dirPath, opts) {
      operations.push({ op: 'mkdirSync', path: dirPath, opts });
      files.set(path.basename(dirPath), { isFile: false, isDirectory: true, isSymlink: false });
    },
    writeFileSync(filePath, data) {
      operations.push({ op: 'writeFileSync', path: filePath });
      files.set(path.basename(filePath), {
        isFile: true,
        isDirectory: false,
        isSymlink: false,
        size: typeof data === 'string' ? Buffer.byteLength(data) : 100,
        mtimeMs: Date.now(),
        _rawContent: typeof data === 'string' ? data : JSON.stringify(data),
      });
    },
    unlinkSync(filePath) {
      operations.push({ op: 'unlinkSync', path: filePath });
      files.delete(path.basename(filePath));
    },
    rmSync(filePath) {
      operations.push({ op: 'rmSync', path: filePath });
      files.delete(path.basename(filePath));
    },
    renameSync(from, to) {
      operations.push({ op: 'renameSync', from, to });
      const fromName = path.basename(from);
      const toName = path.basename(to);
      const data = files.get(fromName);
      if (data) {
        files.delete(fromName);
        files.set(toName, data);
      }
    },
    copyFileSync(from, to) {
      operations.push({ op: 'copyFileSync', from, to });
    },
    get files() {
      return files;
    },
    get operations() {
      return operations;
    },
  };
}

/**
 * Creates a mock logger tracking errors and warnings.
 */
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

// ---------------------------------------------------------------------------
// Test Cases
// ---------------------------------------------------------------------------

test('1. constants exact: 86_400_000 ms freshness, 3_600_000 ms check interval', () => {
  assert.equal(BACKUP_FRESHNESS_THRESHOLD_MS, 86_400_000);
  assert.equal(BACKUP_CHECK_INTERVAL_MS, 3_600_000);
});

test('2. constructor invalid repository fail closed', () => {
  assert.throws(
    () => new BackupScheduler({ stateRoot: SYNTHETIC_STATE_ROOT }),
    /repository must be provided/
  );
  assert.throws(
    () => new BackupScheduler({ repository: {}, stateRoot: SYNTHETIC_STATE_ROOT }),
    /repository must implement createVerifiedBackup/
  );
  assert.throws(
    () =>
      new BackupScheduler({
        repository: { createVerifiedBackup: 'not-a-func' },
        stateRoot: SYNTHETIC_STATE_ROOT,
      }),
    /repository must implement createVerifiedBackup/
  );
});

test('3. relative stateRoot fail closed', () => {
  const repo = createMockRepository();
  assert.throws(
    () => new BackupScheduler({ repository: repo, stateRoot: 'relative/path' }),
    /stateRoot must be an absolute path/
  );
  assert.throws(
    () => new BackupScheduler({ repository: repo, stateRoot: '' }),
    /stateRoot must be a non-empty string/
  );
});

test('4. no existing backup: start immediate due check -> one backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const mockFs = createMockFs({}); // Empty directory

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('5. latest backup age < 24h: zero backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const recentMtime = 1_700_000_000_000 - 3_600_000; // 1 hour old (< 24h)

  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: recentMtime,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 0); // No backup triggered
  scheduler.stop();
});

test('6. age exactly 24h: one backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const exactMtime = 1_700_000_000_000 - 86_400_000; // exactly 24h old

  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: exactMtime,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('7. age > 24h: one backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const overdueMtime = 1_700_000_000_000 - 86_400_001; // > 24h old

  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: overdueMtime,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('8. multiple canonical backups: maximum valid mtime controls freshness', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  // Backup 1 is 30h old (overdue); Backup 2 is 2h old (fresh); both valid UUID v4
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v2-11111111-1111-4111-8111-111111111111.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 30 * 3_600_000,
    },
    'channel-gateway-state.backup-v3-22222222-2222-4222-9222-222222222222.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 2 * 3_600_000,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  // Max valid mtime is 2h old (<24h), so NO backup is created
  assert.equal(repo.calls.length, 0);
  scheduler.stop();
});

test('9. unrelated files ignored', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  // Unrelated files even with fresh mtime should be ignored
  const mockFs = createMockFs({
    'channel-gateway-state.sqlite3': { mtimeMs: 1_700_000_000_000 },
    'unrelated-notes.txt': { mtimeMs: 1_700_000_000_000 },
    'backup.sqlite3': { mtimeMs: 1_700_000_000_000 },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  // No canonical backup found => treated as overdue => backup created
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('10. wrong backup filename ignored', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v0-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: 1_700_000_000_000,
    }, // v0 invalid
    'channel-gateway-state.backup-v3.sqlite3': { mtimeMs: 1_700_000_000_000 }, // no uuid
    'channel-gateway-state.backup-v3-not-a-uuid.sqlite3': { mtimeMs: 1_700_000_000_000 },
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3.tmp': {
      mtimeMs: 1_700_000_000_000,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('11. matching directory ignored', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: 1_700_000_000_000,
      isFile: false, // It is a directory!
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('12. matching symlink ignored', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: 1_700_000_000_000,
      isFile: true,
      isSymlink: true, // It is a symlink!
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('13. future-dated matching file不得 suppress backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  // Future mtime (+1000ms ahead of now)
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: 1_700_000_000_000 + 1_000,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  // Future-dated file ignored => backup created
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('14. invalid mtime不得 suppress backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: NaN,
    },
    'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3': {
      mtimeMs: -100,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('15. start installs exactly one interval, exact delay = 3_600_000', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(env.activeIntervals.length, 1);
  assert.equal(env.activeIntervals[0].delay, 3_600_000);
  scheduler.stop();
});

test('16. double start rejected, 不建立第二 interval', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.throws(() => scheduler.start(), /already started/);
  assert.equal(env.activeIntervals.length, 1); // Exactly one interval
  scheduler.stop();
});

test('17. stop clears interval, idempotent', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(env.activeIntervals.length, 1);
  scheduler.stop();
  assert.equal(env.activeIntervals.length, 0);

  // Calling stop again is safe no-op
  assert.doesNotThrow(() => scheduler.stop());
  assert.equal(scheduler.isStarted, false);
});

test('18. stop does not create backup', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: 1_700_000_000_000,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  repo.calls.length = 0; // Clear startup calls

  scheduler.stop();
  assert.equal(repo.calls.length, 0); // No backup created on stop
});

test('19. F3: real re-entrant / overlap check skip, zero second backup', () => {
  const initialTime = 1_700_000_000_000;
  const env = createFakeEnv(initialTime);

  // 1. Initial stateRoot has a fresh canonical backup (<24h, valid v4 UUID)
  const canonicalFreshName =
    'channel-gateway-state.backup-v4-a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8d.sqlite3';
  const mockFs = createMockFs({
    [canonicalFreshName]: {
      mtimeMs: initialTime - 1_000, // 1 second old
    },
  });

  let reentrantTickInvoked = false;
  let reentrantAttemptExecuted = false;

  const repo = createMockRepository({
    onBackup: () => {
      // 5. In createVerifiedBackup() callback, trigger interval tick synchronously
      if (!reentrantAttemptExecuted) {
        reentrantAttemptExecuted = true;
        env.tickIntervals();
      }
    },
  });

  // Track interval tick invocations to prove nested callback was called
  let totalTickInvocations = 0;
  const originalSetInterval = env.setIntervalFn;
  const instrumentedSetInterval = (fn, delay) => {
    return originalSetInterval(() => {
      totalTickInvocations++;
      if (reentrantAttemptExecuted) {
        reentrantTickInvoked = true;
      }
      fn();
    }, delay);
  };

  const schedulerInstance = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: instrumentedSetInterval,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  // 2. Start scheduler: initial backup is fresh, so start() completes with 0 backups
  schedulerInstance.start();
  assert.equal(repo.calls.length, 0, 'No backup created during startup since fresh backup exists');
  assert.equal(env.activeIntervals.length, 1, 'Exactly one interval timer must be installed');

  // 3. Advance fake clock to >=24h overdue
  env.advanceTime(BACKUP_FRESHNESS_THRESHOLD_MS + 10_000);

  // 4. Trigger first interval tick (triggers backup because it is overdue)
  env.tickIntervals();

  // 6 & 7. Assertions per F3:
  assert.equal(env.activeIntervals.length, 1, 'Interval must exist');
  assert.equal(reentrantAttemptExecuted, true, 'Re-entrant tick must have been triggered');
  assert.equal(reentrantTickInvoked, true, 'Nested interval callback must have executed');
  assert.equal(
    totalTickInvocations,
    2,
    'Total interval tick invocations must be exactly 2 (outer + nested)'
  );
  assert.equal(
    repo.calls.length,
    1,
    'Second backup must not occur; call count remains exactly 1'
  );

  schedulerInstance.stop();
});

test('20. F2: createVerifiedBackup failure: captured/logged with bounded diagnostic, no throw from scheduled tick, scheduler remains active', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const diskError = new Error('Disk write error');
  diskError.code = 'ENOSPC';

  const repo = createMockRepository({
    throwError: diskError,
  });
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  // start() should not throw despite backup failure
  assert.doesNotThrow(() => scheduler.start());
  assert.equal(scheduler.isStarted, true);
  assert.equal(logger.errors.length, 1);
  assert.equal(
    logger.errors[0],
    '[BackupScheduler] PerformBackup: name=Error, code=ENOSPC'
  );
  scheduler.stop();
});

test('21. next normal tick after failure can retry due check; no immediate retry', () => {
  const env = createFakeEnv(1_700_000_000_000);
  let shouldFail = true;

  const repo = {
    calls: 0,
    createVerifiedBackup() {
      this.calls++;
      if (shouldFail) {
        const err = new Error('Temporary failure');
        err.code = 'ETEMP';
        throw err;
      }
      return {
        success: true,
        backupPath: path.join(
          SYNTHETIC_STATE_ROOT,
          'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3'
        ),
        sourceSchemaVersion: 3,
        integrity: 'ok',
      };
    },
  };

  const mockFs = createMockFs({});
  const logger = createMockLogger();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start();
  assert.equal(repo.calls, 1); // First call failed
  assert.equal(logger.errors.length, 1);

  // Time advances only 10 minutes (< 1h check interval)
  env.advanceTime(600_000);
  // No immediate retry happened
  assert.equal(repo.calls, 1);

  // Normal 1h tick arrives
  shouldFail = false;
  env.advanceTime(3_000_000); // Reaches 1h
  env.tickIntervals();

  // Retry occurred on normal tick and succeeded
  assert.equal(repo.calls, 2);
  scheduler.stop();
});

test('22. F2: directory scan failure: bounded error, no backup in that failed check, scheduler remains active', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const scanErr = new Error('Directory access failure');
  scanErr.code = 'EACCES';

  const mockFs = {
    readdirSync() {
      throw scanErr;
    },
    lstatSync() {},
  };
  const repo = createMockRepository();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  // start() should not throw
  assert.doesNotThrow(() => scheduler.start());
  assert.equal(repo.calls.length, 0); // No backup created because scan failed
  assert.equal(logger.errors.length, 1);
  assert.equal(
    logger.errors[0],
    '[BackupScheduler] ScanFreshness: name=Error, code=EACCES'
  );
  assert.equal(scheduler.isStarted, true);
  scheduler.stop();
});

test('23. F2: one unsafe/unreadable candidate entry不得 suppress other freshness evidence', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const logger = createMockLogger();
  const repo = createMockRepository();

  const corruptStatErr = new Error('I/O error during stat');
  corruptStatErr.code = 'EIO';

  // Entry 1 has corrupt stat; Entry 2 is a fresh backup (<24h)
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3': {
      throwStat: corruptStatErr,
    },
    'channel-gateway-state.backup-v3-22222222-2222-4222-9222-222222222222.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 1_000, // 1s old
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start();
  // Warning logged for entry 1 via bounded diagnostic
  assert.equal(logger.warns.length, 1);
  assert.equal(
    logger.warns[0],
    '[BackupScheduler] StatCandidate: name=Error, code=EIO'
  );
  // Entry 2 was still successfully processed and satisfied freshness => 0 backups created
  assert.equal(repo.calls.length, 0);
  scheduler.stop();
});

test('24. createVerifiedBackup invoked with zero arguments', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  assert.equal(repo.calls[0].length, 0); // Called with 0 arguments
  scheduler.stop();
});

test('25. TG-MVP-09A: success under cap does not delete backups or perform copy', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  const destructiveOps = mockFs.operations.filter((o) =>
    ['unlinkSync', 'rmSync', 'copyFileSync'].includes(o.op)
  );
  assert.equal(destructiveOps.length, 0);
  scheduler.stop();
});

test('26. canonical migration/T11A backup artifact mtime可算入 freshness; scheduler不區分 periodic vs pre-migration artifact', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  // A pre-migration backup artifact created with valid UUID-v4 name pattern
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v2-33333333-3333-4333-a333-333333333333.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 10 * 3_600_000, // 10h old (< 24h)
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  // Pre-migration backup is <24h old => satisfies freshness => no backup created
  assert.equal(repo.calls.length, 0);
  scheduler.stop();
});

test('27. F2: Windows path + token in backup error: raw values absent from bounded scheduler log', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const rawWindowsErr = new Error(
    'Backup failed at C:\\Users\\Administrator\\Desktop\\secrets\\db.sqlite3 with token=ghp_secret12345'
  );
  rawWindowsErr.code = 'EWIN_PATH_ERR';

  const repo = createMockRepository({
    throwError: rawWindowsErr,
  });
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start();
  assert.equal(logger.errors.length, 1);
  const logged = logger.errors[0];

  assert.equal(
    logged,
    '[BackupScheduler] PerformBackup: name=Error, code=EWIN_PATH_ERR'
  );
  assert.equal(logged.includes('C:\\Users\\Administrator'), false);
  assert.equal(logged.includes('ghp_secret12345'), false);
  assert.equal(logged.includes('Backup failed'), false);
  scheduler.stop();
});

test('28. F2: POSIX quoted path + secret in scan error: raw values absent from bounded scheduler log', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const rawPosixErr = new Error(
    "ENOENT: no such file or directory, scandir '/home/user/state/db' with secret=MyTopSecretValue"
  );
  rawPosixErr.code = 'ENOENT';

  const mockFs = {
    readdirSync() {
      throw rawPosixErr;
    },
    lstatSync() {},
  };
  const repo = createMockRepository();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start();
  assert.equal(logger.errors.length, 1);
  const logged = logger.errors[0];

  assert.equal(
    logged,
    '[BackupScheduler] ScanFreshness: name=Error, code=ENOENT'
  );
  assert.equal(logged.includes('/home/user/state/db'), false);
  assert.equal(logged.includes('MyTopSecretValue'), false);
  assert.equal(logged.includes('ENOENT: no such file'), false);
  scheduler.stop();
});

test('29. F2: UNC path + token in candidate lstat warning: raw values absent from bounded scheduler log', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository();

  const uncErr = new Error(
    'Failed to stat \\\\server\\share\\secret_store\\candidate.sqlite3 with token=SECRET_TOKEN'
  );
  uncErr.code = 'EUNC_NET_ERR';

  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      throwStat: uncErr,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start();
  assert.equal(logger.warns.length, 1);
  const logged = logger.warns[0];

  assert.equal(
    logged,
    '[BackupScheduler] StatCandidate: name=Error, code=EUNC_NET_ERR'
  );
  assert.equal(logged.includes('\\\\server\\share'), false);
  assert.equal(logged.includes('SECRET_TOKEN'), false);
  assert.equal(logged.includes('Failed to stat'), false);
  scheduler.stop();
});

test('30. F5: non-v4 version nibble lookalikes ignored, cannot suppress due backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();

  // Fresh mtime (1000ms old), but version nibbles are 1 and 5 (not 4)
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-11111111-1111-1111-8111-111111111111.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 1_000,
    },
    'channel-gateway-state.backup-v3-22222222-2222-5222-8222-222222222222.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 1_000,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  // Non-v4 UUID files ignored => treated as overdue => backup created
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('31. F5: invalid variant nibble lookalikes ignored, cannot suppress due backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();

  // Fresh mtime (1000ms old), version is 4, but variant nibbles are 0, c, f (not 8, 9, a, b)
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-11111111-1111-4111-0111-111111111111.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 1_000,
    },
    'channel-gateway-state.backup-v3-22222222-2222-4222-c222-222222222222.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 1_000,
    },
    'channel-gateway-state.backup-v3-33333333-3333-4333-f333-333333333333.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 1_000,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  // Invalid variant UUID files ignored => treated as overdue => backup created
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('32. F5: valid v4 canonical artifact suppresses backup when <24h', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();

  // Valid RFC 4122 UUID v4: 4xxx and [89ab]xxx
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v4-12345678-1234-4234-8234-123456789abc.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 10 * 3_600_000, // 10h old (<24h)
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  // Valid v4 backup satisfies freshness => zero backup created
  assert.equal(repo.calls.length, 0);
  scheduler.stop();
});

// ---------------------------------------------------------------------------
// F1 Tests: createVerifiedBackup Return Contract Negative Controls
// ---------------------------------------------------------------------------

test('33. F1: createVerifiedBackup return contract: undefined result rejected, not counted as success', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository({
    returnValue: undefined,
  });
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  assert.doesNotThrow(() => scheduler.start());
  assert.equal(repo.calls.length, 1);
  assert.equal(logger.errors.length, 1);
  assert.equal(
    logger.errors[0],
    '[BackupScheduler] PerformBackup: name=Error, code=INVALID_BACKUP_RESULT'
  );
  assert.equal(scheduler.isStarted, true);
  scheduler.stop();
});

test('34. F1: createVerifiedBackup return contract: null result rejected, not counted as success', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository({
    returnValue: null,
  });
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  assert.doesNotThrow(() => scheduler.start());
  assert.equal(repo.calls.length, 1);
  assert.equal(logger.errors.length, 1);
  assert.equal(
    logger.errors[0],
    '[BackupScheduler] PerformBackup: name=Error, code=INVALID_BACKUP_RESULT'
  );
  scheduler.stop();
});

test('35. F1: createVerifiedBackup return contract: { success: false } rejected, not counted as success', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository({
    returnValue: {
      success: false,
      backupPath: path.join(SYNTHETIC_STATE_ROOT, 'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3'),
      sourceSchemaVersion: 3,
      integrity: 'ok',
    },
  });
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  assert.doesNotThrow(() => scheduler.start());
  assert.equal(repo.calls.length, 1);
  assert.equal(logger.errors.length, 1);
  assert.equal(
    logger.errors[0],
    '[BackupScheduler] PerformBackup: name=Error, code=BACKUP_UNSUCCESSFUL'
  );
  scheduler.stop();
});

test('36. F1: createVerifiedBackup return contract: missing/empty backupPath rejected, not counted as success', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository({
    returnValue: {
      success: true,
      backupPath: '   ',
      sourceSchemaVersion: 3,
      integrity: 'ok',
    },
  });
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  assert.doesNotThrow(() => scheduler.start());
  assert.equal(repo.calls.length, 1);
  assert.equal(logger.errors.length, 1);
  assert.equal(
    logger.errors[0],
    '[BackupScheduler] PerformBackup: name=Error, code=INVALID_BACKUP_PATH'
  );
  scheduler.stop();
});

test('37. F1: createVerifiedBackup return contract: invalid sourceSchemaVersion rejected, not counted as success', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository({
    returnValue: {
      success: true,
      backupPath: path.join(SYNTHETIC_STATE_ROOT, 'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3'),
      sourceSchemaVersion: 0,
      integrity: 'ok',
    },
  });
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  assert.doesNotThrow(() => scheduler.start());
  assert.equal(repo.calls.length, 1);
  assert.equal(logger.errors.length, 1);
  assert.equal(
    logger.errors[0],
    '[BackupScheduler] PerformBackup: name=Error, code=INVALID_SOURCE_SCHEMA_VERSION'
  );
  scheduler.stop();
});

test('38. F1: createVerifiedBackup return contract: integrity != ok rejected, not counted as success', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository({
    returnValue: {
      success: true,
      backupPath: path.join(SYNTHETIC_STATE_ROOT, 'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3'),
      sourceSchemaVersion: 3,
      integrity: 'corrupt',
    },
  });
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  assert.doesNotThrow(() => scheduler.start());
  assert.equal(repo.calls.length, 1);
  assert.equal(logger.errors.length, 1);
  assert.equal(
    logger.errors[0],
    '[BackupScheduler] PerformBackup: name=Error, code=INVALID_BACKUP_INTEGRITY'
  );
  scheduler.stop();
});

test('39. F1: validateBackupResult direct matrix', () => {
  // Positive control
  assert.doesNotThrow(() =>
    validateBackupResult({
      success: true,
      backupPath: '/valid/backup.sqlite3',
      sourceSchemaVersion: 4,
      integrity: 'ok',
    })
  );

  // Negative controls
  assert.throws(() => validateBackupResult(undefined), (e) => e.code === 'INVALID_BACKUP_RESULT');
  assert.throws(() => validateBackupResult(null), (e) => e.code === 'INVALID_BACKUP_RESULT');
  assert.throws(() => validateBackupResult('string'), (e) => e.code === 'INVALID_BACKUP_RESULT');
  assert.throws(() => validateBackupResult({ success: false }), (e) => e.code === 'BACKUP_UNSUCCESSFUL');
  assert.throws(
    () => validateBackupResult({ success: true, backupPath: '' }),
    (e) => e.code === 'INVALID_BACKUP_PATH'
  );
  assert.throws(
    () => validateBackupResult({ success: true, backupPath: '/path', sourceSchemaVersion: -1 }),
    (e) => e.code === 'INVALID_SOURCE_SCHEMA_VERSION'
  );
  assert.throws(
    () => validateBackupResult({ success: true, backupPath: '/path', sourceSchemaVersion: 1.5 }),
    (e) => e.code === 'INVALID_SOURCE_SCHEMA_VERSION'
  );
  assert.throws(
    () => validateBackupResult({ success: true, backupPath: '/path', sourceSchemaVersion: 4, integrity: 'bad' }),
    (e) => e.code === 'INVALID_BACKUP_INTEGRITY'
  );
});
// ---------------------------------------------------------------------------
// TG-MVP-09A Comprehensive Negative & Positive Controls (Tests 40 - 68)
// ---------------------------------------------------------------------------

test('40. Free space: sufficient space permits backup', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});
  // statfs provides 10MB free space, db is 1000 bytes => >2x => backup runs
  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    statfsSync: () => ({ bavail: 2500, bsize: 4096 }), // 10,240,000 bytes
  });

  scheduler.start();
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('41. Free space: availableBytes < 2x dbSize skips backup and logs ALERT', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});
  const logger = createMockLogger();
  // Live db is 1000 bytes (requires 2000 bytes). Available is only 1500 bytes.
  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    statfsSync: () => ({ bavail: 15, bsize: 100 }), // 1500 bytes < 2000
    logger,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 0); // Backup skipped
  assert.equal(scheduler.consecutiveFailures, 1);
  scheduler.stop();

  // Health JSON must reflect INSUFFICIENT_FREE_SPACE and ALERT
  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.equal(healthData.state, 'ALERT');
  assert.ok(healthData.reasonCodes.includes('INSUFFICIENT_FREE_SPACE'));
});

test('42. Free space: statfs failure skips backup and logs ALERT', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});
  const logger = createMockLogger();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    statfsSync: () => {
      const err = new Error('Disk I/O error during statfs');
      err.code = 'EIO';
      throw err;
    },
    logger,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 0); // Backup skipped
  assert.equal(scheduler.consecutiveFailures, 1);
  scheduler.stop();

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.equal(healthData.state, 'ALERT');
  assert.ok(healthData.reasonCodes.includes('FREE_SPACE_CHECK_FAILED'));
});

test('43. Free space: DB stat failure skips backup and logs ALERT', () => {
  const env = createFakeEnv();
  const repo = createMockRepository({
    databasePath: path.join(SYNTHETIC_STATE_ROOT, 'missing-db.sqlite3'),
  });
  const mockFs = createMockFs({});
  const logger = createMockLogger();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start();
  assert.equal(repo.calls.length, 0);
  assert.equal(scheduler.consecutiveFailures, 1);
  scheduler.stop();

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.equal(healthData.state, 'ALERT');
  assert.ok(healthData.reasonCodes.includes('FREE_SPACE_CHECK_FAILED'));
});

test('44. Health state: OK state when fresh backup exists within 24h', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 5 * 3_600_000, // 5 hours old
      size: 50_000,
    },
  });

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.equal(healthData.state, 'OK');
  assert.deepEqual(healthData.reasonCodes, []);
  assert.equal(healthData.backupCount, 1);
  assert.equal(healthData.totalBytes, 50_000);
  assert.equal(healthData.lastSuccessAt, 1_700_000_000_000 - 5 * 3_600_000);
});

test('45. Health state: age >= 48h triggers ALERT NO_SUCCESSFUL_BACKUP_48H', () => {
  const env = createFakeEnv(1_700_000_000_000);
  // Backup fails on attempt, so 49h old backup remains the latest
  const repo = createMockRepository({ throwError: new Error('Backup failed') });
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 49 * 3_600_000, // 49 hours old
      size: 50_000,
    },
  });
  const logger = createMockLogger();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start();
  scheduler.stop();

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.equal(healthData.state, 'ALERT');
  assert.ok(healthData.reasonCodes.includes('NO_SUCCESSFUL_BACKUP_48H'));
});

test('46. Consecutive failures: 1 or 2 failures do NOT trigger CONSECUTIVE_BACKUP_FAILURES alert', () => {
  const env = createFakeEnv();
  const repo = createMockRepository({ throwError: new Error('Simulated failure') });
  const mockFs = createMockFs({});
  const logger = createMockLogger();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start(); // Cycle 1 failure
  assert.equal(scheduler.consecutiveFailures, 1);
  env.advanceTime(3_600_000);
  env.tickIntervals(); // Cycle 2 failure
  assert.equal(scheduler.consecutiveFailures, 2);
  scheduler.stop();

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.equal(healthData.reasonCodes.includes('CONSECUTIVE_BACKUP_FAILURES'), false);
});

test('47. Consecutive failures: 3 consecutive failures triggers ALERT CONSECUTIVE_BACKUP_FAILURES', () => {
  const env = createFakeEnv();
  const repo = createMockRepository({ throwError: new Error('Simulated failure') });
  const mockFs = createMockFs({});
  const logger = createMockLogger();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start(); // 1
  env.advanceTime(3_600_000);
  env.tickIntervals(); // 2
  env.advanceTime(3_600_000);
  env.tickIntervals(); // 3
  assert.equal(scheduler.consecutiveFailures, 3);
  scheduler.stop();

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.equal(healthData.state, 'ALERT');
  assert.ok(healthData.reasonCodes.includes('CONSECUTIVE_BACKUP_FAILURES'));
});

test('48. Consecutive failures: successful verified backup resets failure count to 0', () => {
  const env = createFakeEnv();
  let fail = true;
  const repo = {
    databasePath: path.join(SYNTHETIC_STATE_ROOT, 'channel-gateway-state.sqlite3'),
    createVerifiedBackup() {
      if (fail) throw new Error('Temporary failure');
      return {
        success: true,
        backupPath: path.join(
          SYNTHETIC_STATE_ROOT,
          'backups',
          'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3'
        ),
        sourceSchemaVersion: 3,
        integrity: 'ok',
      };
    },
  };
  const mockFs = createMockFs({});
  const logger = createMockLogger();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start(); // Cycle 1: fail
  assert.equal(scheduler.consecutiveFailures, 1);
  fail = false; // Next cycle will succeed
  env.advanceTime(3_600_000);
  env.tickIntervals(); // Cycle 2: succeed
  assert.equal(scheduler.consecutiveFailures, 0);
  scheduler.stop();
});

test('49. Privacy: health JSON exact fields contract and zero path or content leakage', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({});

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  const rawJson = mockFs.files.get('backup-health.json')._rawContent;
  const healthData = JSON.parse(rawJson);

  // Exact keys check
  const expectedKeys = [
    'state',
    'reasonCodes',
    'lastSuccessAt',
    'backupCount',
    'totalBytes',
    'maxTotalBytes',
    'minKeepCount',
    'updatedAt',
  ].sort();
  assert.deepEqual(Object.keys(healthData).sort(), expectedKeys);

  // Zero paths in json text
  assert.equal(rawJson.includes(SYNTHETIC_STATE_ROOT), false);
  assert.equal(rawJson.includes('channel-gateway-state'), false);
  assert.equal(rawJson.includes('sqlite3'), false);
  assert.equal(rawJson.includes('backups'), false);
});

test('50. Privacy: atomic health write bounded diagnostics do not leak sensitive paths or secrets', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const logger = createMockLogger();

  const sensitivePath = 'C:\\SecretUser\\Token_12345\\StateRoot';
  const customMockFs = createMockFs({});
  // Inject writeFileSync that fails with a sensitive error message
  customMockFs.writeFileSync = () => {
    const err = new Error('Disk full writing to ' + sensitivePath + ' with secret=SuperSecretToken');
    err.code = 'ENOSPC';
    throw err;
  };

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: sensitivePath,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: customMockFs,
    logger,
  });

  scheduler.start();
  scheduler.stop();

  for (const errMsg of logger.errors) {
    assert.equal(errMsg.includes('SecretUser'), false);
    assert.equal(errMsg.includes('Token_12345'), false);
    assert.equal(errMsg.includes('SuperSecretToken'), false);
  }
});

test('51. Retention: oldest-first cleanup executes only after verified backup success and preserves newest 3', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  // 4 existing backups, each 300MB. Total = 1.2GB (> 1GB cap)
  const initialFiles = {
    'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3': {
      mtimeMs: 1_000,
      size: 300_000_000,
    },
    'channel-gateway-state.backup-v3-22222222-2222-4222-8222-222222222222.sqlite3': {
      mtimeMs: 2_000,
      size: 300_000_000,
    },
    'channel-gateway-state.backup-v3-33333333-3333-4333-8333-333333333333.sqlite3': {
      mtimeMs: 3_000,
      size: 300_000_000,
    },
    'channel-gateway-state.backup-v3-44444444-4444-4444-8444-444444444444.sqlite3': {
      mtimeMs: 4_000,
      size: 300_000_000,
    },
  };
  const mockFs = createMockFs(initialFiles);

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  // The oldest backup (mtime 1000) was deleted to bring total under 1GB!
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3'),
    false
  );
  // Newer backups preserved
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-22222222-2222-4222-8222-222222222222.sqlite3'),
    true
  );
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-33333333-3333-4333-8333-333333333333.sqlite3'),
    true
  );
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-44444444-4444-4444-8444-444444444444.sqlite3'),
    true
  );
});

test('52. Retention: equal-mtime tie-break deletes lower lexical filename first', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  // 4 backups with identical mtimeMs = 1000, 300MB each
  const initialFiles = {
    'channel-gateway-state.backup-v3-bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb.sqlite3': {
      mtimeMs: 1_000,
      size: 300_000_000,
    },
    'channel-gateway-state.backup-v3-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa.sqlite3': {
      mtimeMs: 1_000,
      size: 300_000_000,
    },
    'channel-gateway-state.backup-v3-cccccccc-cccc-4ccc-8ccc-cccccccccccc.sqlite3': {
      mtimeMs: 1_000,
      size: 300_000_000,
    },
    'channel-gateway-state.backup-v3-dddddddd-dddd-4ddd-8ddd-dddddddddddd.sqlite3': {
      mtimeMs: 1_000,
      size: 300_000_000,
    },
  };
  const mockFs = createMockFs(initialFiles);

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  // 'aaaaaaaa...' is lowest lexical order so it is deleted first
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa.sqlite3'),
    false
  );
});

test('53. Retention: min-keep capacity conflict keeps all protected backups and records WARN', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  // 3 fresh backups (<24h) of 400MB each => 1.2GB total. Protected = 3. Protected > 1GB!
  const initialFiles = {
    'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 3_000,
      size: 400_000_000,
    },
    'channel-gateway-state.backup-v3-22222222-2222-4222-8222-222222222222.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 2_000,
      size: 400_000_000,
    },
    'channel-gateway-state.backup-v3-33333333-3333-4333-8333-333333333333.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 1_000,
      size: 400_000_000,
    },
  };
  const mockFs = createMockFs(initialFiles);

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  // None of the 3 protected backups were deleted!
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3'),
    true
  );
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-22222222-2222-4222-8222-222222222222.sqlite3'),
    true
  );
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-33333333-3333-4333-8333-333333333333.sqlite3'),
    true
  );

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.ok(healthData.reasonCodes.includes('MIN_KEEP_CAPACITY_CONFLICT'));
});

test('54. Retention: single backup exceeding capacity is preserved and records ALERT', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  // 1 backup of 1.5GB (> 1GB cap)
  const initialFiles = {
    'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3': {
      mtimeMs: 1_000,
      size: 1_500_000_000,
    },
  };
  const mockFs = createMockFs(initialFiles);

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  // Preserved
  assert.equal(
    mockFs.files.has('channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3'),
    true
  );

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.equal(healthData.state, 'ALERT');
  assert.ok(healthData.reasonCodes.includes('SINGLE_BACKUP_EXCEEDS_CAPACITY'));
});

test('55. Retention: unknown files and symlinks inside backups/ are never deleted and record WARN', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const initialFiles = {
    'unknown-file.txt': { mtimeMs: 1000, size: 50 },
    'malformed-backup.sqlite3': { mtimeMs: 1000, size: 50 },
    'symlink-backup.sqlite3': { mtimeMs: 1000, size: 50, isSymlink: true },
  };
  const mockFs = createMockFs(initialFiles);

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  // None deleted
  assert.equal(mockFs.files.has('unknown-file.txt'), true);
  assert.equal(mockFs.files.has('malformed-backup.sqlite3'), true);
  assert.equal(mockFs.files.has('symlink-backup.sqlite3'), true);

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.ok(healthData.reasonCodes.includes('UNKNOWN_BACKUP_DIRECTORY_ENTRY'));
});

test('56. Retention: live DB, WAL, and SHM are never deleted', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const initialFiles = {
    'channel-gateway-state.sqlite3-wal': { mtimeMs: 1000, size: 1000 },
    'channel-gateway-state.sqlite3-shm': { mtimeMs: 1000, size: 1000 },
  };
  const mockFs = createMockFs(initialFiles);

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  assert.equal(mockFs.files.has('channel-gateway-state.sqlite3'), true);
  assert.equal(mockFs.files.has('channel-gateway-state.sqlite3-wal'), true);
  assert.equal(mockFs.files.has('channel-gateway-state.sqlite3-shm'), true);
});

test('57. Retention: delete failure logs WARN BACKUP_DELETE_FAILED and Gateway continues', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const initialFiles = {
    'channel-gateway-state.backup-v3-11111111-1111-4111-8111-111111111111.sqlite3': {
      mtimeMs: 1_000,
      size: 500_000_000,
    },
    'channel-gateway-state.backup-v3-22222222-2222-4222-8222-222222222222.sqlite3': {
      mtimeMs: 2_000,
      size: 500_000_000,
    },
    'channel-gateway-state.backup-v3-33333333-3333-4333-8333-333333333333.sqlite3': {
      mtimeMs: 3_000,
      size: 500_000_000,
    },
    'channel-gateway-state.backup-v3-44444444-4444-4444-8444-444444444444.sqlite3': {
      mtimeMs: 4_000,
      size: 500_000_000,
    },
  };
  const mockFs = createMockFs(initialFiles);
  // Inject unlinkSync failure
  mockFs.unlinkSync = () => {
    const err = new Error('Permission denied deleting file');
    err.code = 'EACCES';
    throw err;
  };
  const logger = createMockLogger();

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
    logger,
  });

  scheduler.start();
  scheduler.stop();

  const healthData = JSON.parse(mockFs.files.get('backup-health.json')._rawContent || '{}');
  assert.ok(healthData.reasonCodes.includes('BACKUP_DELETE_FAILED'));
});

test('58. Legacy migration: canonical root backup is renamed to backups/ child', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const legacyFilename = 'channel-gateway-state.backup-v2-77777777-7777-4777-a777-777777777777.sqlite3';
  const renames = [];

  const mockFs = createMockFs({});
  // Readdir on stateRoot returns the legacy backup
  const origReaddir = mockFs.readdirSync.bind(mockFs);
  mockFs.readdirSync = (dir) => {
    if (dir === SYNTHETIC_STATE_ROOT) {
      return [legacyFilename, 'channel-gateway-state.sqlite3', 'backups'];
    }
    return origReaddir(dir);
  };
  // lstatSync can resolve legacy backup in stateRoot
  const origLstat = mockFs.lstatSync.bind(mockFs);
  mockFs.lstatSync = (p) => {
    if (p.includes(legacyFilename) && !p.includes('backups')) {
      return {
        isFile: () => true,
        isDirectory: () => false,
        isSymbolicLink: () => false,
        mtimeMs: 1_700_000_000_000 - 1000,
        size: 5000,
      };
    }
    return origLstat(p);
  };
  mockFs.renameSync = (from, to) => {
    renames.push({ from, to });
  };

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  const backupRenames = renames.filter((r) => r.from.includes('channel-gateway-state.backup-'));
  assert.equal(backupRenames.length, 1);
  assert.equal(backupRenames[0].from, path.join(SYNTHETIC_STATE_ROOT, legacyFilename));
  assert.equal(backupRenames[0].to, path.join(SYNTHETIC_STATE_ROOT, 'backups', legacyFilename));
});

test('59. Legacy migration: non-canonical files in root are untouched', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const renames = [];

  const mockFs = createMockFs({});
  mockFs.readdirSync = (dir) => {
    if (dir === SYNTHETIC_STATE_ROOT) {
      return ['random-file.txt', 'notes.md', 'channel-gateway-state.sqlite3', 'backups'];
    }
    return [];
  };
  mockFs.renameSync = (from, to) => {
    renames.push({ from, to });
  };

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  scheduler.start();
  scheduler.stop();

  const backupRenames = renames.filter((r) => r.from.includes('channel-gateway-state.backup-'));
  assert.equal(backupRenames.length, 0); // No non-canonical files renamed
});
