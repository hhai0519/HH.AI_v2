/**
 * runtime/channel-gateway/tests/local-api-dispatcher.test.js
 *
 * Tests for LocalApiDispatcher: Schemas, Status, Takeover, Synchronous Poll, Heartbeat, Reply.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { DatabaseSync } = require('node:sqlite');
const { SqliteStateRepository } = require('../core/sqlite-state-repository');
const { LocalApiDispatcher } = require('../core/local-api-dispatcher');

function createTempHarness() {
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-dispatcher-test-'));
  const stateRoot = path.join(baseDir, 'state');
  fs.mkdirSync(stateRoot, { recursive: true });

  const repo = new SqliteStateRepository(stateRoot);

  function seedInbox(channelId, messageId, status = 'queued', extra = {}) {
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const stmt = rawDb.prepare(
        `INSERT INTO inbox (
          channel_id, account_id, platform_msg_id, status, content,
          claimed_by, claimed_at_token
        ) VALUES (?, ?, ?, ?, ?, ?, ?);`
      );
      stmt.run(
        channelId,
        extra.accountId || 'acc_default',
        String(messageId),
        status,
        extra.content ?? `content of ${messageId}`,
        extra.claimedBy ?? null,
        extra.claimedAtToken ?? null
      );
    } finally {
      rawDb.close();
    }
  }

  function cleanup() {
    try {
      repo.close();
    } catch {}
    try {
      fs.rmSync(baseDir, { recursive: true, force: true });
    } catch {}
  }

  return { stateRoot, repo, seedInbox, cleanup };
}

test('dispatcher: invalid JSON or unknown fields return 400 INVALID_REQUEST with no details', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });

    // Non-object body
    assert.deepEqual(dispatcher.dispatch('/v1/status', 'not-json'), {
      status: 400,
      body: { ok: false, code: 'INVALID_REQUEST' },
    });

    // Array body
    assert.deepEqual(dispatcher.dispatch('/v1/status', []), {
      status: 400,
      body: { ok: false, code: 'INVALID_REQUEST' },
    });

    // Unknown field in status
    assert.deepEqual(dispatcher.dispatch('/v1/status', { channel_id: 'c1', extra: 'bad' }), {
      status: 400,
      body: { ok: false, code: 'INVALID_REQUEST' },
    });

    // Missing field in takeover
    assert.deepEqual(dispatcher.dispatch('/v1/takeover', { channel_id: 'c1' }), {
      status: 400,
      body: { ok: false, code: 'INVALID_REQUEST' },
    });

    // Invalid limit in poll
    assert.deepEqual(dispatcher.dispatch('/v1/poll', { channel_id: 'c1', holder_id: 'h1', fencing_token: 1, limit: 0 }), {
      status: 400,
      body: { ok: false, code: 'INVALID_REQUEST' },
    });
    assert.deepEqual(dispatcher.dispatch('/v1/poll', { channel_id: 'c1', holder_id: 'h1', fencing_token: 1, limit: 51 }), {
      status: 400,
      body: { ok: false, code: 'INVALID_REQUEST' },
    });

    // Oversized text in reply (> 4096 code units)
    assert.deepEqual(
      dispatcher.dispatch('/v1/reply', {
        client_request_id: 'req1',
        channel_id: 'c1',
        holder_id: 'h1',
        fencing_token: 1,
        message_id: 'm1',
        replying_account_id: 'acc1',
        text: 'x'.repeat(4097),
      }),
      { status: 400, body: { ok: false, code: 'INVALID_REQUEST' } }
    );
  } finally {
    harness.cleanup();
  }
});

test('dispatcher: repository exceptions throw into 500 INTERNAL_ERROR with zero leakage (T20)', { timeout: 5000 }, () => {
  const fakeRepo = {
    getChannelState() {
      throw new Error('SQLite database is locked! Secret leaked: pass123');
    },
  };
  const dispatcher = new LocalApiDispatcher({ repository: fakeRepo });

  const res = dispatcher.dispatch('/v1/status', { channel_id: 'c1' });
  assert.equal(res.status, 500);
  assert.deepEqual(res.body, { ok: false, code: 'INTERNAL_ERROR' });
  assert.equal(JSON.stringify(res.body).includes('SQLite'), false);
  assert.equal(JSON.stringify(res.body).includes('pass123'), false);
});

test('dispatcher: status endpoint returns 200 with mapped fields or 404 CHANNEL_NOT_FOUND', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });

    // Not found
    const res404 = dispatcher.dispatch('/v1/status', { channel_id: 'tg:notfound' });
    assert.deepEqual(res404, {
      status: 404,
      body: { ok: false, code: 'CHANNEL_NOT_FOUND' },
    });

    // Establish channel
    harness.repo.takeoverChannel('tg:chan1', 'holder1');
    harness.seedInbox('tg:chan1', 'msg1', 'queued');

    const res200 = dispatcher.dispatch('/v1/status', { channel_id: 'tg:chan1' });
    assert.equal(res200.status, 200);
    assert.equal(res200.body.ok, true);
    assert.equal(res200.body.code, 'OK');
    assert.equal(res200.body.channel_id, 'tg:chan1');
    assert.equal(res200.body.current_holder, 'holder1');
    assert.equal(res200.body.fencing_token, 1);
    assert.equal(res200.body.queued_count, 1);
  } finally {
    harness.cleanup();
  }
});

test('dispatcher: takeover endpoint returns 200 with discarded IDs and ONLY takeover calls takeoverChannel (T13, L4)', { timeout: 5000 }, (t) => {
  const harness = createTempHarness();
  try {
    let takeoverCount = 0;
    const originalTakeover = harness.repo.takeoverChannel;
    t.mock.method(harness.repo, 'takeoverChannel', function (...args) {
      takeoverCount++;
      return originalTakeover.apply(harness.repo, args);
    });

    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });

    // 1. First takeover
    const res1 = dispatcher.dispatch('/v1/takeover', { channel_id: 'tg:c1', holder_id: 'holder_a' });
    assert.equal(res1.status, 200);
    assert.equal(res1.body.fencing_token, 1);
    assert.equal(res1.body.previous_holder, null);
    assert.deepEqual(res1.body.discarded_message_ids, []);
    assert.equal(takeoverCount, 1);

    // Seed claimed message under holder_a
    harness.seedInbox('tg:c1', 'msg_claimed', 'claimed', { claimedBy: 'holder_a', claimedAtToken: 1 });

    // 2. Second takeover by holder_b discards msg_claimed
    const res2 = dispatcher.dispatch('/v1/takeover', { channel_id: 'tg:c1', holder_id: 'holder_b' });
    assert.equal(res2.status, 200);
    assert.equal(res2.body.fencing_token, 2);
    assert.equal(res2.body.previous_holder, 'holder_a');
    assert.deepEqual(res2.body.discarded_message_ids, ['msg_claimed']);
    assert.equal(takeoverCount, 2);

    // Negative tests: poll and heartbeat MUST NOT call takeoverChannel (L4, T13)
    dispatcher.dispatch('/v1/poll', { channel_id: 'tg:c1', holder_id: 'holder_b', fencing_token: 2, limit: 10 });
    assert.equal(takeoverCount, 2, 'poll MUST NOT implicitly call takeoverChannel');

    dispatcher.dispatch('/v1/heartbeat', { channel_id: 'tg:c1', holder_id: 'holder_b', fencing_token: 2 });
    assert.equal(takeoverCount, 2, 'heartbeat MUST NOT implicitly call takeoverChannel');
  } finally {
    harness.cleanup();
  }
});

test('dispatcher: synchronous poll critical section A (existing=50, claimMessages not called) (T23)', { timeout: 5000 }, (t) => {
  const harness = createTempHarness();
  try {
    harness.repo.takeoverChannel('tg:c50', 'holder_50');

    // Seed 50 claimed messages
    for (let i = 1; i <= 50; i++) {
      harness.seedInbox('tg:c50', `c_${i}`, 'claimed', {
        claimedBy: 'holder_50',
        claimedAtToken: 1,
        content: `Content ${i}`,
      });
    }
    // Seed 2 queued messages
    harness.seedInbox('tg:c50', 'q_1', 'queued');
    harness.seedInbox('tg:c50', 'q_2', 'queued');

    let claimMessagesCalled = 0;
    const origClaim = harness.repo.claimMessages;
    t.mock.method(harness.repo, 'claimMessages', function (...args) {
      claimMessagesCalled++;
      return origClaim.apply(harness.repo, args);
    });

    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });
    const res = dispatcher.dispatch('/v1/poll', {
      channel_id: 'tg:c50',
      holder_id: 'holder_50',
      fencing_token: 1,
      limit: 50,
    });

    assert.equal(res.status, 200);
    assert.equal(claimMessagesCalled, 0, 'claimMessages must NOT be called when existing = 50');
    assert.equal(res.body.messages.length, 50);

    // Verify queued count unchanged
    const state = harness.repo.getChannelState('tg:c50');
    assert.equal(state.backlogCount, 2);
  } finally {
    harness.cleanup();
  }
});

test('dispatcher: synchronous poll critical section B (existing=49, claims exactly 1) (T23)', { timeout: 5000 }, (t) => {
  const harness = createTempHarness();
  try {
    harness.repo.takeoverChannel('tg:c49', 'holder_49');

    // Seed 49 claimed messages
    for (let i = 1; i <= 49; i++) {
      harness.seedInbox('tg:c49', `c_${i}`, 'claimed', {
        claimedBy: 'holder_49',
        claimedAtToken: 1,
        content: `Content ${i}`,
      });
    }
    // Seed 2 queued messages
    harness.seedInbox('tg:c49', 'q_1', 'queued', { content: 'Queued 1' });
    harness.seedInbox('tg:c49', 'q_2', 'queued', { content: 'Queued 2' });

    let claimLimitPassed = null;
    const origClaim = harness.repo.claimMessages;
    t.mock.method(harness.repo, 'claimMessages', function (c, h, f, lim) {
      claimLimitPassed = lim;
      return origClaim.call(harness.repo, c, h, f, lim);
    });

    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });
    const res = dispatcher.dispatch('/v1/poll', {
      channel_id: 'tg:c49',
      holder_id: 'holder_49',
      fencing_token: 1,
      limit: 10,
    });

    assert.equal(res.status, 200);
    assert.equal(claimLimitPassed, 1, 'claimMessages must receive claimLimit = 1');
    assert.equal(res.body.messages.length, 50);

    // Only 1 new queued row claimed, 1 remains queued
    const state = harness.repo.getChannelState('tg:c49');
    assert.equal(state.backlogCount, 1);
  } finally {
    harness.cleanup();
  }
});

test('dispatcher: synchronous poll critical section C (lost-response retry) (T22)', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    harness.repo.takeoverChannel('tg:c_retry', 'holder_retry');
    harness.seedInbox('tg:c_retry', 'msg_retry_1', 'queued', { content: 'Retriable content 1' });

    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });

    // First poll claims message
    const res1 = dispatcher.dispatch('/v1/poll', {
      channel_id: 'tg:c_retry',
      holder_id: 'holder_retry',
      fencing_token: 1,
      limit: 10,
    });
    assert.equal(res1.status, 200);
    assert.equal(res1.body.messages.length, 1);
    assert.equal(res1.body.messages[0].message_id, 'msg_retry_1');
    assert.equal(res1.body.messages[0].content, 'Retriable content 1');

    // Simulate lost response: second poll with same holder & fencing token returns it again
    const res2 = dispatcher.dispatch('/v1/poll', {
      channel_id: 'tg:c_retry',
      holder_id: 'holder_retry',
      fencing_token: 1,
      limit: 10,
    });
    assert.equal(res2.status, 200);
    assert.equal(res2.body.messages.length, 1);
    assert.equal(res2.body.messages[0].message_id, 'msg_retry_1');
    assert.equal(res2.body.messages[0].content, 'Retriable content 1');
  } finally {
    harness.cleanup();
  }
});

test('dispatcher: synchronous poll critical section D (concurrent / sequential requests capped at 50)', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    harness.repo.takeoverChannel('tg:c_conc', 'holder_conc');

    // 49 claimed
    for (let i = 1; i <= 49; i++) {
      harness.seedInbox('tg:c_conc', `c_${i}`, 'claimed', {
        claimedBy: 'holder_conc',
        claimedAtToken: 1,
      });
    }
    // 3 queued
    harness.seedInbox('tg:c_conc', 'q_1', 'queued');
    harness.seedInbox('tg:c_conc', 'q_2', 'queued');
    harness.seedInbox('tg:c_conc', 'q_3', 'queued');

    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });

    // Two poll requests for same holder/token
    const resA = dispatcher.dispatch('/v1/poll', { channel_id: 'tg:c_conc', holder_id: 'holder_conc', fencing_token: 1, limit: 5 });
    const resB = dispatcher.dispatch('/v1/poll', { channel_id: 'tg:c_conc', holder_id: 'holder_conc', fencing_token: 1, limit: 5 });

    assert.equal(resA.status, 200);
    assert.equal(resA.body.messages.length, 50);

    assert.equal(resB.status, 200);
    assert.equal(resB.body.messages.length, 50);

    const state = harness.repo.getChannelState('tg:c_conc');
    assert.equal(state.backlogCount, 2, '2 queued rows beyond capacity MUST remain queued');
  } finally {
    harness.cleanup();
  }
});

test('dispatcher: heartbeat endpoint returns 200 on match and 409 on holder/token mismatch with no forbidden details', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    harness.repo.takeoverChannel('tg:hb', 'holder_hb');
    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });

    // Valid heartbeat
    const resOk = dispatcher.dispatch('/v1/heartbeat', {
      channel_id: 'tg:hb',
      holder_id: 'holder_hb',
      fencing_token: 1,
    });
    assert.deepEqual(resOk, { status: 200, body: { ok: true, code: 'OK' } });

    // Wrong holder
    const resHolderMis = dispatcher.dispatch('/v1/heartbeat', {
      channel_id: 'tg:hb',
      holder_id: 'wrong_holder',
      fencing_token: 1,
    });
    assert.deepEqual(resHolderMis, { status: 409, body: { ok: false, code: 'HOLDER_MISMATCH' } });
    assert.equal('currentHolder' in resHolderMis.body, false);

    // Stale token
    const resStaleTok = dispatcher.dispatch('/v1/heartbeat', {
      channel_id: 'tg:hb',
      holder_id: 'holder_hb',
      fencing_token: 0,
    });
    assert.deepEqual(resStaleTok, { status: 409, body: { ok: false, code: 'STALE_FENCING_TOKEN' } });
    assert.equal('expectedToken' in resStaleTok.body, false);
    assert.equal('receivedToken' in resStaleTok.body, false);
  } finally {
    harness.cleanup();
  }
});

test('dispatcher: reply endpoint returns 403 on whitelisted denial reasons and 501 OUTBOUND_NOT_READY when authorized (T14)', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    harness.repo.takeoverChannel('tg:reply', 'holder_rep');
    harness.seedInbox('tg:reply', 'msg_rep_1', 'claimed', {
      claimedBy: 'holder_rep',
      claimedAtToken: 1,
      accountId: 'acc_rep',
    });

    const dispatcher = new LocalApiDispatcher({ repository: harness.repo });

    // Message not found -> 403 MESSAGE_NOT_FOUND
    const resNotFound = dispatcher.dispatch('/v1/reply', {
      client_request_id: 'req_1',
      channel_id: 'tg:reply',
      holder_id: 'holder_rep',
      fencing_token: 1,
      message_id: 'non_existent_msg',
      replying_account_id: 'acc_rep',
      text: 'hello',
    });
    assert.deepEqual(resNotFound, {
      status: 403,
      body: { ok: false, code: 'REPLY_NOT_AUTHORIZED', reason: 'MESSAGE_NOT_FOUND' },
    });

    // Valid reply authorization -> 501 OUTBOUND_NOT_READY (TG-MVP-11 boundary, T14)
    const res501 = dispatcher.dispatch('/v1/reply', {
      client_request_id: 'req_2',
      channel_id: 'tg:reply',
      holder_id: 'holder_rep',
      fencing_token: 1,
      message_id: 'msg_rep_1',
      replying_account_id: 'acc_rep',
      text: 'Valid reply text',
    });
    assert.deepEqual(res501, {
      status: 501,
      body: { ok: false, code: 'OUTBOUND_NOT_READY' },
    });
  } finally {
    harness.cleanup();
  }
});
