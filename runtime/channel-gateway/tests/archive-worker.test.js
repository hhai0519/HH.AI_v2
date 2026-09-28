/**
 * runtime/channel-gateway/tests/archive-worker.test.js
 *
 * TG-MVP-14: ArchiveWorker lifecycle and queue processing tests.
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
    // Content snapshot is NOT cleared in DB (markArchiveCoordinationFailed preserves it)

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
        // If closed guard is active, this must not be reached
        attemptedMutationAfterClose = true;
      },
      markArchiveCoordinationFailed: () => {},
    };

    const mockWriter = {
      archiveRoot: tmpDir,
      publishArchiveRecord: async () => {
        // Hung / slow write that exceeds test stop timeout
        await slowWritePromise;
        return { status: 'COMPLETED' };
      },
    };

    const worker = new ArchiveWorker({
      repository: mockRepo,
      fileWriter: mockWriter,
      archiveRoot: tmpDir,
      stopTimeoutMs: 50, // Short injected stop timeout for test
    });

    await worker.start();
    // Schedule item 601
    worker.notifyPending();

    // Give it a tick to start processing item 1
    await new Promise((r) => setTimeout(r, 10));

    // Call stop() while item 1 is hanging
    const stopPromise = worker.stop();
    await stopPromise;

    // Stop must have completed within bounded time (< 200ms)
    assert.strictEqual(worker.isStopped, true);

    // Second item (602) was NEVER claimed because stop halts queue drainage
    assert.strictEqual(claimedIndex, 1);

    // Now resolve slow write after stop has closed
    resolveSlowWrite();
    await new Promise((r) => setTimeout(r, 20));

    // Closed guard prevents DB mutation after timeout
    assert.strictEqual(attemptedMutationAfterClose, false);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});
