/**
 * runtime/channel-gateway/tests/channel-control.test.js
 *
 * Canonical Node tests for ADR-0022 D5–D10 channel control semantics.
 * Uses node:test and node:assert only.
 * All test fixtures and metadata are purely synthetic.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { ChannelControl, MESSAGE_STATUS } = require('../core/channel-control');

test('ChannelControl - 1. TG / LINE independent state objects do not cross-pollute', () => {
  const tgControl = new ChannelControl('telegram');
  const lineControl = new ChannelControl('line');

  tgControl.takeover('synthetic-agent-tg-1');
  assert.strictEqual(tgControl.currentHolder, 'synthetic-agent-tg-1');
  assert.strictEqual(tgControl.fencingToken, 1);

  // LINE remains completely unaffected
  assert.strictEqual(lineControl.currentHolder, null);
  assert.strictEqual(lineControl.fencingToken, 0);

  lineControl.takeover('synthetic-agent-line-1');
  assert.strictEqual(lineControl.currentHolder, 'synthetic-agent-line-1');
  assert.strictEqual(lineControl.fencingToken, 1);

  // TG state was not affected by line takeover
  assert.strictEqual(tgControl.currentHolder, 'synthetic-agent-tg-1');
  assert.strictEqual(tgControl.fencingToken, 1);
});

test('ChannelControl - 2. explicit takeover successfully acquires holder', () => {
  const control = new ChannelControl('telegram');
  assert.strictEqual(control.currentHolder, null);

  const res = control.takeover('synthetic-agent-alpha');
  assert.strictEqual(res.success, true);
  assert.strictEqual(res.holder, 'synthetic-agent-alpha');
  assert.strictEqual(control.currentHolder, 'synthetic-agent-alpha');
});

test('ChannelControl - 3. takeover increments fencing/version token monotonically', () => {
  const control = new ChannelControl('telegram');
  assert.strictEqual(control.fencingToken, 0);

  const res1 = control.takeover('synthetic-agent-1');
  assert.strictEqual(res1.fencingToken, 1);
  assert.strictEqual(control.fencingToken, 1);

  const res2 = control.takeover('synthetic-agent-2');
  assert.strictEqual(res2.fencingToken, 2);
  assert.strictEqual(control.fencingToken, 2);

  const res3 = control.takeover('synthetic-agent-3');
  assert.strictEqual(res3.fencingToken, 3);
  assert.strictEqual(control.fencingToken, 3);
});

test('ChannelControl - 4. heartbeat with current holder succeeds', () => {
  const control = new ChannelControl('telegram');
  control.takeover('synthetic-agent-primary');

  const hb = control.heartbeat('synthetic-agent-primary', 1, { timestamp: 1000 });
  assert.strictEqual(hb.success, true);
  assert.strictEqual(hb.holder, 'synthetic-agent-primary');
  assert.strictEqual(hb.fencingToken, 1);
});

test('ChannelControl - 5. heartbeat with stale token fails and does not takeover', () => {
  const control = new ChannelControl('telegram');
  control.takeover('synthetic-agent-1'); // token 1
  control.takeover('synthetic-agent-2'); // token 2

  // Stale holder or stale token attempts heartbeat
  const hb1 = control.heartbeat('synthetic-agent-1', 1);
  assert.strictEqual(hb1.success, false);
  assert.strictEqual(hb1.reason, 'HOLDER_MISMATCH');

  // Current holder but stale token
  const hb2 = control.heartbeat('synthetic-agent-2', 1);
  assert.strictEqual(hb2.success, false);
  assert.strictEqual(hb2.reason, 'STALE_FENCING_TOKEN');

  // Holder must remain agent-2 with token 2
  assert.strictEqual(control.currentHolder, 'synthetic-agent-2');
  assert.strictEqual(control.fencingToken, 2);
});

test('ChannelControl - 6. poll cannot acquire control when there is no holder', () => {
  const control = new ChannelControl('telegram');
  control.enqueueMessage({ id: 'syn-msg-1', receivingAccountId: 'acct-syn-1' });

  assert.strictEqual(control.currentHolder, null);

  // Poll attempt without prior takeover
  const pollRes = control.pollMessages('synthetic-unauthorized-agent', 1);
  assert.strictEqual(pollRes.success, false);
  assert.strictEqual(pollRes.reason, 'NOT_CURRENT_HOLDER');
  assert.strictEqual(pollRes.claimedMessages.length, 0);

  // Holder must remain null (no implicit takeover)
  assert.strictEqual(control.currentHolder, null);
  assert.strictEqual(control.getBacklogCount(), 1);
});

test('ChannelControl - 7. regular takeover discards old claimed messages', () => {
  const control = new ChannelControl('telegram');
  control.takeover('synthetic-agent-1'); // token 1

  control.enqueueMessage({ id: 'syn-msg-1', receivingAccountId: 'acct-syn-1' });
  control.enqueueMessage({ id: 'syn-msg-2', receivingAccountId: 'acct-syn-1' });

  // Agent 1 claims msg-1 (limit = 1)
  const pollRes = control.pollMessages('synthetic-agent-1', 1, 1);
  assert.strictEqual(pollRes.claimedMessages.length, 1);
  assert.strictEqual(pollRes.claimedMessages[0].id, 'syn-msg-1');

  // Agent 2 executes regular takeover
  const takeoverRes = control.takeover('synthetic-agent-2');
  assert.strictEqual(takeoverRes.fencingToken, 2);

  // Old claimed message must be discarded
  assert.strictEqual(takeoverRes.discardedMessages.length, 1);
  assert.strictEqual(takeoverRes.discardedMessages[0].id, 'syn-msg-1');
  assert.strictEqual(takeoverRes.discardedMessages[0].status, MESSAGE_STATUS.DISCARDED);
});

test('ChannelControl - 8. regular takeover preserves still-queued messages', () => {
  const control = new ChannelControl('telegram');
  control.takeover('synthetic-agent-1');

  control.enqueueMessage({ id: 'syn-msg-1', receivingAccountId: 'acct-syn-1' });
  control.enqueueMessage({ id: 'syn-msg-2', receivingAccountId: 'acct-syn-1' });

  // Agent 1 claims msg-1 only
  control.pollMessages('synthetic-agent-1', 1, 1);

  // msg-2 is still queued
  assert.strictEqual(control.getBacklogCount(), 1);

  // Agent 2 takes over
  const takeoverRes = control.takeover('synthetic-agent-2');
  assert.strictEqual(takeoverRes.backlogCount, 1);

  // Agent 2 polls and should receive msg-2
  const agent2Poll = control.pollMessages('synthetic-agent-2', 2);
  assert.strictEqual(agent2Poll.claimedMessages.length, 1);
  assert.strictEqual(agent2Poll.claimedMessages[0].id, 'syn-msg-2');
  assert.strictEqual(agent2Poll.claimedMessages[0].claimedBy, 'synthetic-agent-2');
});

test('ChannelControl - 9. expired holder discards claimed messages', () => {
  const control = new ChannelControl('telegram');
  control.takeover('synthetic-agent-temp');

  control.enqueueMessage({ id: 'syn-msg-claim', receivingAccountId: 'acct-syn-1' });
  control.pollMessages('synthetic-agent-temp', 1);

  // Expire holder
  const expRes = control.expireHolder();
  assert.strictEqual(expRes.success, true);
  assert.strictEqual(expRes.expiredHolder, 'synthetic-agent-temp');
  assert.strictEqual(expRes.discardedMessages.length, 1);
  assert.strictEqual(expRes.discardedMessages[0].id, 'syn-msg-claim');
  assert.strictEqual(expRes.discardedMessages[0].status, MESSAGE_STATUS.DISCARDED);
  assert.strictEqual(control.currentHolder, null);
});

test('ChannelControl - 10. expired holder preserves queued messages', () => {
  const control = new ChannelControl('telegram');
  control.takeover('synthetic-agent-temp');

  control.enqueueMessage({ id: 'syn-msg-1', receivingAccountId: 'acct-syn-1' });
  control.enqueueMessage({ id: 'syn-msg-2', receivingAccountId: 'acct-syn-1' });

  // Claim msg-1, leave msg-2 queued
  control.pollMessages('synthetic-agent-temp', 1, 1);

  // Expire holder
  const expRes = control.expireHolder();
  assert.strictEqual(expRes.backlogCount, 1);
  assert.strictEqual(control.getBacklogCount(), 1);

  // When next agent takes over, msg-2 is still available
  control.takeover('synthetic-agent-next');
  const nextPoll = control.pollMessages('synthetic-agent-next', 2);
  assert.strictEqual(nextPoll.claimedMessages.length, 1);
  assert.strictEqual(nextPoll.claimedMessages[0].id, 'syn-msg-2');
});

test('ChannelControl - 11. stale holder reply authorization rejected', () => {
  const control = new ChannelControl('telegram');
  control.takeover('synthetic-agent-1');

  control.enqueueMessage({ id: 'syn-msg-reply', receivingAccountId: 'acct-syn-1' });
  control.pollMessages('synthetic-agent-1', 1);

  // Takeover by Agent 2
  control.takeover('synthetic-agent-2');

  // Agent 1 attempts to authorize reply with stale token and stale identity
  const staleAuth1 = control.authorizeReply('synthetic-agent-1', 1, 'syn-msg-reply');
  assert.strictEqual(staleAuth1.authorized, false);
  assert.strictEqual(staleAuth1.reason, 'NOT_CURRENT_HOLDER');

  // Agent 2 with stale token attempt
  const staleAuth2 = control.authorizeReply('synthetic-agent-2', 1, 'syn-msg-reply');
  assert.strictEqual(staleAuth2.authorized, false);
  assert.strictEqual(staleAuth2.reason, 'STALE_FENCING_TOKEN');

  // Even with valid current token, msg-reply was discarded on takeover
  const staleAuth3 = control.authorizeReply('synthetic-agent-2', 2, 'syn-msg-reply');
  assert.strictEqual(staleAuth3.authorized, false);
  assert.strictEqual(staleAuth3.reason, 'MESSAGE_NOT_CLAIMED');
});

test('ChannelControl - 12. no-holder incoming queue can accumulate messages', () => {
  const control = new ChannelControl('telegram');
  assert.strictEqual(control.currentHolder, null);

  control.enqueueMessage({ id: 'syn-queued-1', receivingAccountId: 'acct-syn-1' });
  control.enqueueMessage({ id: 'syn-queued-2', receivingAccountId: 'acct-syn-1' });
  control.enqueueMessage({ id: 'syn-queued-3', receivingAccountId: 'acct-syn-2' });

  assert.strictEqual(control.getBacklogCount(), 3);
});

test('ChannelControl - 13. backlog count reflects queued messages accurately', () => {
  const control = new ChannelControl('telegram');
  assert.strictEqual(control.getBacklogCount(), 0);

  control.enqueueMessage({ id: 'm1', receivingAccountId: 'a1' });
  assert.strictEqual(control.getBacklogCount(), 1);

  control.enqueueMessage({ id: 'm2', receivingAccountId: 'a1' });
  assert.strictEqual(control.getBacklogCount(), 2);

  control.takeover('synthetic-agent-1');
  assert.strictEqual(control.getBacklogCount(), 2);

  control.pollMessages('synthetic-agent-1', 1, 1);
  assert.strictEqual(control.getBacklogCount(), 1);

  control.pollMessages('synthetic-agent-1', 1, 1);
  assert.strictEqual(control.getBacklogCount(), 0);
});
