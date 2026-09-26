/**
 * runtime/channel-gateway/tests/outbox-worker.test.js
 *
 * TG-MVP-12: Outbox Worker Lifecycle, Safe Processing & Crash Recovery Test Suite.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { SqliteStateRepository } = require('../core/sqlite-state-repository');
const { OutboxWorker } = require('../core/outbox-worker');
const {
  OUTBOX_STATUS,
  TRANSPORT_PHASE,
  POLICY_DECISION,
  computeCanonicalPayloadHash,
} = require('../core/outbox-delivery-policy');

function createTempHarness() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-outbox-worker-test-'));
  const repo = new SqliteStateRepository(dir);
  return {
    stateRoot: dir,
    repo,
    cleanup() {
      try {
        repo.close();
      } catch (_) {}
      fs.rmSync(dir, { recursive: true, force: true });
    },
  };
}

function seedClaimedMessage(repo, channelId, holderId, fencingToken, messageId, accountId) {
  repo.takeoverChannel(channelId, holderId);
  // Direct raw seed in inbox
  const db = repo; // use repo's internal mechanism through raw seed or ingest
  const rawDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
  try {
    rawDb
      .prepare(
        `INSERT INTO inbox (channel_id, account_id, platform_msg_id, status, content, claimed_by, claimed_at_token)
         VALUES (?, ?, ?, 'claimed', 'test content', ?, ?);`
      )
      .run(channelId, accountId, messageId, holderId, fencingToken);
  } finally {
    rawDb.close();
  }
}

test('OutboxWorker - lifecycle start and clean stop with zero timer leak', async () => {
  const harness = createTempHarness();
  try {
    const worker = new OutboxWorker({
      repository: harness.repo,
      pollIntervalMs: 50,
    });

    assert.strictEqual(worker.isRunning, false);
    await worker.start();
    assert.strictEqual(worker.isRunning, true);

    await worker.stop();
    assert.strictEqual(worker.isRunning, false);
  } finally {
    harness.cleanup();
  }
});

test('OutboxWorker - without deliveryExecutor never consumes or drops QUEUED commands (Section 21)', async () => {
  const harness = createTempHarness();
  try {
    seedClaimedMessage(harness.repo, 'tg:chat:100', 'holder1', 1, 'tg:100:101', 'acc_tg');
    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: '100',
      logical_reply_target: 'tg:100:101',
      message_type: 'text',
      body: 'Hello',
    });

    const enqueueRes = harness.repo.enqueueAuthorizedReply({
      clientRequestId: 'req_1',
      channelId: 'tg:chat:100',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:100:101',
      replyingAccountId: 'acc_tg',
      text: 'Hello',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '100',
      logicalReplyTarget: 'tg:100:101',
      messageType: 'text',
      payloadHash: hash,
    });
    assert.strictEqual(enqueueRes.success, true);

    const worker = new OutboxWorker({
      repository: harness.repo,
      deliveryExecutor: null, // NO executor injected
    });

    await worker.start();
    const processed = await worker.processNext();
    assert.strictEqual(processed, null);

    // Verify command remains untouched in QUEUED state
    const cmd = harness.repo.getOutboxCommand(enqueueRes.commandId);
    assert.strictEqual(cmd.status, OUTBOX_STATUS.QUEUED);
    assert.strictEqual(cmd.attempt_count, 0);

    await worker.stop();
  } finally {
    harness.cleanup();
  }
});

test('OutboxWorker - R2-C: caller disconnect -> command persisted; standalone worker + fake executor processes to ACCEPTED_BY_PLATFORM', async () => {
  const harness = createTempHarness();
  try {
    seedClaimedMessage(harness.repo, 'tg:chat:100', 'holder1', 1, 'tg:100:102', 'acc_tg');
    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: '100',
      logical_reply_target: 'tg:100:102',
      message_type: 'text',
      body: 'Autonomous reply',
    });

    // 1. Caller enqueues and then "disconnects"
    const enqueueRes = harness.repo.enqueueAuthorizedReply({
      clientRequestId: 'req_r2c',
      channelId: 'tg:chat:100',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:100:102',
      replyingAccountId: 'acc_tg',
      text: 'Autonomous reply',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '100',
      logicalReplyTarget: 'tg:100:102',
      messageType: 'text',
      payloadHash: hash,
    });
    assert.strictEqual(enqueueRes.success, true);
    const cmdId = enqueueRes.commandId;

    // 2. Standalone worker with fake executor picks up the command
    let executed = false;
    const fakeExecutor = async (command) => {
      assert.strictEqual(command.command_id, cmdId);
      assert.strictEqual(command.status, OUTBOX_STATUS.IN_FLIGHT);
      assert.strictEqual(command.attempt_count, 1);
      executed = true;
      return { success: true, http_status: 200 };
    };

    const worker = new OutboxWorker({
      repository: harness.repo,
      deliveryExecutor: fakeExecutor,
    });

    await worker.start();
    const result = await worker.processNext();
    assert.ok(result);
    assert.strictEqual(result.command_id, cmdId);
    assert.strictEqual(result.decision, POLICY_DECISION.ACCEPTED_BY_PLATFORM);
    assert.strictEqual(executed, true);

    // Command transitioned to ACCEPTED_BY_PLATFORM
    const updated = harness.repo.getOutboxCommand(cmdId);
    assert.strictEqual(updated.status, OUTBOX_STATUS.ACCEPTED_BY_PLATFORM);

    await worker.stop();
  } finally {
    harness.cleanup();
  }
});

test('OutboxWorker - R2-J: valid Telegram retry_after schedules controlled delayed retry', async () => {
  const harness = createTempHarness();
  try {
    seedClaimedMessage(harness.repo, 'tg:chat:200', 'holder1', 1, 'tg:200:201', 'acc_tg');
    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: '200',
      logical_reply_target: 'tg:200:201',
      message_type: 'text',
      body: 'Rate limited text',
    });

    const nowSec = 1700000000;
    const enqueueRes = harness.repo.enqueueAuthorizedReply({
      clientRequestId: 'req_flood',
      channelId: 'tg:chat:200',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:200:201',
      replyingAccountId: 'acc_tg',
      text: 'Rate limited text',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '200',
      logicalReplyTarget: 'tg:200:201',
      messageType: 'text',
      payloadHash: hash,
      nowSec,
    });
    const cmdId = enqueueRes.commandId;

    // Fake executor simulates Telegram 429 flood control with retry_after = 20
    const fakeExecutor = async () => {
      return {
        phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
        http_status: 429,
        retry_after: 20,
      };
    };

    const worker = new OutboxWorker({
      repository: harness.repo,
      deliveryExecutor: fakeExecutor,
      nowSec: () => nowSec,
    });

    await worker.start();
    const result = await worker.processNext();
    assert.strictEqual(result.decision, POLICY_DECISION.RETRY);

    // Command should be rescheduled to QUEUED with next_attempt_at = nowSec + 20
    const cmd = harness.repo.getOutboxCommand(cmdId);
    assert.strictEqual(cmd.status, OUTBOX_STATUS.QUEUED);
    assert.strictEqual(cmd.attempt_count, 1);
    assert.strictEqual(cmd.next_attempt_at, nowSec + 20);

    // Immediately attempting to claim should return null since next_attempt_at is in the future
    const earlyClaim = harness.repo.claimNextQueuedOutboxCommand(nowSec);
    assert.strictEqual(earlyClaim, null);

    // After 20 seconds, claim should succeed
    const dueClaim = harness.repo.claimNextQueuedOutboxCommand(nowSec + 20);
    assert.ok(dueClaim);
    assert.strictEqual(dueClaim.command_id, cmdId);
    assert.strictEqual(dueClaim.attempt_count, 2);

    await worker.stop();
  } finally {
    harness.cleanup();
  }
});

test('OutboxWorker - R2-K: startup crash recovery transitions Telegram IN_FLIGHT -> UNCERTAIN (never blind resend)', async () => {
  const harness = createTempHarness();
  try {
    seedClaimedMessage(harness.repo, 'tg:chat:300', 'holder1', 1, 'tg:300:301', 'acc_tg');
    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: '300',
      logical_reply_target: 'tg:300:301',
      message_type: 'text',
      body: 'Crash test',
    });

    const enqueueRes = harness.repo.enqueueAuthorizedReply({
      clientRequestId: 'req_crash',
      channelId: 'tg:chat:300',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:300:301',
      replyingAccountId: 'acc_tg',
      text: 'Crash test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '300',
      logicalReplyTarget: 'tg:300:301',
      messageType: 'text',
      payloadHash: hash,
    });
    const cmdId = enqueueRes.commandId;

    // Simulate crash while command was IN_FLIGHT
    const claimed = harness.repo.claimNextQueuedOutboxCommand();
    assert.strictEqual(claimed.command_id, cmdId);
    assert.strictEqual(claimed.status, OUTBOX_STATUS.IN_FLIGHT);

    // Close repository to simulate process termination
    harness.repo.close();

    // New process restarts and reopens repository
    const restartedRepo = new SqliteStateRepository(harness.stateRoot);
    try {
      const worker = new OutboxWorker({
        repository: restartedRepo,
      });

      // Starting worker executes crash recovery
      await worker.start();

      // Telegram command MUST be transitioned to UNCERTAIN, never blind resend!
      const recoveredCmd = restartedRepo.getOutboxCommand(cmdId);
      assert.strictEqual(recoveredCmd.status, OUTBOX_STATUS.UNCERTAIN);

      // Verify bounded summary exposes uncertain command
      const uncertain = restartedRepo.getUncertainSummaries();
      assert.strictEqual(uncertain.count, 1);
      assert.strictEqual(uncertain.summaries[0].command_id, cmdId);
      assert.strictEqual(uncertain.summaries[0].platform, 'telegram');
      assert.strictEqual(uncertain.summaries[0].recipient, '300');
      // Body is strictly NOT present in summary
      assert.strictEqual(uncertain.summaries[0].body, undefined);

      await worker.stop();
    } finally {
      restartedRepo.close();
    }
  } finally {
    harness.cleanup();
  }
});

test('F2 canary: deliveryExecutor returns { success:false, http_status:500 } without phase -> Telegram command becomes UNCERTAIN', async () => {
  const harness = createTempHarness();
  try {
    seedClaimedMessage(harness.repo, 'tg:chat:501', 'holder1', 1, 'tg:501:1', 'acc_tg');
    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: '501',
      logical_reply_target: 'tg:501:1',
      message_type: 'text',
      body: 'Missing phase test',
    });

    const enqueueRes = harness.repo.enqueueAuthorizedReply({
      clientRequestId: 'req_missing_phase',
      channelId: 'tg:chat:501',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:501:1',
      replyingAccountId: 'acc_tg',
      text: 'Missing phase test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '501',
      logicalReplyTarget: 'tg:501:1',
      messageType: 'text',
      payloadHash: hash,
    });
    const cmdId = enqueueRes.commandId;

    // Delivery executor returns 500 without phase
    const worker = new OutboxWorker({
      repository: harness.repo,
      deliveryExecutor: async () => {
        return { success: false, http_status: 500 }; // no phase property provided!
      },
    });

    const processRes = await worker.processNext();
    assert.strictEqual(processRes.command_id, cmdId);
    assert.strictEqual(processRes.decision, POLICY_DECISION.UNCERTAIN);

    const afterCmd = harness.repo.getOutboxCommand(cmdId);
    assert.strictEqual(afterCmd.status, OUTBOX_STATUS.UNCERTAIN);
  } finally {
    harness.cleanup();
  }
});

test('F2 canary: deliveryExecutor returns invalid phase -> Telegram command becomes UNCERTAIN', async () => {
  const harness = createTempHarness();
  try {
    seedClaimedMessage(harness.repo, 'tg:chat:502', 'holder1', 1, 'tg:502:1', 'acc_tg');
    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: '502',
      logical_reply_target: 'tg:502:1',
      message_type: 'text',
      body: 'Invalid phase test',
    });

    const enqueueRes = harness.repo.enqueueAuthorizedReply({
      clientRequestId: 'req_invalid_phase',
      channelId: 'tg:chat:502',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:502:1',
      replyingAccountId: 'acc_tg',
      text: 'Invalid phase test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '502',
      logicalReplyTarget: 'tg:502:1',
      messageType: 'text',
      payloadHash: hash,
    });
    const cmdId = enqueueRes.commandId;

    const worker = new OutboxWorker({
      repository: harness.repo,
      deliveryExecutor: async () => {
        return { success: false, http_status: 500, phase: 'INVALID_BOGUS_PHASE' };
      },
    });

    const processRes = await worker.processNext();
    assert.strictEqual(processRes.command_id, cmdId);
    assert.strictEqual(processRes.decision, POLICY_DECISION.UNCERTAIN);

    const afterCmd = harness.repo.getOutboxCommand(cmdId);
    assert.strictEqual(afterCmd.status, OUTBOX_STATUS.UNCERTAIN);
  } finally {
    harness.cleanup();
  }
});

test('F3: OutboxWorker without deliveryExecutor runs recovery, has no active timer, and does not consume queue', async () => {
  const harness = createTempHarness();
  try {
    seedClaimedMessage(harness.repo, 'tg:chat:503', 'holder1', 1, 'tg:503:1', 'acc_tg');
    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: '503',
      logical_reply_target: 'tg:503:1',
      message_type: 'text',
      body: 'No executor test',
    });

    const enqueueRes = harness.repo.enqueueAuthorizedReply({
      clientRequestId: 'req_no_exec',
      channelId: 'tg:chat:503',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:503:1',
      replyingAccountId: 'acc_tg',
      text: 'No executor test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '503',
      logicalReplyTarget: 'tg:503:1',
      messageType: 'text',
      payloadHash: hash,
    });
    const cmdId = enqueueRes.commandId;

    const worker = new OutboxWorker({
      repository: harness.repo,
      // no deliveryExecutor
    });

    assert.strictEqual(worker.hasActiveTimer, false);
    await worker.start();
    assert.strictEqual(worker.isRunning, true);
    assert.strictEqual(worker.hasActiveTimer, false); // no perpetual polling timer!

    // Wait a brief tick to ensure no background consumption
    await new Promise((resolve) => setTimeout(resolve, 50));

    // Command must still be QUEUED
    const cmd = harness.repo.getOutboxCommand(cmdId);
    assert.strictEqual(cmd.status, OUTBOX_STATUS.QUEUED);
    assert.strictEqual(cmd.attempt_count, 0);

    await worker.stop();
    assert.strictEqual(worker.isRunning, false);
    assert.strictEqual(worker.hasActiveTimer, false);
  } finally {
    harness.cleanup();
  }
});

test('OutboxWorker - propagates terminalReasonCode to repository on terminal failure', async () => {
  const harness = createTempHarness();
  try {
    seedClaimedMessage(harness.repo, 'tg:chat:200', 'holder1', 1, 'tg:200:201', 'acc_tg');
    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: '200',
      logical_reply_target: 'tg:200:201',
      message_type: 'text',
      body: 'Terminal failure test',
    });

    const enqueueRes = harness.repo.enqueueAuthorizedReply({
      clientRequestId: 'req_terminal_reason',
      channelId: 'tg:chat:200',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:200:201',
      replyingAccountId: 'acc_tg',
      text: 'Terminal failure test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '200',
      logicalReplyTarget: 'tg:200:201',
      messageType: 'text',
      payloadHash: hash,
    });
    assert.strictEqual(enqueueRes.success, true);
    const cmdId = enqueueRes.commandId;

    // Delivery executor returns 400 client error
    const worker = new OutboxWorker({
      repository: harness.repo,
      deliveryExecutor: async () => ({
        success: false,
        http_status: 400,
        transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
      }),
    });

    await worker.start();
    const result = await worker.processNext();
    assert.strictEqual(result.decision, POLICY_DECISION.FAILED_TERMINAL);

    const cmd = harness.repo.getOutboxCommand(cmdId);
    assert.strictEqual(cmd.status, OUTBOX_STATUS.FAILED_TERMINAL);
    assert.strictEqual(cmd.terminal_reason_code, 'TELEGRAM_CLIENT_ERROR_400');
    assert.strictEqual(cmd.next_attempt_at, null);

    await worker.stop();
  } finally {
    harness.cleanup();
  }
});

