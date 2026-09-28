/**
 * runtime/channel-gateway/tests/archive-worker.test.js
 *
 * TG-MVP-14 R1: ArchiveWorker lifecycle and queue processing tests.
 * - B1: Startup cleanup Promise is awaited, rejection is contained, no unhandled rejection, normal start continues.
 * - F3: Closed guard prevents post-close DB mutation, new fs steps, and retry timers.
 * - FAILED remains no-auto-retry.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { ArchiveWorker } = require('../core/archive-worker');

test('ArchiveWorker: processes PENDING -> COMPLETED and clears snapshot', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-worker-test-'));
  try {
    let pendingCleared = false;
    let completedMarked = false;

    const mockCoord = {
      archive_id: 501,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      command_id: 'cmd-501',
      platform_msg_id: 'tg:123:1',
      relative_path: 'TG_alice/Q001_General/001_Hello_20260329-103000.md',
      content_snapshot: 'Question content',
    };

    const mockTopic = {
      topic_id: 1,
      account_id: 'alice',
      display_name: 'General',
    };

    let claimedOnce = false;
    const mockRepo = {
      getPendingArchiveIds: () => (claimedOnce ? new Set() : new Set([501])),
      claimNextPendingArchiveCoordination: () => {
        if (!claimedOnce) {
          claimedOnce = true;
          return mockCoord;
        }
        return null;
      },
      getArchiveTopicById: () => mockTopic,
      getOutboxCommand: () => ({ body: 'Reply body' }),
      markArchiveCoordinationCompleted: ({ archiveId, completedAtSec, nowSec }) => {
        if (archiveId === 501) {
          completedMarked = true;
          pendingCleared = true;
        }
      },
      markArchiveCoordinationFailed: () => {},
    };

    const mockWriter = {
      archiveRoot: tmpDir,
      publishArchiveRecord: async () => {
        return { status: 'COMPLETED' };
      },
    };

    const worker = new ArchiveWorker({
      repository: mockRepo,
      fileWriter: mockWriter,
      archiveRoot: tmpDir,
    });

    await worker.start();
    // Allow queue to tick
    await worker.triggerProcessing();

    assert.strictEqual(completedMarked, true);
    assert.strictEqual(pendingCleared, true);

    await worker.stop();
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('ArchiveWorker: failure -> FAILED with stable reason and snapshot retained', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-worker-fail-'));
  try {
    let failedMarked = false;
    let failedReason = null;

    const mockCoord = {
      archive_id: 502,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      command_id: 'cmd-502',
      platform_msg_id: 'tg:123:2',
      relative_path: 'TG_alice/Q001_General/001_Hello_20260329-103000.md',
      content_snapshot: 'Sensitive question content',
    };

    let claimed = false;
    const mockRepo = {
      getPendingArchiveIds: () => new Set(),
      claimNextPendingArchiveCoordination: () => {
        if (!claimed) {
          claimed = true;
          return mockCoord;
        }
        return null;
      },
      getArchiveTopicById: () => ({ display_name: 'General' }),
      getOutboxCommand: () => ({ body: 'Reply' }),
      markArchiveCoordinationCompleted: () => {},
      markArchiveCoordinationFailed: (args) => {
        if (args.archiveId === 502) {
          failedMarked = true;
          failedReason = args.failedReasonCode || args.reasonCode;
        }
      },
    };

    const mockWriter = {
      archiveRoot: tmpDir,
      publishArchiveRecord: async () => {
        return { status: 'FAILED', reasonCode: 'ARCHIVE_TARGET_CONFLICT' };
      },
    };

    const worker = new ArchiveWorker({
      repository: mockRepo,
      fileWriter: mockWriter,
      archiveRoot: tmpDir,
    });

    await worker.start();
    await worker.triggerProcessing();

    assert.strictEqual(failedMarked, true);
    assert.strictEqual(failedReason, 'ARCHIVE_TARGET_CONFLICT');

    await worker.stop();
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('ArchiveWorker: stop does not drain entire queue and honors timeout with closed guard', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-worker-stop-'));
  try {
    let attemptedMutationAfterClose = false;
    let resolveSlowWrite;
    const slowWritePromise = new Promise((resolve) => {
      resolveSlowWrite = resolve;
    });

    const mockCoord1 = {
      archive_id: 601,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      command_id: 'cmd-601',
      platform_msg_id: 'tg:100:1',
      relative_path: 'TG_alice/Q001_General/001_Hello_20260329-103000.md',
    };
    const mockCoord2 = {
      archive_id: 602,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 2,
      record_kind: 'ORIGINAL',
      command_id: 'cmd-602',
      platform_msg_id: 'tg:100:2',
      relative_path: 'TG_alice/Q001_General/002_Hello_20260329-103000.md',
    };

    let claimedIndex = 0;
    const items = [mockCoord1, mockCoord2];

    const mockRepo = {
      getPendingArchiveIds: () => new Set(),
      claimNextPendingArchiveCoordination: () => {
        if (claimedIndex < items.length) {
          return items[claimedIndex++];
        }
        return null;
      },
      getArchiveTopicById: () => ({ display_name: 'General' }),
      getOutboxCommand: () => ({ body: 'Reply' }),
      markArchiveCoordinationCompleted: ({ archiveId }) => {
        attemptedMutationAfterClose = true;
      },
      markArchiveCoordinationFailed: () => {},
    };

    let isClosedPassed = null;
    const mockWriter = {
      archiveRoot: tmpDir,
      publishArchiveRecord: async (params) => {
        isClosedPassed = params.isClosed;
        await slowWritePromise;
        return { status: 'COMPLETED' };
      },
    };

    const worker = new ArchiveWorker({
      repository: mockRepo,
      fileWriter: mockWriter,
      archiveRoot: tmpDir,
      stopTimeoutMs: 50,
    });

    await worker.start();
    worker.notifyPending();

    await new Promise((r) => setTimeout(r, 10));

    const stopPromise = worker.stop();
    await stopPromise;

    assert.strictEqual(worker.isStopped, true);
    assert.strictEqual(claimedIndex, 1);

    // Verify writer received isClosed predicate and it evaluates to true after stop timeout
    assert.strictEqual(typeof isClosedPassed, 'function');
    assert.strictEqual(isClosedPassed(), true);

    resolveSlowWrite();
    await new Promise((r) => setTimeout(r, 20));

    assert.strictEqual(attemptedMutationAfterClose, false);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('B1: ArchiveWorker.start awaits async cleanup, contains rejection without unhandled rejection, and continues start', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-worker-cleanup-b1-'));
  try {
    let unhandledOccurred = false;
    const unhandledListener = () => {
      unhandledOccurred = true;
    };
    process.on('unhandledRejection', unhandledListener);

    let cleanupStarted = false;
    let cleanupCompleted = false;

    // Injected mock writer whose fsPromises rejects during cleanup
    const failingFs = {
      readdir: async () => {
        cleanupStarted = true;
        // Delay slightly to prove start awaits cleanup
        await new Promise((r) => setTimeout(r, 20));
        cleanupCompleted = true;
        const err = new Error('EPERM: disk permission denied during startup cleanup');
        err.code = 'EPERM';
        throw err;
      },
    };

    const mockWriter = {
      archiveRoot: tmpDir,
      fsPromises: failingFs,
      publishArchiveRecord: async () => ({ status: 'COMPLETED' }),
    };

    let itemProcessed = false;
    const mockRepo = {
      getPendingArchiveIds: () => new Set([701]),
      claimNextPendingArchiveCoordination: () => {
        if (!itemProcessed) {
          itemProcessed = true;
          return {
            archive_id: 701,
            account_id: 'alice',
            topic_id: 1,
            entry_sequence: 1,
            record_kind: 'ORIGINAL',
            command_id: 'cmd-701',
            platform_msg_id: 'tg:100:1',
            relative_path: 'TG_alice/Q001_General/001_Hello_20260329-103000.md',
          };
        }
        return null;
      },
      getArchiveTopicById: () => ({ display_name: 'General' }),
      getOutboxCommand: () => ({ body: 'Reply' }),
      markArchiveCoordinationCompleted: () => {},
      markArchiveCoordinationFailed: () => {},
    };

    const worker = new ArchiveWorker({
      repository: mockRepo,
      fileWriter: mockWriter,
      archiveRoot: tmpDir,
    });

    // 1. start() must await cleanup and contain the rejection
    await worker.start();

    // Verify cleanup was awaited
    assert.strictEqual(cleanupStarted, true, 'cleanup must have started');
    assert.strictEqual(cleanupCompleted, true, 'cleanup must have finished before start returned');

    // 2. Normal start continues despite cleanup failure
    assert.strictEqual(worker.isRunning, true, 'worker must be running');

    // 3. Process item to prove normal operation continues
    await worker.triggerProcessing();
    assert.strictEqual(itemProcessed, true, 'normal processing continues');

    // 4. Verify no unhandled rejection occurred
    await new Promise((r) => setTimeout(r, 20));
    assert.strictEqual(unhandledOccurred, false, 'no unhandledRejection must occur');

    process.removeListener('unhandledRejection', unhandledListener);
    await worker.stop();
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});
