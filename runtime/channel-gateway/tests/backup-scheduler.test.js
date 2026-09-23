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
 * 6. Overlap / re-entrancy prevention.
 * 7. Non-fatal failure semantics and bounded non-secret logging.
 * 8. Zero copy/move/retention/cleanup.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const {
  BackupScheduler,
  BACKUP_FRESHNESS_THRESHOLD_MS,
  BACKUP_CHECK_INTERVAL_MS,
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
  const { onBackup = null, throwError = null } = options;

  return {
    createVerifiedBackup(...args) {
      calls.push(args);
      if (typeof onBackup === 'function') {
        onBackup();
      }
      if (throwError) {
        throw throwError;
      }
      return {
        success: true,
        backupPath: path.join(
          SYNTHETIC_STATE_ROOT,
          'channel-gateway-state.backup-v3-00000000-0000-0000-0000-000000000000.sqlite3'
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
    /must implement createVerifiedBackup/
  );
  assert.throws(
    () =>
      new BackupScheduler({
        repository: { createVerifiedBackup: 'not-a-func' },
        stateRoot: SYNTHETIC_STATE_ROOT,
      }),
    /must implement createVerifiedBackup/
  );
});

test('3. relative stateRoot fail closed', () => {
  const repo = createMockRepository();
  assert.throws(
    () => new BackupScheduler({ repository: repo, stateRoot: './relative/path' }),
    /must be an absolute path/
  );
  assert.throws(
    () => new BackupScheduler({ repository: repo, stateRoot: '' }),
    /must be a non-empty string/
  );
});

test('4. no existing backup: start immediate due check -> one backup', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  const mockFs = createMockFs({}); // empty stateRoot

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
  // Backup 1 is 30h old (overdue); Backup 2 is 2h old (fresh)
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v2-11111111-1111-1111-1111-111111111111.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 30 * 3_600_000,
    },
    'channel-gateway-state.backup-v3-22222222-2222-2222-2222-222222222222.sqlite3': {
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
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: 1_700_000_000_000 + 100_000, // Future-dated!
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
  // Future-dated file ignored -> due check triggers backup
  assert.equal(repo.calls.length, 1);
  scheduler.stop();
});

test('14. invalid mtime不得 suppress backup', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-11111111-1111-1111-1111-111111111111.sqlite3': {
      mtimeMs: 0, // non-positive
    },
    'channel-gateway-state.backup-v3-22222222-2222-2222-2222-222222222222.sqlite3': {
      mtimeMs: NaN, // invalid NaN
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
  assert.equal(env.activeIntervals.length, 1);
  assert.throws(() => scheduler.start(), /already started/);
  assert.equal(env.activeIntervals.length, 1); // No second interval
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

  // Idempotent: repeated stop is safe no-op
  scheduler.stop();
  assert.equal(env.activeIntervals.length, 0);
});

test('18. stop does not create backup', () => {
  const env = createFakeEnv();
  const repo = createMockRepository();
  // Existing recent backup so startup doesn't trigger backup
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-e0186178-5e76-47b2-bdcf-884814e5bb0c.sqlite3': {
      mtimeMs: env.now(),
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
  assert.equal(repo.calls.length, 0);
  scheduler.stop();
  assert.equal(repo.calls.length, 0); // No backup created on stop
});

test('19. re-entrant / overlap check skip, zero second backup', () => {
  const env = createFakeEnv();
  let schedulerInstance = null;
  let reentrantAttemptExecuted = false;

  const repo = createMockRepository({
    onBackup: () => {
      // While backup is in-flight, simulate an overlapping interval tick
      if (schedulerInstance && !reentrantAttemptExecuted) {
        reentrantAttemptExecuted = true;
        // Trigger interval while in-flight
        env.tickIntervals();
      }
    },
  });

  const mockFs = createMockFs({});

  schedulerInstance = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: mockFs,
  });

  schedulerInstance.start();
  assert.equal(reentrantAttemptExecuted, true);
  // Only the original backup executed; overlapping tick skipped
  assert.equal(repo.calls.length, 1);
  schedulerInstance.stop();
});

test('20. createVerifiedBackup failure: captured/logged, no throw from scheduled tick, scheduler remains active', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository({
    throwError: new Error('VACUUM INTO synthetic disk full failure'),
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
  assert.match(logger.errors[0], /Failed to create verified backup/);
  scheduler.stop();
});

test('21. next normal tick after failure can retry due check; no immediate retry', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const logger = createMockLogger();
  let failFirst = true;

  const repo = {
    calls: [],
    createVerifiedBackup(...args) {
      this.calls.push(args);
      if (failFirst) {
        failFirst = false;
        throw new Error('Transient backup failure');
      }
      return { success: true };
    },
  };

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
  assert.equal(repo.calls.length, 1); // First attempt failed
  assert.equal(scheduler.isStarted, true);

  // Advance clock by 1h and trigger next normal tick
  env.advanceTime(3_600_000);
  env.tickIntervals();

  // Second tick retried overdue check and succeeded
  assert.equal(repo.calls.length, 2);
  scheduler.stop();
});

test('22. directory scan failure: bounded error, no backup in that failed check, scheduler remains active', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository();

  const brokenFs = {
    readdirSync() {
      throw new Error('EACCES: permission denied, scandir');
    },
    lstatSync() {
      throw new Error('Not reached');
    },
  };

  const scheduler = new BackupScheduler({
    repository: repo,
    stateRoot: SYNTHETIC_STATE_ROOT,
    now: env.now,
    setIntervalFn: env.setIntervalFn,
    clearIntervalFn: env.clearIntervalFn,
    fs: brokenFs,
    logger,
  });

  assert.doesNotThrow(() => scheduler.start());
  assert.equal(scheduler.isStarted, true);
  assert.equal(repo.calls.length, 0); // No backup executed due to scan failure
  assert.equal(logger.errors.length, 1);
  assert.match(logger.errors[0], /Failed to read stateRoot directory/);
  scheduler.stop();
});

test('23. one unsafe/unreadable candidate entry不得 suppress other freshness evidence', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const logger = createMockLogger();
  const repo = createMockRepository();

  // Entry 1 throws on lstat; Entry 2 is valid and recent (<24h)
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v3-11111111-1111-1111-1111-111111111111.sqlite3': {
      throwStat: new Error('EPERM: operation not permitted'),
    },
    'channel-gateway-state.backup-v3-22222222-2222-2222-2222-222222222222.sqlite3': {
      mtimeMs: 1_700_000_000_000 - 3_600_000, // 1h old
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
  // Entry 1 threw, logged as warning, Entry 2 was fresh (<24h) -> no backup triggered
  assert.equal(repo.calls.length, 0);
  assert.equal(logger.warns.length, 1);
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
  assert.equal(repo.calls[0].length, 0); // Exactly 0 arguments
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
  assert.equal(repo.calls.length, 1);

  // Check mockFs operations: only readdirSync, zero unlink / rm / rename / copy
  const destructiveOps = mockFs.operations.filter((o) =>
    ['unlinkSync', 'rmSync', 'renameSync', 'copyFileSync'].includes(o.op)
  );
  assert.equal(destructiveOps.length, 0);
  scheduler.stop();
});

test('26. canonical migration/T11A backup artifact mtime可算入 freshness; scheduler不區分 periodic vs pre-migration artifact', () => {
  const env = createFakeEnv(1_700_000_000_000);
  const repo = createMockRepository();
  // A pre-migration backup artifact created with schema v2 name pattern
  const mockFs = createMockFs({
    'channel-gateway-state.backup-v2-33333333-3333-3333-3333-333333333333.sqlite3': {
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

test('27. logger output不得包含 DB rows / credentials; errors with absolute-path message不得機械原樣反射至 bounded scheduler log', () => {
  const env = createFakeEnv();
  const logger = createMockLogger();
  const repo = createMockRepository({
    throwError: new Error(
      'Backup failed at C:\\Users\\Administrator\\Desktop\\secrets\\db.sqlite3 with token=ghp_secret12345'
    ),
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

  // Absolute path must be redacted
  assert.equal(logged.includes('C:\\Users\\Administrator\\Desktop\\secrets\\db.sqlite3'), false);
  assert.equal(logged.includes('ghp_secret12345'), false);
  assert.match(logged, /\[REDACTED_PATH\]/);
  scheduler.stop();
});
