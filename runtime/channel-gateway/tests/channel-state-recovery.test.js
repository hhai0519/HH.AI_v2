/**
 * runtime/channel-gateway/tests/channel-state-recovery.test.js
 *
 * ADR-0022 D10: Tests for Channel Control Durable Snapshot & Safe Restart Recovery.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { ChannelControl, MESSAGE_STATUS } = require('../core/channel-control');
const {
  CHANNEL_SNAPSHOT_SCHEMA_VERSION,
  validateChannelControlSnapshot,
  buildChannelControlSnapshot,
  recoverChannelControlFromSnapshot,
} = require('../core/channel-state-recovery');

test('ChannelStateRecovery - 1. snapshot schema version = 1', () => {
  const control = new ChannelControl('telegram');
  const snapshot = buildChannelControlSnapshot(control);
  assert.equal(snapshot.schemaVersion, CHANNEL_SNAPSHOT_SCHEMA_VERSION);
  assert.equal(snapshot.schemaVersion, 1);
});

test('ChannelStateRecovery - 2. snapshot excludes currentHolder', () => {
  const control = new ChannelControl('telegram');
  control.takeover('agent-session-1');
  assert.equal(control.currentHolder, 'agent-session-1');

  const snapshot = buildChannelControlSnapshot(control);
  assert.equal(Object.prototype.hasOwnProperty.call(snapshot, 'currentHolder'), false);
  assert.equal(snapshot.currentHolder, undefined);
});

test('ChannelStateRecovery - 3. snapshot excludes lastHeartbeatAt', () => {
  const control = new ChannelControl('telegram');
  control.takeover('agent-session-1', { timestamp: 123456789 });
  assert.equal(control.lastHeartbeatAt, 123456789);

  const snapshot = buildChannelControlSnapshot(control);
  assert.equal(Object.prototype.hasOwnProperty.call(snapshot, 'lastHeartbeatAt'), false);
  assert.equal(snapshot.lastHeartbeatAt, undefined);
});

test('ChannelStateRecovery - 4. fencingToken exported', () => {
  const control = new ChannelControl('telegram');
  control.takeover('holder-1');
  control.takeover('holder-2');
  control.takeover('holder-3');
  assert.equal(control.fencingToken, 3);

  const snapshot = buildChannelControlSnapshot(control);
  assert.equal(snapshot.fencingToken, 3);
});

test('ChannelStateRecovery - 5. queued messages exported', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'm1', receivingAccountId: 'bot-1', metadata: { text: 'hello' } });
  control.enqueueMessage({ id: 'm2', receivingAccountId: 'bot-1', metadata: { text: 'world' } });

  const snapshot = buildChannelControlSnapshot(control);
  assert.equal(snapshot.messages.length, 2);
  assert.equal(snapshot.messages[0].id, 'm1');
  assert.equal(snapshot.messages[0].status, MESSAGE_STATUS.QUEUED);
  assert.equal(snapshot.messages[1].id, 'm2');
  assert.equal(snapshot.messages[1].status, MESSAGE_STATUS.QUEUED);
});

test('ChannelStateRecovery - 6. snapshot is deep copy', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'm1', receivingAccountId: 'bot-1', metadata: { score: 10 } });

  const snapshot = buildChannelControlSnapshot(control);
  assert.notEqual(snapshot.messages, control.messages);
  assert.notEqual(snapshot.messages[0], control.messages[0]);
  assert.notEqual(snapshot.messages[0].metadata, control.messages[0].metadata);

  // Mutating control does not mutate snapshot
  control.messages[0].metadata.score = 999;
  assert.equal(snapshot.messages[0].metadata.score, 10);
});

test('ChannelStateRecovery - 7. duplicate message id rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 1,
    messages: [
      {
        id: 'dup-id',
        receivingAccountId: 'bot-1',
        status: 'queued',
        claimedBy: null,
        claimedAtToken: null,
        discardReason: null,
        metadata: {},
        discardedByHolder: null,
        discardedAtToken: null,
      },
      {
        id: 'dup-id',
        receivingAccountId: 'bot-1',
        status: 'queued',
        claimedBy: null,
        claimedAtToken: null,
        discardReason: null,
        metadata: {},
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /Duplicate message id in snapshot: 'dup-id'/
  );
});

test('ChannelStateRecovery - 8. unknown top-level snapshot key rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 1,
    messages: [],
    extraKey: 'not-allowed',
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /Unknown top-level snapshot key: 'extraKey'/
  );
});

test('ChannelStateRecovery - 9. unknown message key rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 1,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'queued',
        claimedBy: null,
        claimedAtToken: null,
        discardReason: null,
        metadata: {},
        discardedByHolder: null,
        discardedAtToken: null,
        rogueKey: 123,
      },
    ],
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /unknown message key: 'rogueKey'/
  );
});

test('ChannelStateRecovery - 10. invalid status rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 1,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'in_progress',
        claimedBy: null,
        claimedAtToken: null,
        discardReason: null,
        metadata: {},
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /invalid message status 'in_progress'/
  );
});

test('ChannelStateRecovery - 11. QUEUED with claim metadata rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 1,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'queued',
        claimedBy: 'holder-1',
        claimedAtToken: 1,
        discardReason: null,
        metadata: {},
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /QUEUED message must have claimedBy === null/
  );
});

test('ChannelStateRecovery - 12. CLAIMED without holder rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 1,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'claimed',
        claimedBy: null,
        claimedAtToken: 1,
        discardReason: null,
        metadata: {},
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /CLAIMED message must have non-empty claimedBy/
  );
});

test('ChannelStateRecovery - 13. CLAIMED token != snapshot fencing token rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 5,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'claimed',
        claimedBy: 'holder-1',
        claimedAtToken: 4, // Stale token mismatch
        discardReason: null,
        metadata: {},
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /CLAIMED message claimedAtToken \(4\) must match snapshot fencingToken \(5\)/
  );
});

test('ChannelStateRecovery - 14. REPLIED claim token > fencing token rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 3,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'replied',
        claimedBy: 'holder-1',
        claimedAtToken: 4, // Future token impossible
        discardReason: null,
        metadata: {},
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /REPLIED message claimedAtToken \(4\) cannot exceed snapshot fencingToken \(3\)/
  );
});

test('ChannelStateRecovery - 15. invalid metadata JSON compatibility rejected', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 1,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'queued',
        claimedBy: null,
        claimedAtToken: null,
        discardReason: null,
        metadata: {
          badNumber: NaN,
        },
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  assert.throws(
    () => validateChannelControlSnapshot(snapshot),
    /number must be finite/
  );
});

test('ChannelStateRecovery - 16. recovery holder = null', () => {
  const control = new ChannelControl('telegram');
  control.takeover('active-agent');
  const snapshot = buildChannelControlSnapshot(control);

  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);
  assert.equal(recovered.currentHolder, null);
});

test('ChannelStateRecovery - 17. recovery heartbeat = null', () => {
  const control = new ChannelControl('telegram');
  control.takeover('active-agent', { timestamp: 999999 });
  const snapshot = buildChannelControlSnapshot(control);

  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);
  assert.equal(recovered.lastHeartbeatAt, null);
});

test('ChannelStateRecovery - 18. recovery fencing token preserved', () => {
  const control = new ChannelControl('telegram');
  control.takeover('h1');
  control.takeover('h2');
  control.takeover('h3');
  assert.equal(control.fencingToken, 3);

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(recovered.fencingToken, 3);
});

test('ChannelStateRecovery - 19. QUEUED preserved', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'q1', receivingAccountId: 'bot-1', metadata: { text: 'keep me' } });
  control.enqueueMessage({ id: 'q2', receivingAccountId: 'bot-1', metadata: { text: 'keep me too' } });

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(recovered.messages.length, 2);
  assert.equal(recovered.messages[0].status, MESSAGE_STATUS.QUEUED);
  assert.equal(recovered.messages[1].status, MESSAGE_STATUS.QUEUED);
  assert.equal(recovered.getBacklogCount(), 2);
});

test('ChannelStateRecovery - 20. CLAIMED -> DISCARDED', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'c1', receivingAccountId: 'bot-1' });
  control.takeover('agent-1');
  control.pollMessages('agent-1', control.fencingToken);

  assert.equal(control.messages[0].status, MESSAGE_STATUS.CLAIMED);

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(recovered.messages[0].status, MESSAGE_STATUS.DISCARDED);
});

test('ChannelStateRecovery - 21. restart discard reason = GATEWAY_RESTART', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'c1', receivingAccountId: 'bot-1' });
  control.takeover('agent-1');
  control.pollMessages('agent-1', control.fencingToken);

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(recovered.messages[0].discardReason, 'GATEWAY_RESTART');
  assert.equal(recovered.messages[0].discardedByHolder, 'agent-1');
  assert.equal(recovered.messages[0].discardedAtToken, control.fencingToken);
});

test('ChannelStateRecovery - 22. discardedOnRecovery contains claimed message', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'c1', receivingAccountId: 'bot-1', metadata: { payload: 'secret' } });
  control.takeover('agent-1');
  control.pollMessages('agent-1', control.fencingToken);

  const snapshot = buildChannelControlSnapshot(control);
  const { discardedOnRecovery } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(discardedOnRecovery.length, 1);
  assert.deepStrictEqual(discardedOnRecovery[0], {
    id: 'c1',
    receivingAccountId: 'bot-1',
    status: 'discarded',
    discardReason: 'GATEWAY_RESTART',
  });
  // Must NOT leak message payload/metadata in notification struct
  assert.equal(discardedOnRecovery[0].metadata, undefined);
  assert.equal(discardedOnRecovery[0].payload, undefined);
});

test('ChannelStateRecovery - 23. REPLIED preserved', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'r1', receivingAccountId: 'bot-1' });
  control.takeover('agent-1');
  control.pollMessages('agent-1', control.fencingToken);
  control.authorizeReply('agent-1', control.fencingToken, 'r1', 'bot-1');

  assert.equal(control.messages[0].status, MESSAGE_STATUS.REPLIED);

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(recovered.messages[0].status, MESSAGE_STATUS.REPLIED);
});

test('ChannelStateRecovery - 24. existing DISCARDED preserved', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'd1', receivingAccountId: 'bot-1' });
  control.discardQueuedForAccount('bot-1', 'USER_CANCELLED');

  assert.equal(control.messages[0].status, MESSAGE_STATUS.DISCARDED);
  assert.equal(control.messages[0].discardReason, 'USER_CANCELLED');

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(recovered.messages[0].status, MESSAGE_STATUS.DISCARDED);
  assert.equal(recovered.messages[0].discardReason, 'USER_CANCELLED');
});

test('ChannelStateRecovery - 25. backlog only counts queued', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'm-queued-1', receivingAccountId: 'bot-1' });
  control.enqueueMessage({ id: 'm-queued-2', receivingAccountId: 'bot-1' });
  control.enqueueMessage({ id: 'm-claimed', receivingAccountId: 'bot-1' });

  control.takeover('agent-1');
  control.pollMessages('agent-1', control.fencingToken, 1);

  assert.equal(control.getBacklogCount(), 2);

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered, discardedOnRecovery } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(recovered.getBacklogCount(), 2);
  assert.equal(discardedOnRecovery.length, 1);
});

test('ChannelStateRecovery - 26. old holder poll after recovery rejected', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'm1', receivingAccountId: 'bot-1' });
  control.takeover('old-agent');

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  const pollRes = recovered.pollMessages('old-agent', recovered.fencingToken);
  assert.equal(pollRes.success, false);
  assert.equal(pollRes.reason, 'NOT_CURRENT_HOLDER');
});

test('ChannelStateRecovery - 27. old holder reply after recovery rejected', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'm1', receivingAccountId: 'bot-1' });
  control.takeover('old-agent');
  control.pollMessages('old-agent', control.fencingToken);

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  const replyRes = recovered.authorizeReply('old-agent', recovered.fencingToken, 'm1', 'bot-1');
  assert.equal(replyRes.authorized, false);
  assert.equal(replyRes.reason, 'NOT_CURRENT_HOLDER');
});

test('ChannelStateRecovery - 28. new takeover increments N -> N+1', () => {
  const control = new ChannelControl('telegram');
  control.takeover('old-agent');
  assert.equal(control.fencingToken, 1);

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  assert.equal(recovered.fencingToken, 1);

  const takeoverRes = recovered.takeover('new-agent');
  assert.equal(takeoverRes.success, true);
  assert.equal(recovered.fencingToken, 2);
  assert.equal(recovered.currentHolder, 'new-agent');
});

test('ChannelStateRecovery - 29. old token N stale after new takeover', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'm1', receivingAccountId: 'bot-1' });
  control.takeover('agent-1');
  const tokenN = control.fencingToken; // 1

  const snapshot = buildChannelControlSnapshot(control);
  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  // New takeover makes token 2
  recovered.takeover('agent-2');
  assert.equal(recovered.fencingToken, 2);

  // Attempt using old token N with new holder fails
  const pollRes = recovered.pollMessages('agent-2', tokenN);
  assert.equal(pollRes.success, false);
  assert.equal(pollRes.reason, 'STALE_FENCING_TOKEN');
});

test('ChannelStateRecovery - 30. snapshot input object not mutated', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 2,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'claimed',
        claimedBy: 'agent-1',
        claimedAtToken: 2,
        discardReason: null,
        metadata: { info: 'test' },
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  const snapshotCopy = JSON.parse(JSON.stringify(snapshot));
  recoverChannelControlFromSnapshot(snapshot);

  assert.deepStrictEqual(snapshot, snapshotCopy);
});

test('ChannelStateRecovery - 31. recovered message objects do not alias snapshot objects', () => {
  const snapshot = {
    schemaVersion: 1,
    channelId: 'telegram',
    fencingToken: 1,
    messages: [
      {
        id: 'm1',
        receivingAccountId: 'bot-1',
        status: 'queued',
        claimedBy: null,
        claimedAtToken: null,
        discardReason: null,
        metadata: { flag: true },
        discardedByHolder: null,
        discardedAtToken: null,
      },
    ],
  };

  const { control: recovered } = recoverChannelControlFromSnapshot(snapshot);

  assert.notEqual(recovered.messages[0], snapshot.messages[0]);
  assert.notEqual(recovered.messages[0].metadata, snapshot.messages[0].metadata);

  recovered.messages[0].metadata.flag = false;
  assert.equal(snapshot.messages[0].metadata.flag, true);
});

test('ChannelStateRecovery - 32. normal empty state snapshot/recovery works', () => {
  const control = new ChannelControl('line');
  assert.equal(control.fencingToken, 0);
  assert.equal(control.messages.length, 0);

  const snapshot = buildChannelControlSnapshot(control);
  assert.equal(snapshot.schemaVersion, 1);
  assert.equal(snapshot.channelId, 'line');
  assert.equal(snapshot.fencingToken, 0);
  assert.equal(snapshot.messages.length, 0);

  const { control: recovered, discardedOnRecovery } = recoverChannelControlFromSnapshot(snapshot);
  assert.equal(recovered.channelId, 'line');
  assert.equal(recovered.fencingToken, 0);
  assert.equal(recovered.currentHolder, null);
  assert.equal(recovered.lastHeartbeatAt, null);
  assert.equal(recovered.messages.length, 0);
  assert.equal(discardedOnRecovery.length, 0);
});
