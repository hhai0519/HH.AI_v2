'use strict';

/**
 * runtime/channel-gateway/tests/backup-runtime-owner.test.js
 *
 * Deterministic Unit & Integration Tests for BackupRuntimeOwner (TG-MVP-09 / T11-main).
 *
 * Invariants Verified:
 * 1. Default lifecycle contract: repository open -> scheduler start.
 * 2. Strict stop ordering: scheduler stop -> repository close.
 * 3. Consistent stateRoot propagation to repository & scheduler.
 * 4. Duplicate start fail closed.
 * 5. Safe idempotent stop (pre-start and repeated).
 * 6. Error handling: repository open failure leaves scheduler uninstantiated.
 * 7. Error handling: scheduler factory / start failure closes opened repository.
 * 8. Stop does not trigger backups.
 * 9. Structural source assertions: zero signal handlers, zero env/argv/config, zero child processes.
 * 10. Real integration with real SqliteStateRepository and temp directory.
 * 11. Real integration avoids duplicate backup when fresh canonical backup exists.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const { BackupRuntimeOwner } = require('../core/backup-runtime-owner');
const { SqliteStateRepository } = require('../core/sqlite-state-repository');

const SYNTHETIC_STATE_ROOT =
  process.platform === 'win32'
    ? 'C:\\Synthetic\\Gateway\\RuntimeOwnerStateRoot'
    : '/synthetic/gateway/runtime-owner-state-root';

function createMockLifecycleTracker() {
  const events = [];

  const mockRepo = {
    isClosed: false,
    close() {
      this.isClosed = true;
      events.push('repository.close');
    },
    createVerifiedBackup() {
      events.push('repository.createVerifiedBackup');
      return { success: true };
    },
  };

  const mockScheduler = {
    isStarted: false,
    start() {
      this.isStarted = true;
      events.push('scheduler.start');
    },
    stop() {
      this.isStarted = false;
      events.push('scheduler.stop');
    },
  };

  return {
    events,
    mockRepo,
    mockScheduler,
  };
}

// ---------------------------------------------------------------------------
// Unit Tests
// ---------------------------------------------------------------------------

test('1. default responsibility contract: repository open -> scheduler start', () => {
  const tracker = createMockLifecycleTracker();
  let repoFactoryRoot = null;
  let schedulerFactoryRoot = null;

  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: (root) => {
      repoFactoryRoot = root;
      tracker.events.push('repository.open');
      return tracker.mockRepo;
    },
    schedulerFactory: (repo, root) => {
      schedulerFactoryRoot = root;
      tracker.events.push('scheduler.create');
      return tracker.mockScheduler;
    },
  });

  owner.start();
  assert.equal(owner.isStarted, true);
  assert.deepEqual(tracker.events, [
    'repository.open',
    'scheduler.create',
    'scheduler.start',
  ]);
  assert.equal(repoFactoryRoot, SYNTHETIC_STATE_ROOT);
  assert.equal(schedulerFactoryRoot, SYNTHETIC_STATE_ROOT);
  owner.stop();
});

test('2. stop order: scheduler stop -> repository close', () => {
  const tracker = createMockLifecycleTracker();

  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: () => tracker.mockRepo,
    schedulerFactory: () => tracker.mockScheduler,
  });

  owner.start();
  tracker.events.length = 0; // Clear start events

  owner.stop();
  assert.equal(owner.isStarted, false);
  assert.deepEqual(tracker.events, ['scheduler.stop', 'repository.close']);
  assert.equal(tracker.mockRepo.isClosed, true);
});

test('3. same stateRoot passed to repository and scheduler', () => {
  let passedToRepo = null;
  let passedToScheduler = null;

  const tracker = createMockLifecycleTracker();
  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: (root) => {
      passedToRepo = root;
      return tracker.mockRepo;
    },
    schedulerFactory: (repo, root) => {
      passedToScheduler = root;
      return tracker.mockScheduler;
    },
  });

  owner.start();
  assert.equal(passedToRepo, SYNTHETIC_STATE_ROOT);
  assert.equal(passedToScheduler, SYNTHETIC_STATE_ROOT);
  owner.stop();
});

test('4. duplicate start fail closed', () => {
  const tracker = createMockLifecycleTracker();
  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: () => tracker.mockRepo,
    schedulerFactory: () => tracker.mockScheduler,
  });

  owner.start();
  assert.throws(() => owner.start(), /already started/);
  owner.stop();
});

test('5. stop before start idempotent', () => {
  const tracker = createMockLifecycleTracker();
  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: () => tracker.mockRepo,
    schedulerFactory: () => tracker.mockScheduler,
  });

  // Calling stop before start is a safe no-op
  assert.doesNotThrow(() => owner.stop());
  assert.equal(tracker.events.length, 0);
  assert.equal(owner.isStarted, false);
});

test('6. stop repeated idempotent', () => {
  const tracker = createMockLifecycleTracker();
  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: () => tracker.mockRepo,
    schedulerFactory: () => tracker.mockScheduler,
  });

  owner.start();
  owner.stop();
  const stopEventCount = tracker.events.length;

  // Second stop should do nothing
  owner.stop();
  assert.equal(tracker.events.length, stopEventCount);
});

test('7. repository open failure: scheduler not created', () => {
  let schedulerFactoryCalled = false;

  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: () => {
      throw new Error('Database locked / open failure');
    },
    schedulerFactory: () => {
      schedulerFactoryCalled = true;
      return {};
    },
  });

  assert.throws(() => owner.start(), /Database locked \/ open failure/);
  assert.equal(schedulerFactoryCalled, false);
  assert.equal(owner.isStarted, false);
});

test('8. scheduler factory failure: opened repository is closed', () => {
  const tracker = createMockLifecycleTracker();

  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: () => tracker.mockRepo,
    schedulerFactory: () => {
      throw new Error('Scheduler instantiation error');
    },
  });

  assert.throws(() => owner.start(), /Scheduler instantiation error/);
  assert.equal(tracker.mockRepo.isClosed, true);
  assert.equal(owner.isStarted, false);
});

test('9. scheduler.start structural throw: repository is closed', () => {
  const tracker = createMockLifecycleTracker();
  tracker.mockScheduler.start = () => {
    throw new Error('Scheduler start crashed');
  };

  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: () => tracker.mockRepo,
    schedulerFactory: () => tracker.mockScheduler,
  });

  assert.throws(() => owner.start(), /Scheduler start crashed/);
  assert.equal(tracker.mockRepo.isClosed, true);
  assert.equal(owner.isStarted, false);
});

test('10. owner stop does not trigger backup', () => {
  const tracker = createMockLifecycleTracker();
  const owner = new BackupRuntimeOwner({
    stateRoot: SYNTHETIC_STATE_ROOT,
    repositoryFactory: () => tracker.mockRepo,
    schedulerFactory: () => tracker.mockScheduler,
  });

  owner.start();
  owner.stop();

  const backupCalls = tracker.events.filter((e) => e === 'repository.createVerifiedBackup');
  assert.equal(backupCalls.length, 0);
});

test('11. owner source does not install process.on / SIGINT / SIGTERM', () => {
  const sourcePath = path.join(__dirname, '../core/backup-runtime-owner.js');
  const source = fs.readFileSync(sourcePath, 'utf8');

  // Strip comments before checking for runtime invocations
  const stripped = source.replace(/\/\*[\s\S]*?\*\/|\/\/.*/g, '');
  assert.equal(stripped.includes('process.on'), false);
  assert.equal(stripped.includes('SIGINT'), false);
  assert.equal(stripped.includes('SIGTERM'), false);
});

test('12. owner does not read env / argv / Local Config', () => {
  const sourcePath = path.join(__dirname, '../core/backup-runtime-owner.js');
  const source = fs.readFileSync(sourcePath, 'utf8');
  const stripped = source.replace(/\/\*[\s\S]*?\*\/|\/\/.*/g, '');

  assert.equal(stripped.includes('process.env'), false);
  assert.equal(stripped.includes('process.argv'), false);
  assert.equal(stripped.includes('local-config-loader'), false);
  assert.equal(stripped.includes('loadDataLocationConfigFromFile'), false);
});

test('13. owner does not create child process / daemon', () => {
  const sourcePath = path.join(__dirname, '../core/backup-runtime-owner.js');
  const source = fs.readFileSync(sourcePath, 'utf8');
  const stripped = source.replace(/\/\*[\s\S]*?\*\/|\/\/.*/g, '');

  assert.equal(stripped.includes('child_process'), false);
  assert.equal(stripped.includes('fork'), false);
  assert.equal(stripped.includes('spawn'), false);
  assert.equal(stripped.includes('daemon'), false);
});

// ---------------------------------------------------------------------------
// Real Integration Tests with Real SqliteStateRepository in Repo Temp Dir
// ---------------------------------------------------------------------------

test('14. real integration test: no prior backup -> exactly one verified backup artifact created on startup; repo closed on stop', () => {
  const tempDir = path.join(
    __dirname,
    'temp-integration-owner-' + Date.now() + '-' + Math.floor(Math.random() * 10000)
  );
  fs.mkdirSync(tempDir, { recursive: true });

  try {
    const owner = new BackupRuntimeOwner({
      stateRoot: tempDir,
    });

    owner.start();
    assert.equal(owner.isStarted, true);
    assert.ok(owner.repository instanceof SqliteStateRepository);

    // Check directory contents
    const files = fs.readdirSync(tempDir);
    const backupFiles = files.filter(
      (f) => f.startsWith('channel-gateway-state.backup-') && f.endsWith('.sqlite3')
    );

    // Exactly one verified backup artifact created
    assert.equal(backupFiles.length, 1);

    const backupPath = path.join(tempDir, backupFiles[0]);
    const stat = fs.lstatSync(backupPath);
    assert.equal(stat.isFile(), true);
    assert.equal(stat.isSymbolicLink(), false);

    const repoRef = owner.repository;
    owner.stop();
    assert.equal(owner.isStarted, false);
    assert.equal(owner.repository, null);

    // Verify repository was closed
    assert.throws(
      () => repoRef.createVerifiedBackup(),
      /Repository is closed/
    );
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test('15. real integration test: with existing fresh backup (<24h), owner startup does not create a second backup', () => {
  const tempDir = path.join(
    __dirname,
    'temp-integration-fresh-' + Date.now() + '-' + Math.floor(Math.random() * 10000)
  );
  fs.mkdirSync(tempDir, { recursive: true });

  try {
    // 1. First owner run creates the initial backup
    const owner1 = new BackupRuntimeOwner({ stateRoot: tempDir });
    owner1.start();
    owner1.stop();

    const filesAfterFirst = fs.readdirSync(tempDir);
    const backupFilesFirst = filesAfterFirst.filter(
      (f) => f.startsWith('channel-gateway-state.backup-') && f.endsWith('.sqlite3')
    );
    assert.equal(backupFilesFirst.length, 1);

    // 2. Second owner run on the same stateRoot immediately after (< 24h)
    const owner2 = new BackupRuntimeOwner({ stateRoot: tempDir });
    owner2.start();
    owner2.stop();

    const filesAfterSecond = fs.readdirSync(tempDir);
    const backupFilesSecond = filesAfterSecond.filter(
      (f) => f.startsWith('channel-gateway-state.backup-') && f.endsWith('.sqlite3')
    );

    // Still exactly one backup artifact! No second backup created.
    assert.equal(backupFilesSecond.length, 1);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});
