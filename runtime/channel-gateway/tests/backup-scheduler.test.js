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
  const { onBackup = null, throwError = null, returnValue = undefined } = options;

  return {
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
  const operations = [];

  return {
    readdirSync(dirPath) {
      operations.push({ op: 'readdirSync', path: dirPath });
      return Array.from(files.keys());
    },
    lstatSync(filePath) {
      operations.push({ op: 'lstatSync', path: filePath });
      const filename = path.basename(filePath);
      const fileData = files.get(filename);
      if (!fileData) {
        const err = new Error(`ENOENT: no such file or directory, stat '${filePath}'`);
        err.code = 'ENOENT';
        throw err;
      }
      if (fileData.throwStat) {
        throw fileData.throwStat;
      }

      return {
        isFile: () => fileData.isFile !== false,
        isSymbolicLink: () => fileData.isSymlink === true,
        mtimeMs: fileData.mtimeMs,
        mtime: fileData.mtime instanceof Date ? fileData.mtime : new Date(fileData.mtimeMs || 0),
      };
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

test('25. success result不觸發 copy/move/delete/cleanup', () => {
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
    ['unlinkSync', 'rmSync', 'renameSync', 'copyFileSync'].includes(o.op)
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
