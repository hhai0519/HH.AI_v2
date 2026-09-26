/**
 * runtime/channel-gateway/tests/sqlite-channel-transactions.test.js
 *
 * ADR-0023 / E-03 T7B: Channel Gateway Core Durable Channel Transactions Test Suite.
 *
 * Verifies:
 * 1. Explicit channel takeover (first takeover, sequential takeover, same-holder re-takeover).
 * 2. Takeover discards claimed unreplied messages with TAKEOVER reason, preserving queued backlog.
 * 3. Heartbeat renewal succeeds on matching holder and token; cannot implicitly takeover.
 * 4. Heartbeat rejects stale token or holder mismatch without mutation.
 * 5. Heartbeat expiry clears holder, discards claimed messages with HEARTBEAT_EXPIRY reason, preserves queued, does not increment token.
 * 6. Repeated expiry on expired channel returns NO_ACTIVE_HOLDER with zero mutation.
 * 7. FIFO claim order (sequence ASC), limit validation, and atomicity.
 * 8. Claim rejected for non-holder or stale token without mutation.
 * 9. Read-only validateReplyAuthorization matrix: all failure modes + zero DB mutation on authorized.
 * 10. Deterministic transaction rollback on failure (takeover and claim via temporary abort triggers).
 * 11. Multi-connection durable fencing canary (cross-connection stale holder/token rejection).
 * 12. Restart persistence: channel state and inbox survive repo close and reopen.
 * 13. getChannelState read-only inspection contract.
 * 14. Architectural boundary and semantic canaries (CANARY 1 - 24).
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { DatabaseSync } = require('node:sqlite');

const {
  SqliteStateRepository,
  SQLITE_STATE_SCHEMA_VERSION,
} = require('../core/sqlite-state-repository');
const { computeCanonicalPayloadHash } = require('../core/outbox-delivery-policy');

function createTempHarness() {
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-sqlite-tx-test-'));
  const stateRoot = path.join(baseDir, 'state');
  fs.mkdirSync(stateRoot, { recursive: true });

  function cleanup() {
    try {
      fs.rmSync(baseDir, { recursive: true, force: true });
    } catch {
      // ignore cleanup errors
    }
  }

  return {
    baseDir,
    stateRoot,
    cleanup,
  };
}

/**
 * Synthetic helper to seed messages into inbox via a separate connection,
 * respecting the strict boundary that no production enqueue API exists in T7B.
 */
function seedInboxMessage(
  databasePath,
  channelId,
  messageId,
  receivingAccountId = 'acc_default',
  status = 'queued',
  extra = {}
) {
  const rawDb = new DatabaseSync(databasePath);
  try {
    const stmt = rawDb.prepare(
      `INSERT INTO inbox (
        channel_id, account_id, platform_msg_id, status, content,
        claimed_by, claimed_at_token, discard_reason, discarded_by_holder, discarded_at_token
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);`
    );
    stmt.run(
      channelId,
      receivingAccountId,
      String(messageId),
      status,
      extra.content ?? null,
      extra.claimedBy ?? null,
      extra.claimedAtToken ?? null,
      extra.discardReason ?? null,
      extra.discardedByHolder ?? null,
      extra.discardedAtToken ?? null
    );
  } finally {
    rawDb.close();
  }
}

// 1. First takeover establishes holder with fencing token 1 (CANARY 2, 3)
test('SqliteChannelTransactions - 1. first takeover establishes holder and token 1', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      const res = repo.takeoverChannel('line:group:100', 'holder_alpha', { timestamp: 1700000000 });
      assert.strictEqual(res.success, true);
      assert.strictEqual(res.channelId, 'line:group:100');
      assert.strictEqual(res.holder, 'holder_alpha');
      assert.strictEqual(res.fencingToken, 1);
      assert.strictEqual(res.previousHolder, null);
      assert.deepStrictEqual(res.discardedMessages, []);
      assert.strictEqual(res.backlogCount, 0);

      const state = repo.getChannelState('line:group:100');
      assert.deepStrictEqual(state, {
        channelId: 'line:group:100',
        currentHolder: 'holder_alpha',
        fencingToken: 1,
        lastHeartbeatAt: 1700000000,
        backlogCount: 0,
      });
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 2. Sequential takeover increments token and records previousHolder (CANARY 3)
test('SqliteChannelTransactions - 2. sequential takeover increments token and records previousHolder', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');
      const res2 = repo.takeoverChannel('line:group:100', 'holder_beta', { timestamp: 1700001000 });

      assert.strictEqual(res2.success, true);
      assert.strictEqual(res2.holder, 'holder_beta');
      assert.strictEqual(res2.fencingToken, 2);
      assert.strictEqual(res2.previousHolder, 'holder_alpha');

      // Re-takeover by same holder also increments fencing token
      const res3 = repo.takeoverChannel('line:group:100', 'holder_beta', { timestamp: 1700002000 });
      assert.strictEqual(res3.success, true);
      assert.strictEqual(res3.holder, 'holder_beta');
      assert.strictEqual(res3.fencingToken, 3);
      assert.strictEqual(res3.previousHolder, 'holder_beta');
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 3. Takeover discards claimed messages and preserves queued backlog (CANARY 4)
test('SqliteChannelTransactions - 3. takeover discards claimed messages with TAKEOVER reason and preserves queued', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');

      // Seed 3 messages: msg1, msg2, msg3
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_1', 'acc_1');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_2', 'acc_1');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_3', 'acc_1');

      // Claim msg_1 and msg_2 with holder_alpha at token 1
      const claimRes = repo.claimMessages('line:group:100', 'holder_alpha', 1, 2);
      assert.strictEqual(claimRes.claimedMessages.length, 2);

      // Now holder_beta takes over
      const takeoverRes = repo.takeoverChannel('line:group:100', 'holder_beta');
      assert.strictEqual(takeoverRes.success, true);
      assert.strictEqual(takeoverRes.fencingToken, 2);
      assert.strictEqual(takeoverRes.discardedMessages.length, 2);

      // Verify discarded messages audit fields
      const d1 = takeoverRes.discardedMessages[0];
      assert.strictEqual(d1.messageId, 'msg_1');
      assert.strictEqual(d1.status, 'discarded');
      assert.strictEqual(d1.discardReason, 'TAKEOVER');
      assert.strictEqual(d1.claimedBy, 'holder_alpha');
      assert.strictEqual(d1.claimedAtToken, 1);

      const d2 = takeoverRes.discardedMessages[1];
      assert.strictEqual(d2.messageId, 'msg_2');
      assert.strictEqual(d2.status, 'discarded');
      assert.strictEqual(d2.discardReason, 'TAKEOVER');

      // Queued msg_3 is preserved!
      assert.strictEqual(takeoverRes.backlogCount, 1);

      // Verify directly from DB
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const rows = rawDb.prepare('SELECT platform_msg_id, status, discard_reason, discarded_by_holder, discarded_at_token FROM inbox ORDER BY sequence ASC;').all();
        assert.strictEqual(rows.length, 3);
        assert.strictEqual(rows[0].status, 'discarded');
        assert.strictEqual(rows[0].discard_reason, 'TAKEOVER');
        assert.strictEqual(rows[0].discarded_by_holder, 'holder_beta');
        assert.strictEqual(rows[0].discarded_at_token, 2);

        assert.strictEqual(rows[1].status, 'discarded');
        assert.strictEqual(rows[1].discard_reason, 'TAKEOVER');

        assert.strictEqual(rows[2].status, 'queued');
        assert.strictEqual(rows[2].discard_reason, null);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 4. Heartbeat renewal contract: success on match, cannot implicit takeover (CANARY 5)
test('SqliteChannelTransactions - 4. heartbeat updates timestamp, cannot takeover on absent or mismatch', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      // 1. Heartbeat on non-existent channel returns HOLDER_MISMATCH with zero creation
      const hbAbsent = repo.heartbeatChannel('line:group:nonexistent', 'holder_alpha', 1);
      assert.strictEqual(hbAbsent.success, false);
      assert.strictEqual(hbAbsent.reason, 'HOLDER_MISMATCH');
      assert.strictEqual(hbAbsent.currentHolder, null);

      assert.strictEqual(repo.getChannelState('line:group:nonexistent'), null);

      // 2. Establish holder
      repo.takeoverChannel('line:group:100', 'holder_alpha');

      // 3. Successful heartbeat
      const hbSuccess = repo.heartbeatChannel('line:group:100', 'holder_alpha', 1, { timestamp: 1700050000 });
      assert.strictEqual(hbSuccess.success, true);
      assert.strictEqual(hbSuccess.holder, 'holder_alpha');
      assert.strictEqual(hbSuccess.fencingToken, 1);
      assert.strictEqual(hbSuccess.lastHeartbeatAt, 1700050000);

      // Verify timestamp updated
      const state = repo.getChannelState('line:group:100');
      assert.strictEqual(state.lastHeartbeatAt, 1700050000);

      // 4. Heartbeat with wrong holder rejected without mutation
      const hbWrongHolder = repo.heartbeatChannel('line:group:100', 'holder_imposter', 1, { timestamp: 1700099999 });
      assert.strictEqual(hbWrongHolder.success, false);
      assert.strictEqual(hbWrongHolder.reason, 'HOLDER_MISMATCH');
      assert.strictEqual(hbWrongHolder.currentHolder, 'holder_alpha');

      // Timestamp remained unchanged
      assert.strictEqual(repo.getChannelState('line:group:100').lastHeartbeatAt, 1700050000);

      // 5. Heartbeat with stale token rejected without mutation
      const hbStaleToken = repo.heartbeatChannel('line:group:100', 'holder_alpha', 99, { timestamp: 1700099999 });
      assert.strictEqual(hbStaleToken.success, false);
      assert.strictEqual(hbStaleToken.reason, 'STALE_FENCING_TOKEN');
      assert.strictEqual(hbStaleToken.expectedToken, 1);
      assert.strictEqual(hbStaleToken.receivedToken, 99);

      assert.strictEqual(repo.getChannelState('line:group:100').lastHeartbeatAt, 1700050000);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 5. Expiry clears holder and heartbeat, discards claimed messages, does not increment token (CANARY 6)
test('SqliteChannelTransactions - 5. heartbeat expiry clears holder, discards claimed with HEARTBEAT_EXPIRY, preserves queued', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_1', 'acc_1');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_2', 'acc_1');

      // Claim msg_1
      repo.claimMessages('line:group:100', 'holder_alpha', 1, 1);

      // Expire holder
      const expRes = repo.expireChannelHolder('line:group:100');
      assert.strictEqual(expRes.success, true);
      assert.strictEqual(expRes.expiredHolder, 'holder_alpha');
      assert.strictEqual(expRes.fencingToken, 1); // Token is NOT incremented!
      assert.strictEqual(expRes.discardedMessages.length, 1);
      assert.strictEqual(expRes.discardedMessages[0].messageId, 'msg_1');
      assert.strictEqual(expRes.discardedMessages[0].discardReason, 'HEARTBEAT_EXPIRY');
      assert.strictEqual(expRes.backlogCount, 1); // msg_2 remains queued

      // Check state
      const state = repo.getChannelState('line:group:100');
      assert.strictEqual(state.currentHolder, null);
      assert.strictEqual(state.lastHeartbeatAt, null);
      assert.strictEqual(state.fencingToken, 1);
      assert.strictEqual(state.backlogCount, 1);

      // Repeated expiry returns NO_ACTIVE_HOLDER
      const expAgain = repo.expireChannelHolder('line:group:100');
      assert.strictEqual(expAgain.success, false);
      assert.strictEqual(expAgain.reason, 'NO_ACTIVE_HOLDER');

      // Alias expireHolder works identically
      assert.strictEqual(repo.expireHolder('line:group:100').reason, 'NO_ACTIVE_HOLDER');
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 6. FIFO message claim order, limit enforcement, and backlog counting (CANARY 8, 9, 10)
test('SqliteChannelTransactions - 6. FIFO claim by sequence, limit enforcement, and backlog counting', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');

      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_seq_10', 'acc_1');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_seq_20', 'acc_1');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_seq_30', 'acc_1');

      // Claim limit = 1 -> should receive only msg_seq_10
      const c1 = repo.claimMessages('line:group:100', 'holder_alpha', 1, 1);
      assert.strictEqual(c1.success, true);
      assert.strictEqual(c1.claimedMessages.length, 1);
      assert.strictEqual(c1.claimedMessages[0].messageId, 'msg_seq_10');
      assert.strictEqual(c1.claimedMessages[0].status, 'claimed');
      assert.strictEqual(c1.claimedMessages[0].claimedBy, 'holder_alpha');
      assert.strictEqual(c1.claimedMessages[0].claimedAtToken, 1);
      assert.strictEqual(c1.remainingBacklogCount, 2);

      // Claim limit = 5 -> should receive remaining 2 messages in sequence ASC
      const c2 = repo.claimMessages('line:group:100', 'holder_alpha', 1, 5);
      assert.strictEqual(c2.success, true);
      assert.strictEqual(c2.claimedMessages.length, 2);
      assert.strictEqual(c2.claimedMessages[0].messageId, 'msg_seq_20');
      assert.strictEqual(c2.claimedMessages[1].messageId, 'msg_seq_30');
      assert.strictEqual(c2.remainingBacklogCount, 0);

      // Claim when empty backlog returns empty list
      const c3 = repo.claimMessages('line:group:100', 'holder_alpha', 1, 10);
      assert.strictEqual(c3.success, true);
      assert.strictEqual(c3.claimedMessages.length, 0);
      assert.strictEqual(c3.remainingBacklogCount, 0);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 7. Claim limit validation: positive safe integer only, no unbounded default (CANARY 10)
test('SqliteChannelTransactions - 7. claim limit must be positive safe integer', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');

      const invalidLimits = [0, -1, -100, 1.5, NaN, Infinity, -Infinity, '1', null, undefined, {}];
      for (const lim of invalidLimits) {
        assert.throws(
          () => repo.claimMessages('line:group:100', 'holder_alpha', 1, lim),
          /positive safe integer/i,
          `Limit ${String(lim)} must throw`
        );
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 8. Claim rejects non-holder or stale token without mutation (CANARY 7, 8)
test('SqliteChannelTransactions - 8. claim rejects non-holder or stale token without mutation', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_1', 'acc_1');

      // Wrong holder
      const resWrongHolder = repo.claimMessages('line:group:100', 'holder_imposter', 1, 10);
      assert.strictEqual(resWrongHolder.success, false);
      assert.strictEqual(resWrongHolder.reason, 'NOT_CURRENT_HOLDER');
      assert.deepStrictEqual(resWrongHolder.claimedMessages, []);

      // Stale token
      const resStaleToken = repo.claimMessages('line:group:100', 'holder_alpha', 0, 10);
      assert.strictEqual(resStaleToken.success, false);
      assert.strictEqual(resStaleToken.reason, 'STALE_FENCING_TOKEN');
      assert.deepStrictEqual(resStaleToken.claimedMessages, []);

      // Message is still queued
      assert.strictEqual(repo.getChannelState('line:group:100').backlogCount, 1);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 9. Read-only reply authorization validation matrix (CANARY 14, 15, 16)
test('SqliteChannelTransactions - 9. validateReplyAuthorization matrix: zero DB mutation and complete rejection paths', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');

      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_claimed', 'acc_line_1');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_queued', 'acc_line_1');

      repo.claimMessages('line:group:100', 'holder_alpha', 1, 1); // claims msg_claimed

      // A. NOT_CURRENT_HOLDER
      const r1 = repo.validateReplyAuthorization('line:group:100', 'holder_other', 1, 'msg_claimed', 'acc_line_1');
      assert.strictEqual(r1.authorized, false);
      assert.strictEqual(r1.reason, 'NOT_CURRENT_HOLDER');

      // B. STALE_FENCING_TOKEN
      const r2 = repo.validateReplyAuthorization('line:group:100', 'holder_alpha', 2, 'msg_claimed', 'acc_line_1');
      assert.strictEqual(r2.authorized, false);
      assert.strictEqual(r2.reason, 'STALE_FENCING_TOKEN');

      // C. MESSAGE_NOT_FOUND
      const r3 = repo.validateReplyAuthorization('line:group:100', 'holder_alpha', 1, 'msg_nonexistent', 'acc_line_1');
      assert.strictEqual(r3.authorized, false);
      assert.strictEqual(r3.reason, 'MESSAGE_NOT_FOUND');

      // D. MESSAGE_NOT_CLAIMED (status = queued)
      const r4 = repo.validateReplyAuthorization('line:group:100', 'holder_alpha', 1, 'msg_queued', 'acc_line_1');
      assert.strictEqual(r4.authorized, false);
      assert.strictEqual(r4.reason, 'MESSAGE_NOT_CLAIMED');
      assert.strictEqual(r4.status, 'queued');

      // E. ACCOUNT_MISMATCH
      const r5 = repo.validateReplyAuthorization('line:group:100', 'holder_alpha', 1, 'msg_claimed', 'acc_wrong');
      assert.strictEqual(r5.authorized, false);
      assert.strictEqual(r5.reason, 'ACCOUNT_MISMATCH');

      // F. SUCCESS
      const rSuccess = repo.validateReplyAuthorization('line:group:100', 'holder_alpha', 1, 'msg_claimed', 'acc_line_1');
      assert.strictEqual(rSuccess.authorized, true);
      assert.strictEqual(rSuccess.messageId, 'msg_claimed');
      assert.strictEqual(rSuccess.channelId, 'line:group:100');
      assert.strictEqual(rSuccess.receivingAccountId, 'acc_line_1');
      assert.strictEqual(rSuccess.replyingAccountId, 'acc_line_1');

      // CANARY 14, 15: Zero side-effect verification: msg_claimed must STILL be 'claimed' in SQLite!
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const msgRow = rawDb.prepare("SELECT status FROM inbox WHERE platform_msg_id = 'msg_claimed';").get();
        assert.strictEqual(msgRow.status, 'claimed', 'Successful authorization MUST NOT mutate inbox status to replied');
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 10. Deterministic rollback on takeover failure via temporary abort trigger (CANARY 1, 11)
test('SqliteChannelTransactions - 10. takeover failure triggers full rollback without partial mutation', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_1', 'acc_1');
      repo.claimMessages('line:group:100', 'holder_alpha', 1, 1); // msg_1 claimed

      // Inject temporary test trigger on the live connection via private raw handle or second connection?
      // Notice: temporary triggers are connection-scoped. Since repo has private #db, can we create
      // a trigger on the table via a second connection or temp trigger?
      // In SQLite, a trigger created in schema_migrations or on the database schema affects all connections!
      const schemaDb = new DatabaseSync(repo.databasePath);
      try {
        schemaDb.exec(
          "CREATE TRIGGER test_abort_takeover_update BEFORE UPDATE ON inbox WHEN NEW.discard_reason = 'TAKEOVER' BEGIN SELECT RAISE(ABORT, 'forced test abort on takeover discard'); END;"
        );
      } finally {
        schemaDb.close();
      }

      // Now repo.takeoverChannel to holder_beta MUST throw due to trigger aborting inbox update
      assert.throws(
        () => repo.takeoverChannel('line:group:100', 'holder_beta'),
        /forced test abort on takeover discard/
      );

      // Verify that channel_control was ALSO rolled back and is NOT holder_beta!
      const state = repo.getChannelState('line:group:100');
      assert.strictEqual(state.currentHolder, 'holder_alpha', 'channel_control must be rolled back on takeover failure');
      assert.strictEqual(state.fencingToken, 1, 'fencing_token must remain 1');

      // Verify inbox msg_1 is STILL claimed and was NOT partially discarded
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const row = rawDb.prepare("SELECT status, discard_reason FROM inbox WHERE platform_msg_id = 'msg_1';").get();
        assert.strictEqual(row.status, 'claimed');
        assert.strictEqual(row.discard_reason, null);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 11. Deterministic rollback on claim failure via temporary abort trigger (CANARY 1, 11)
test('SqliteChannelTransactions - 11. claim failure triggers full rollback without partial claim', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_alpha');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_claim_1', 'acc_1');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_claim_2', 'acc_1');

      // Add trigger that aborts specifically on msg_claim_2
      const schemaDb = new DatabaseSync(repo.databasePath);
      try {
        schemaDb.exec(
          "CREATE TRIGGER test_abort_second_claim BEFORE UPDATE OF status ON inbox WHEN NEW.platform_msg_id = 'msg_claim_2' BEGIN SELECT RAISE(ABORT, 'forced test abort on second claim'); END;"
        );
      } finally {
        schemaDb.close();
      }

      // Attempt claimMessages with limit 2: msg_claim_1 would update first, then msg_claim_2 aborts
      assert.throws(
        () => repo.claimMessages('line:group:100', 'holder_alpha', 1, 2),
        /forced test abort on second claim/
      );

      // Re-read inbox: BOTH messages must still be 'queued'! Zero partial claims
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const rows = rawDb.prepare('SELECT platform_msg_id, status FROM inbox ORDER BY sequence ASC;').all();
        assert.strictEqual(rows.length, 2);
        assert.strictEqual(rows[0].status, 'queued', 'msg_claim_1 must be rolled back to queued');
        assert.strictEqual(rows[1].status, 'queued', 'msg_claim_2 must remain queued');
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 12. Restart persistence: state survives repository close and reopen (CANARY 12)
test('SqliteChannelTransactions - 12. state survives close and reopen from disk', () => {
  const harness = createTempHarness();
  try {
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    repo1.takeoverChannel('tg:chat:999', 'holder_tg', { timestamp: 1700100000 });
    seedInboxMessage(repo1.databasePath, 'tg:chat:999', 'tg_msg_1', 'acc_tg');
    repo1.claimMessages('tg:chat:999', 'holder_tg', 1, 1);
    repo1.close();

    // Reopen repository
    const repo2 = new SqliteStateRepository(harness.stateRoot);
    try {
      const state = repo2.getChannelState('tg:chat:999');
      assert.deepStrictEqual(state, {
        channelId: 'tg:chat:999',
        currentHolder: 'holder_tg',
        fencingToken: 1,
        lastHeartbeatAt: 1700100000,
        backlogCount: 0,
      });

      // Authorization check still works after reopen
      const auth = repo2.validateReplyAuthorization('tg:chat:999', 'holder_tg', 1, 'tg_msg_1', 'acc_tg');
      assert.strictEqual(auth.authorized, true);
    } finally {
      repo2.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 13. Multi-connection durable fencing canary (CANARY 13)
test('SqliteChannelTransactions - 13. multi-connection durable fencing: stale caller rejected', () => {
  const harness = createTempHarness();
  try {
    const repoA = new SqliteStateRepository(harness.stateRoot);
    const repoB = new SqliteStateRepository(harness.stateRoot);
    try {
      // 1. Connection A takes over channel -> token 1
      const tA = repoA.takeoverChannel('line:shared:1', 'holder_A');
      assert.strictEqual(tA.fencingToken, 1);

      seedInboxMessage(repoA.databasePath, 'line:shared:1', 'shared_msg_1', 'acc_1');

      // 2. Connection B takes over channel -> token 2
      const tB = repoB.takeoverChannel('line:shared:1', 'holder_B');
      assert.strictEqual(tB.fencingToken, 2);

      // 3. Stale caller on Connection A with holder_A and token 1 attempts heartbeat
      const hbStale = repoA.heartbeatChannel('line:shared:1', 'holder_A', 1);
      assert.strictEqual(hbStale.success, false);
      assert.strictEqual(hbStale.reason, 'HOLDER_MISMATCH');

      // 4. Stale caller on Connection A with holder_A and token 1 attempts claim
      const claimStale = repoA.claimMessages('line:shared:1', 'holder_A', 1, 1);
      assert.strictEqual(claimStale.success, false);
      assert.strictEqual(claimStale.reason, 'NOT_CURRENT_HOLDER');

      // 5. Active holder B on Connection B successfully claims
      const claimActive = repoB.claimMessages('line:shared:1', 'holder_B', 2, 1);
      assert.strictEqual(claimActive.success, true);
      assert.strictEqual(claimActive.claimedMessages.length, 1);
      assert.strictEqual(claimActive.claimedMessages[0].messageId, 'shared_msg_1');
    } finally {
      repoA.close();
      repoB.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 14. Input contract validations fail-closed before any transaction or mutation
test('SqliteChannelTransactions - 14. input validations fail-closed on invalid parameters', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      // channelId validation
      assert.throws(() => repo.takeoverChannel('', 'holder_A'), /channelId/i);
      assert.throws(() => repo.takeoverChannel('   ', 'holder_A'), /channelId/i);
      assert.throws(() => repo.takeoverChannel(123, 'holder_A'), TypeError);

      // holderId validation
      assert.throws(() => repo.takeoverChannel('ch1', ''), /holderId/i);
      assert.throws(() => repo.takeoverChannel('ch1', null), TypeError);

      // fencingToken validation
      assert.throws(() => repo.heartbeatChannel('ch1', 'holder_A', -1), /fencingToken/i);
      assert.throws(() => repo.heartbeatChannel('ch1', 'holder_A', 1.5), /fencingToken/i);
      assert.throws(() => repo.heartbeatChannel('ch1', 'holder_A', '1'), /fencingToken/i);

      // messageId validation in reply authorization
      assert.throws(() => repo.validateReplyAuthorization('ch1', 'h1', 1, '', 'acc1'), /messageId/i);
      assert.throws(() => repo.validateReplyAuthorization('ch1', 'h1', 1, null, 'acc1'), /messageId/i);

      // replyingAccountId validation
      assert.throws(() => repo.validateReplyAuthorization('ch1', 'h1', 1, 'msg1', ''), /replyingAccountId/i);
      assert.throws(() => repo.validateReplyAuthorization('ch1', 'h1', 1, 'msg1', 123), TypeError);

      // timestamp validation
      assert.throws(() => repo.takeoverChannel('ch1', 'holder_A', { timestamp: -5 }), /timestamp/i);
      assert.throws(() => repo.takeoverChannel('ch1', 'holder_A', { timestamp: 1.2 }), /timestamp/i);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 15. Closed repository rejects all transaction methods fail-closed
test('SqliteChannelTransactions - 15. closed repository rejects all operations fail-closed', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    repo.close();

    assert.throws(() => repo.takeoverChannel('ch1', 'h1'), /closed/i);
    assert.throws(() => repo.heartbeatChannel('ch1', 'h1', 1), /closed/i);
    assert.throws(() => repo.expireChannelHolder('ch1'), /closed/i);
    assert.throws(() => repo.claimMessages('ch1', 'h1', 1, 1), /closed/i);
    assert.throws(() => repo.validateReplyAuthorization('ch1', 'h1', 1, 'm1', 'acc1'), /closed/i);
    assert.throws(() => repo.getChannelState('ch1'), /closed/i);
  } finally {
    harness.cleanup();
  }
});

// 16. Architectural invariants and boundaries (CANARY 17-24)
test('SqliteChannelTransactions - 16. architectural invariants: schema version 7, event-ingest boundary, outbox present, no account-switch', () => {
  assert.strictEqual(SQLITE_STATE_SCHEMA_VERSION, 7, 'CANARY 17: schema version must be 7');

  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      assert.strictEqual(repo.schemaVersion, 7, 'CANARY 18: applied schema version is 7');

      // CANARY 19: Authorized ingress in T8B / TG-MVP-10; arbitrary other ingress remains absent
      assert.strictEqual(typeof repo.ingestMessage, 'function');
      assert.strictEqual(typeof repo.recordIgnoredEvent, 'function');
      assert.strictEqual(typeof repo.ingestEdit, 'function');
      assert.strictEqual(repo.enqueueMessage, undefined);
      assert.strictEqual(repo.receiveMessage, undefined);
      assert.strictEqual(repo.insertInboundMessage, undefined);

      // CANARY 20: No account-switch mutation
      assert.strictEqual(repo.discardQueuedForAccount, undefined);

      // CANARY 21: Outbox methods present
      assert.strictEqual(typeof repo.enqueueAuthorizedReply, 'function');
      assert.strictEqual(typeof repo.getUncertainSummaries, 'function');

      // CANARY 22: R2 safe - no reply mutation completion without atomic outbox
      assert.strictEqual(repo.authorizeReply, undefined);

      // CANARY 23: ingest_cursor, inbound_event, and outbox tables exist
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const tRows = rawDb.prepare("SELECT name FROM sqlite_schema WHERE type = 'table';").all();
        const tNames = tRows.map((r) => r.name);
        assert.strictEqual(tNames.includes('ingest_cursor'), true);
        assert.strictEqual(tNames.includes('inbound_event'), true);
        assert.strictEqual(tNames.includes('outbox'), true);

        // CANARY 10: MIGRATIONS remain [1, 2, 3, 4, 5, 6, 7]
        const mRows = rawDb.prepare('SELECT version FROM schema_migrations ORDER BY version ASC;').all();
        assert.deepStrictEqual(mRows.map((r) => r.version), [1, 2, 3, 4, 5, 6, 7]);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 17. Reply authorization rejects claimed_by mismatch with CLAIM_MISMATCH (CANARY 1, 4)
test('SqliteChannelTransactions - 17. reply authorization rejects claimed_by mismatch with CLAIM_MISMATCH (CANARY 1, 4)', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_A');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_mismatch_holder', 'acc_1', 'claimed', {
        claimedBy: 'holder_other',
        claimedAtToken: 1,
      });

      const res = repo.validateReplyAuthorization('line:group:100', 'holder_A', 1, 'msg_mismatch_holder', 'acc_1');
      assert.strictEqual(res.authorized, false);
      assert.strictEqual(res.reason, 'CLAIM_MISMATCH');

      // Verify DB row was NOT mutated (CANARY 4: read-only)
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const row = rawDb.prepare("SELECT status, claimed_by, claimed_at_token FROM inbox WHERE platform_msg_id = 'msg_mismatch_holder';").get();
        assert.strictEqual(row.status, 'claimed');
        assert.strictEqual(row.claimed_by, 'holder_other');
        assert.strictEqual(row.claimed_at_token, 1);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 18. Reply authorization rejects claimed_at_token mismatch with CLAIM_MISMATCH (CANARY 2, 4)
test('SqliteChannelTransactions - 18. reply authorization rejects claimed_at_token mismatch with CLAIM_MISMATCH (CANARY 2, 4)', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_A');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_mismatch_token', 'acc_1', 'claimed', {
        claimedBy: 'holder_A',
        claimedAtToken: 0,
      });

      const res = repo.validateReplyAuthorization('line:group:100', 'holder_A', 1, 'msg_mismatch_token', 'acc_1');
      assert.strictEqual(res.authorized, false);
      assert.strictEqual(res.reason, 'CLAIM_MISMATCH');

      // Verify DB row was NOT mutated (CANARY 4: read-only)
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const row = rawDb.prepare("SELECT status, claimed_by, claimed_at_token FROM inbox WHERE platform_msg_id = 'msg_mismatch_token';").get();
        assert.strictEqual(row.status, 'claimed');
        assert.strictEqual(row.claimed_by, 'holder_A');
        assert.strictEqual(row.claimed_at_token, 0);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 19. Reply authorization rejects discarded message with MESSAGE_NOT_CLAIMED (CANARY 3, 4)
test('SqliteChannelTransactions - 19. reply authorization rejects discarded message with MESSAGE_NOT_CLAIMED (CANARY 3, 4)', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_A');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_discarded', 'acc_1', 'discarded', {
        discardReason: 'HEARTBEAT_EXPIRY',
        discardedByHolder: 'holder_A',
        discardedAtToken: 1,
      });

      const res = repo.validateReplyAuthorization('line:group:100', 'holder_A', 1, 'msg_discarded', 'acc_1');
      assert.strictEqual(res.authorized, false);
      assert.strictEqual(res.reason, 'MESSAGE_NOT_CLAIMED');
      assert.strictEqual(res.status, 'discarded');

      // Verify DB row was NOT mutated (CANARY 4: read-only)
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const row = rawDb.prepare("SELECT status, discard_reason FROM inbox WHERE platform_msg_id = 'msg_discarded';").get();
        assert.strictEqual(row.status, 'discarded');
        assert.strictEqual(row.discard_reason, 'HEARTBEAT_EXPIRY');
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 20. Heartbeat timestamp survives repository restart (CANARY 5)
test('SqliteChannelTransactions - 20. heartbeat timestamp survives repository restart (CANARY 5)', () => {
  const harness = createTempHarness();
  try {
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    repo1.takeoverChannel('line:group:100', 'holder_alpha', { timestamp: 1700000000 });
    const hbRes = repo1.heartbeatChannel('line:group:100', 'holder_alpha', 1, { timestamp: 1700055555 });
    assert.strictEqual(hbRes.success, true);
    assert.strictEqual(hbRes.lastHeartbeatAt, 1700055555);
    repo1.close();

    // Reopen repository
    const repo2 = new SqliteStateRepository(harness.stateRoot);
    try {
      const state = repo2.getChannelState('line:group:100');
      assert.deepStrictEqual(state, {
        channelId: 'line:group:100',
        currentHolder: 'holder_alpha',
        fencingToken: 1,
        lastHeartbeatAt: 1700055555,
        backlogCount: 0,
      });
    } finally {
      repo2.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 21. Expiry state, discarded claimed rows, and queued backlog survive restart (CANARY 6, 7)
test('SqliteChannelTransactions - 21. expiry state, discarded claimed rows, and queued backlog survive restart (CANARY 6, 7)', () => {
  const harness = createTempHarness();
  try {
    const repo1 = new SqliteStateRepository(harness.stateRoot);
    repo1.takeoverChannel('line:group:100', 'holder_alpha');
    seedInboxMessage(repo1.databasePath, 'line:group:100', 'msg_claimed_1', 'acc_1');
    seedInboxMessage(repo1.databasePath, 'line:group:100', 'msg_queued_1', 'acc_1');

    // Claim msg_claimed_1
    const claimRes = repo1.claimMessages('line:group:100', 'holder_alpha', 1, 1);
    assert.strictEqual(claimRes.claimedMessages.length, 1);

    // Expire holder
    const expRes = repo1.expireChannelHolder('line:group:100');
    assert.strictEqual(expRes.success, true);
    assert.strictEqual(expRes.expiredHolder, 'holder_alpha');
    assert.strictEqual(expRes.fencingToken, 1);
    assert.strictEqual(expRes.backlogCount, 1);
    repo1.close();

    // Reopen repository
    const repo2 = new SqliteStateRepository(harness.stateRoot);
    try {
      const state = repo2.getChannelState('line:group:100');
      assert.deepStrictEqual(state, {
        channelId: 'line:group:100',
        currentHolder: null,
        fencingToken: 1,
        lastHeartbeatAt: null,
        backlogCount: 1,
      });

      // Read-only DB verify
      const rawDb = new DatabaseSync(repo2.databasePath, { readOnly: true });
      try {
        const rows = rawDb.prepare('SELECT platform_msg_id, status, discard_reason, discarded_by_holder, discarded_at_token FROM inbox ORDER BY sequence ASC;').all();
        assert.strictEqual(rows.length, 2);
        assert.strictEqual(rows[0].platform_msg_id, 'msg_claimed_1');
        assert.strictEqual(rows[0].status, 'discarded');
        assert.strictEqual(rows[0].discard_reason, 'HEARTBEAT_EXPIRY');
        assert.strictEqual(rows[0].discarded_by_holder, 'holder_alpha');
        assert.strictEqual(rows[0].discarded_at_token, 1);

        assert.strictEqual(rows[1].platform_msg_id, 'msg_queued_1');
        assert.strictEqual(rows[1].status, 'queued');
        assert.strictEqual(rows[1].discard_reason, null);
      } finally {
        rawDb.close();
      }
    } finally {
      repo2.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 22. Takeover and expiry preserve already-discarded and replied rows (CANARY 8)
test('SqliteChannelTransactions - 22. takeover and expiry preserve already-discarded and replied rows (CANARY 8)', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:100', 'holder_init');

      // Seed already discarded and replied messages
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_prev_discarded', 'acc_1', 'discarded', {
        discardReason: 'PRIOR_REASON',
        discardedByHolder: 'holder_prev',
        discardedAtToken: 0,
      });
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_already_replied', 'acc_1', 'replied');
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_active_claim', 'acc_1');

      // Claim msg_active_claim
      repo.claimMessages('line:group:100', 'holder_init', 1, 1);

      // 1. Takeover by holder_new
      const toRes = repo.takeoverChannel('line:group:100', 'holder_new');
      assert.strictEqual(toRes.success, true);
      assert.strictEqual(toRes.discardedMessages.length, 1);
      assert.strictEqual(toRes.discardedMessages[0].messageId, 'msg_active_claim');

      // Verify msg_prev_discarded and msg_already_replied were NOT altered
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const dRow = rawDb.prepare("SELECT status, discard_reason, discarded_by_holder, discarded_at_token FROM inbox WHERE platform_msg_id = 'msg_prev_discarded';").get();
        assert.strictEqual(dRow.status, 'discarded');
        assert.strictEqual(dRow.discard_reason, 'PRIOR_REASON');
        assert.strictEqual(dRow.discarded_by_holder, 'holder_prev');
        assert.strictEqual(dRow.discarded_at_token, 0);

        const rRow = rawDb.prepare("SELECT status, discard_reason FROM inbox WHERE platform_msg_id = 'msg_already_replied';").get();
        assert.strictEqual(rRow.status, 'replied');
        assert.strictEqual(rRow.discard_reason, null);
      } finally {
        rawDb.close();
      }

      // 2. Now claim and expire on holder_new
      seedInboxMessage(repo.databasePath, 'line:group:100', 'msg_claim_2', 'acc_1');
      repo.claimMessages('line:group:100', 'holder_new', 2, 1);
      const expRes = repo.expireChannelHolder('line:group:100');
      assert.strictEqual(expRes.success, true);

      // Verify again: msg_prev_discarded and msg_already_replied still unaltered
      const rawDb2 = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const dRow = rawDb2.prepare("SELECT status, discard_reason, discarded_by_holder, discarded_at_token FROM inbox WHERE platform_msg_id = 'msg_prev_discarded';").get();
        assert.strictEqual(dRow.status, 'discarded');
        assert.strictEqual(dRow.discard_reason, 'PRIOR_REASON');
        assert.strictEqual(dRow.discarded_by_holder, 'holder_prev');
        assert.strictEqual(dRow.discarded_at_token, 0);

        const rRow = rawDb2.prepare("SELECT status, discard_reason FROM inbox WHERE platform_msg_id = 'msg_already_replied';").get();
        assert.strictEqual(rRow.status, 'replied');
        assert.strictEqual(rRow.discard_reason, null);
      } finally {
        rawDb2.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 23. Reply authorization multi-account collision canary and wrong-account isolation (CANARY 25, 26)
test('SqliteChannelTransactions - 23. reply authorization disambiguates multi-account collision and isolates wrong account (CANARY 25, 26)', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:group:collision', 'holder_shared');

      // Seed two distinct rows with same channel_id and same platform_msg_id under different accounts (valid schema v3)
      seedInboxMessage(
        repo.databasePath,
        'line:group:collision',
        'shared_platform_msg_99',
        'acc_alpha',
        'claimed',
        {
          claimedBy: 'holder_shared',
          claimedAtToken: 1,
        }
      );
      seedInboxMessage(
        repo.databasePath,
        'line:group:collision',
        'shared_platform_msg_99',
        'acc_beta',
        'claimed',
        {
          claimedBy: 'holder_shared',
          claimedAtToken: 1,
        }
      );

      // 1. Caller for acc_alpha selects exact acc_alpha row
      const resAlpha = repo.validateReplyAuthorization(
        'line:group:collision',
        'holder_shared',
        1,
        'shared_platform_msg_99',
        'acc_alpha'
      );
      assert.strictEqual(resAlpha.authorized, true);
      assert.strictEqual(resAlpha.messageId, 'shared_platform_msg_99');
      assert.strictEqual(resAlpha.channelId, 'line:group:collision');
      assert.strictEqual(resAlpha.receivingAccountId, 'acc_alpha');
      assert.strictEqual(resAlpha.replyingAccountId, 'acc_alpha');

      // 2. Caller for acc_beta selects exact acc_beta row without collision interference
      const resBeta = repo.validateReplyAuthorization(
        'line:group:collision',
        'holder_shared',
        1,
        'shared_platform_msg_99',
        'acc_beta'
      );
      assert.strictEqual(resBeta.authorized, true);
      assert.strictEqual(resBeta.messageId, 'shared_platform_msg_99');
      assert.strictEqual(resBeta.channelId, 'line:group:collision');
      assert.strictEqual(resBeta.receivingAccountId, 'acc_beta');
      assert.strictEqual(resBeta.replyingAccountId, 'acc_beta');

      // 3. Caller for acc_gamma (wrong account): primary exact miss, secondary channel probe hits -> ACCOUNT_MISMATCH
      const resGamma = repo.validateReplyAuthorization(
        'line:group:collision',
        'holder_shared',
        1,
        'shared_platform_msg_99',
        'acc_gamma'
      );
      assert.strictEqual(resGamma.authorized, false);
      assert.strictEqual(resGamma.reason, 'ACCOUNT_MISMATCH');
      // Cross-account isolation: does NOT expose state or claim metadata of other accounts
      assert.strictEqual(resGamma.status, undefined);
      assert.strictEqual(resGamma.claimedBy, undefined);
      assert.strictEqual(resGamma.claimedAtToken, undefined);

      // 4. Zero-mutation verification: verify both rows remain intact and unaltered in SQLite
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const rows = rawDb.prepare(
          "SELECT account_id, platform_msg_id, status, claimed_by, claimed_at_token FROM inbox WHERE channel_id = 'line:group:collision' AND platform_msg_id = 'shared_platform_msg_99' ORDER BY sequence ASC;"
        ).all();
        assert.strictEqual(rows.length, 2);
        assert.strictEqual(rows[0].account_id, 'acc_alpha');
        assert.strictEqual(rows[0].status, 'claimed');
        assert.strictEqual(rows[0].claimed_by, 'holder_shared');
        assert.strictEqual(rows[0].claimed_at_token, 1);
        assert.strictEqual(rows[1].account_id, 'acc_beta');
        assert.strictEqual(rows[1].status, 'claimed');
        assert.strictEqual(rows[1].claimed_by, 'holder_shared');
        assert.strictEqual(rows[1].claimed_at_token, 1);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 24. Reply authorization channel boundary canary: cross-channel message cannot be authorized or probe-mismatched
test('SqliteChannelTransactions - 24. reply authorization enforces strict channel boundary and rejects cross-channel message with MESSAGE_NOT_FOUND', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      // Establish two separate channels
      repo.takeoverChannel('line:channel:primary', 'holder_1');
      repo.takeoverChannel('line:channel:secondary', 'holder_2');

      // Seed message into primary channel only
      seedInboxMessage(
        repo.databasePath,
        'line:channel:primary',
        'msg_primary_only',
        'acc_primary',
        'claimed',
        {
          claimedBy: 'holder_1',
          claimedAtToken: 1,
        }
      );

      // Attempt authorization on secondary channel for message that only exists in primary channel
      const res = repo.validateReplyAuthorization(
        'line:channel:secondary',
        'holder_2',
        1,
        'msg_primary_only',
        'acc_primary'
      );
      // Strict channel boundary: must return MESSAGE_NOT_FOUND, never ACCOUNT_MISMATCH, never cross-channel auth
      assert.strictEqual(res.authorized, false);
      assert.strictEqual(res.reason, 'MESSAGE_NOT_FOUND');

      // Verify zero mutation on primary message
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const row = rawDb.prepare(
          "SELECT channel_id, account_id, status, claimed_by, claimed_at_token FROM inbox WHERE platform_msg_id = 'msg_primary_only';"
        ).get();
        assert.strictEqual(row.channel_id, 'line:channel:primary');
        assert.strictEqual(row.account_id, 'acc_primary');
        assert.strictEqual(row.status, 'claimed');
        assert.strictEqual(row.claimed_by, 'holder_1');
        assert.strictEqual(row.claimed_at_token, 1);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 25. getClaimedMessages: correct holder and token returns claimed rows in sequence order with content (D-TG11-2)
test('SqliteChannelTransactions - 25. getClaimedMessages returns claimed rows with content in ascending sequence', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:group:1', 'holder_alpha');

      seedInboxMessage(repo.databasePath, 'tg:group:1', 'msg_1', 'acc_1', 'claimed', {
        claimedBy: 'holder_alpha',
        claimedAtToken: 1,
        content: 'Hello message 1',
      });
      seedInboxMessage(repo.databasePath, 'tg:group:1', 'msg_2', 'acc_1', 'claimed', {
        claimedBy: 'holder_alpha',
        claimedAtToken: 1,
        content: 'Hello message 2',
      });
      seedInboxMessage(repo.databasePath, 'tg:group:1', 'msg_3', 'acc_1', 'queued', {
        content: 'Queued message 3',
      });

      const claimed = repo.getClaimedMessages('tg:group:1', 'holder_alpha', 1);
      assert.strictEqual(claimed.length, 2);
      assert.strictEqual(claimed[0].messageId, 'msg_1');
      assert.strictEqual(claimed[0].content, 'Hello message 1');
      assert.strictEqual(claimed[0].status, 'claimed');
      assert.strictEqual(claimed[0].claimedBy, 'holder_alpha');
      assert.strictEqual(claimed[0].claimedAtToken, 1);

      assert.strictEqual(claimed[1].messageId, 'msg_2');
      assert.strictEqual(claimed[1].content, 'Hello message 2');
      assert.strictEqual(claimed[1].sequence > claimed[0].sequence, true);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 26. getClaimedMessages: wrong holder returns [] (D-TG11-2, T21)
test('SqliteChannelTransactions - 26. getClaimedMessages returns [] on wrong holder', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:group:1', 'holder_alpha');
      seedInboxMessage(repo.databasePath, 'tg:group:1', 'msg_1', 'acc_1', 'claimed', {
        claimedBy: 'holder_alpha',
        claimedAtToken: 1,
        content: 'Content',
      });

      const claimed = repo.getClaimedMessages('tg:group:1', 'wrong_holder', 1);
      assert.deepStrictEqual(claimed, []);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 27. getClaimedMessages: stale token returns [] (D-TG11-2, T21)
test('SqliteChannelTransactions - 27. getClaimedMessages returns [] on stale token', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:group:1', 'holder_alpha');
      seedInboxMessage(repo.databasePath, 'tg:group:1', 'msg_1', 'acc_1', 'claimed', {
        claimedBy: 'holder_alpha',
        claimedAtToken: 1,
        content: 'Content',
      });

      const claimed = repo.getClaimedMessages('tg:group:1', 'holder_alpha', 0);
      assert.deepStrictEqual(claimed, []);

      const claimedFuture = repo.getClaimedMessages('tg:group:1', 'holder_alpha', 99);
      assert.deepStrictEqual(claimedFuture, []);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 28. getClaimedMessages: no holder returns [] (D-TG11-2)
test('SqliteChannelTransactions - 28. getClaimedMessages returns [] when channel has no holder or does not exist', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      const nonExistent = repo.getClaimedMessages('tg:nonexistent', 'holder_alpha', 1);
      assert.deepStrictEqual(nonExistent, []);

      // Channel exists but holder expired (current_holder is null)
      repo.takeoverChannel('tg:group:2', 'holder_temp', { timestamp: 1000 });
      repo.expireChannelHolder('tg:group:2');
      const expiredHolder = repo.getClaimedMessages('tg:group:2', 'holder_temp', 1);
      assert.deepStrictEqual(expiredHolder, []);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 29. getClaimedMessages: hard maximum 50 rows returned (D-TG11-2)
test('SqliteChannelTransactions - 29. getClaimedMessages enforces hard repository limit 50', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:group:bulk', 'holder_bulk');

      for (let i = 1; i <= 60; i++) {
        seedInboxMessage(repo.databasePath, 'tg:group:bulk', `bulk_msg_${i}`, 'acc_bulk', 'claimed', {
          claimedBy: 'holder_bulk',
          claimedAtToken: 1,
          content: `Content ${i}`,
        });
      }

      const claimed = repo.getClaimedMessages('tg:group:bulk', 'holder_bulk', 1);
      assert.strictEqual(claimed.length, 50, 'Hard repository limit 50 must cap returned claimed messages');
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 30. getClaimedMessages: claimed_by and claimed_at_token filtering isolates rows from other/stale holders (T21)
test('SqliteChannelTransactions - 30. getClaimedMessages strict row filter isolates other holder claims', { timeout: 5000 }, () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:group:filter', 'holder_current');

      // Seed a claimed row with older token or another holder
      seedInboxMessage(repo.databasePath, 'tg:group:filter', 'msg_old_holder', 'acc_filter', 'claimed', {
        claimedBy: 'holder_old',
        claimedAtToken: 0,
        content: 'Old claim',
      });
      // Seed a claimed row with matching current holder & token
      seedInboxMessage(repo.databasePath, 'tg:group:filter', 'msg_curr_holder', 'acc_filter', 'claimed', {
        claimedBy: 'holder_current',
        claimedAtToken: 1,
        content: 'Current claim',
      });

      const claimed = repo.getClaimedMessages('tg:group:filter', 'holder_current', 1);
      assert.strictEqual(claimed.length, 1);
      assert.strictEqual(claimed[0].messageId, 'msg_curr_holder');
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 31. enqueueAuthorizedReply - fresh enqueue creates single QUEUED outbox command and marks inbox replied
test('SqliteChannelTransactions - 31. R2-A: fresh enqueueAuthorizedReply creates durable QUEUED command and marks inbox replied', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:reply:1', 'holder_1');
      seedInboxMessage(repo.databasePath, 'tg:reply:1', 'msg_reply_1', 'acc_1', 'claimed', {
        claimedBy: 'holder_1',
        claimedAtToken: 1,
      });

      const text = 'Hello world reply';
      const payloadHash = computeCanonicalPayloadHash({
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        messageType: 'text',
        text,
      });

      const res = repo.enqueueAuthorizedReply({
        clientRequestId: 'req-001',
        channelId: 'tg:reply:1',
        holderId: 'holder_1',
        fencingToken: 1,
        messageId: 'msg_reply_1',
        replyingAccountId: 'acc_1',
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        logicalReplyTarget: 'msg_reply_1',
        messageType: 'text',
        text,
        payloadHash,
      });

      assert.strictEqual(res.success, true);
      assert.strictEqual(res.idempotentReplay, false);
      assert.strictEqual(res.outboxStatus, 'QUEUED');
      assert.ok(typeof res.commandId === 'string' && res.commandId.length > 0);

      // Verify inbox status transitioned to replied
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const inboxRow = rawDb.prepare("SELECT status FROM inbox WHERE platform_msg_id = 'msg_reply_1';").get();
        assert.strictEqual(inboxRow.status, 'replied');

        const outboxRows = rawDb.prepare('SELECT * FROM outbox;').all();
        assert.strictEqual(outboxRows.length, 1);
        assert.strictEqual(outboxRows[0].client_request_id, 'req-001');
        assert.strictEqual(outboxRows[0].status, 'QUEUED');
        assert.strictEqual(outboxRows[0].body, 'Hello world reply');
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 32. R2-A: Same client_request_id + same payload -> idempotent replay returns existing command
test('SqliteChannelTransactions - 32. R2-A: idempotent replay returns existing command and does not duplicate', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:reply:2', 'holder_1');
      seedInboxMessage(repo.databasePath, 'tg:reply:2', 'msg_reply_2', 'acc_1', 'claimed', {
        claimedBy: 'holder_1',
        claimedAtToken: 1,
      });

      const text = 'Idempotent text';
      const payloadHash = computeCanonicalPayloadHash({
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        messageType: 'text',
        text,
      });

      const params = {
        clientRequestId: 'req-idem-1',
        channelId: 'tg:reply:2',
        holderId: 'holder_1',
        fencingToken: 1,
        messageId: 'msg_reply_2',
        replyingAccountId: 'acc_1',
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        logicalReplyTarget: 'msg_reply_2',
        messageType: 'text',
        text,
        payloadHash,
      };

      const res1 = repo.enqueueAuthorizedReply(params);
      assert.strictEqual(res1.success, true);
      assert.strictEqual(res1.idempotentReplay, false);

      // Second identical call (even if holder has changed later!)
      const res2 = repo.enqueueAuthorizedReply(params);
      assert.strictEqual(res2.success, true);
      assert.strictEqual(res2.idempotentReplay, true);
      assert.strictEqual(res2.commandId, res1.commandId);
      assert.strictEqual(res2.outboxStatus, 'QUEUED');

      // Exactly one row in outbox table
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const outboxRows = rawDb.prepare('SELECT * FROM outbox;').all();
        assert.strictEqual(outboxRows.length, 1);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 33. R2-B: Same client_request_id + different payload -> IDEMPOTENCY_CONFLICT
test('SqliteChannelTransactions - 33. R2-B: same client_request_id with different payload returns IDEMPOTENCY_CONFLICT', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:reply:3', 'holder_1');
      seedInboxMessage(repo.databasePath, 'tg:reply:3', 'msg_reply_3', 'acc_1', 'claimed', {
        claimedBy: 'holder_1',
        claimedAtToken: 1,
      });

      const text1 = 'Initial text';
      const hash1 = computeCanonicalPayloadHash({
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        messageType: 'text',
        text: text1,
      });

      const res1 = repo.enqueueAuthorizedReply({
        clientRequestId: 'req-conflict-1',
        channelId: 'tg:reply:3',
        holderId: 'holder_1',
        fencingToken: 1,
        messageId: 'msg_reply_3',
        replyingAccountId: 'acc_1',
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        logicalReplyTarget: 'msg_reply_3',
        messageType: 'text',
        text: text1,
        payloadHash: hash1,
      });
      assert.strictEqual(res1.success, true);

      const text2 = 'DIFFERENT text conflicting payload';
      const hash2 = computeCanonicalPayloadHash({
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        messageType: 'text',
        text: text2,
      });

      // Second call with same clientRequestId but DIFFERENT text
      const res2 = repo.enqueueAuthorizedReply({
        clientRequestId: 'req-conflict-1',
        channelId: 'tg:reply:3',
        holderId: 'holder_1',
        fencingToken: 1,
        messageId: 'msg_reply_3',
        replyingAccountId: 'acc_1',
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        logicalReplyTarget: 'msg_reply_3',
        messageType: 'text',
        text: text2,
        payloadHash: hash2,
      });
      assert.strictEqual(res2.success, false);
      assert.strictEqual(res2.reason, 'IDEMPOTENCY_CONFLICT');

      // Verify zero second row in outbox
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const count = rawDb.prepare('SELECT count(*) as cnt FROM outbox;').get();
        assert.strictEqual(count.cnt, 1);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 34. R2-D: Takeover after commit preserves committed outbox command
test('SqliteChannelTransactions - 34. R2-D: takeover after commit preserves committed outbox command', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:reply:4', 'holder_A');
      seedInboxMessage(repo.databasePath, 'tg:reply:4', 'msg_reply_4', 'acc_1', 'claimed', {
        claimedBy: 'holder_A',
        claimedAtToken: 1,
      });

      const text = 'Committed before takeover';
      const payloadHash = computeCanonicalPayloadHash({
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        messageType: 'text',
        text,
      });

      const res = repo.enqueueAuthorizedReply({
        clientRequestId: 'req-takeover-preserves-1',
        channelId: 'tg:reply:4',
        holderId: 'holder_A',
        fencingToken: 1,
        messageId: 'msg_reply_4',
        replyingAccountId: 'acc_1',
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        logicalReplyTarget: 'msg_reply_4',
        messageType: 'text',
        text,
        payloadHash,
      });
      assert.strictEqual(res.success, true);

      // Takeover by holder_B
      repo.takeoverChannel('tg:reply:4', 'holder_B');

      // Verify outbox command is untouched
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const outboxRow = rawDb.prepare('SELECT * FROM outbox WHERE command_id = ?;').get(res.commandId);
        assert.ok(outboxRow);
        assert.strictEqual(outboxRow.status, 'QUEUED');
        assert.strictEqual(outboxRow.client_request_id, 'req-takeover-preserves-1');
      } finally {
        rawDb.close();
      }

      // Idempotent replay by old request still succeeds even after takeover!
      const replay = repo.enqueueAuthorizedReply({
        clientRequestId: 'req-takeover-preserves-1',
        channelId: 'tg:reply:4',
        holderId: 'holder_A',
        fencingToken: 1,
        messageId: 'msg_reply_4',
        replyingAccountId: 'acc_1',
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        logicalReplyTarget: 'msg_reply_4',
        messageType: 'text',
        text,
        payloadHash,
      });
      assert.strictEqual(replay.success, true);
      assert.strictEqual(replay.idempotentReplay, true);
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 35. Stale fencing or wrong holder returns false with zero outbox mutation
test('SqliteChannelTransactions - 35. stale fencing or wrong holder returns false with zero outbox rows', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:reply:5', 'holder_A');
      seedInboxMessage(repo.databasePath, 'tg:reply:5', 'msg_reply_5', 'acc_1', 'claimed', {
        claimedBy: 'holder_A',
        claimedAtToken: 1,
      });

      const text = 'Fail attempt';
      const payloadHash = computeCanonicalPayloadHash({
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        messageType: 'text',
        text,
      });

      // Wrong holder
      const badHolderRes = repo.enqueueAuthorizedReply({
        clientRequestId: 'req-bad-holder',
        channelId: 'tg:reply:5',
        holderId: 'wrong_holder',
        fencingToken: 1,
        messageId: 'msg_reply_5',
        replyingAccountId: 'acc_1',
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        logicalReplyTarget: 'msg_reply_5',
        messageType: 'text',
        text,
        payloadHash,
      });
      assert.strictEqual(badHolderRes.success, false);
      assert.strictEqual(badHolderRes.reason, 'NOT_CURRENT_HOLDER');

      // Stale fencing token
      const staleTokenRes = repo.enqueueAuthorizedReply({
        clientRequestId: 'req-stale-tok',
        channelId: 'tg:reply:5',
        holderId: 'holder_A',
        fencingToken: 0,
        messageId: 'msg_reply_5',
        replyingAccountId: 'acc_1',
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        logicalReplyTarget: 'msg_reply_5',
        messageType: 'text',
        text,
        payloadHash,
      });
      assert.strictEqual(staleTokenRes.success, false);
      assert.strictEqual(staleTokenRes.reason, 'STALE_FENCING_TOKEN');

      // Zero outbox rows created
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const count = rawDb.prepare('SELECT count(*) as cnt FROM outbox;').get();
        assert.strictEqual(count.cnt, 0);
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 36. Forced outbox INSERT failure rolls back inbox transition
test('SqliteChannelTransactions - 36. forced outbox insert failure rolls back: inbox remains claimed and zero outbox rows', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('tg:reply:6', 'holder_A');
      seedInboxMessage(repo.databasePath, 'tg:reply:6', 'msg_reply_6', 'acc_1', 'claimed', {
        claimedBy: 'holder_A',
        claimedAtToken: 1,
      });

      const text = 'Doomed text';
      const payloadHash = computeCanonicalPayloadHash({
        platform: 'telegram',
        endpointOperation: 'sendMessage',
        recipient: '123456',
        messageType: 'text',
        text,
      });

      // Install abort trigger on outbox
      const rawDb = new DatabaseSync(repo.databasePath);
      try {
        rawDb.exec(`
          CREATE TRIGGER test_abort_outbox
          BEFORE INSERT ON outbox
          BEGIN
            SELECT RAISE(ABORT, 'Simulated forced outbox INSERT failure');
          END;
        `);
      } finally {
        rawDb.close();
      }

      assert.throws(
        () =>
          repo.enqueueAuthorizedReply({
            clientRequestId: 'req-abort-outbox',
            channelId: 'tg:reply:6',
            holderId: 'holder_A',
            fencingToken: 1,
            messageId: 'msg_reply_6',
            replyingAccountId: 'acc_1',
            platform: 'telegram',
            endpointOperation: 'sendMessage',
            recipient: '123456',
            logicalReplyTarget: 'msg_reply_6',
            messageType: 'text',
            text,
            payloadHash,
          }),
        /Simulated forced outbox INSERT failure/
      );

      // Inbox must STILL be claimed (NOT replied)
      const checkDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const inboxRow = checkDb.prepare("SELECT status FROM inbox WHERE platform_msg_id = 'msg_reply_6';").get();
        assert.strictEqual(inboxRow.status, 'claimed', 'Inbox status must remain claimed on rollback');

        const outboxCount = checkDb.prepare('SELECT count(*) as cnt FROM outbox;').get();
        assert.strictEqual(outboxCount.cnt, 0, 'Zero outbox rows must exist');
      } finally {
        checkDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});

// 37. F1: enqueueAuthorizedReply rejects unpaired, malformed, expired, or far-future LINE retry credentials (fail closed)
test('SqliteChannelTransactions - 37. F1: enqueueAuthorizedReply rejects unpaired, malformed, expired, or far-future LINE retry credentials and enforces schema pair CHECK', () => {
  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      repo.takeoverChannel('line:reply:1', 'holder_line');
      seedInboxMessage(repo.databasePath, 'line:reply:1', 'msg_line_1', 'acc_line', 'claimed', {
        claimedBy: 'holder_line',
        claimedAtToken: 1,
      });

      const nowSec = 1700000000;
      const validUUID = '550e8400-e29b-41d4-a716-446655440000';
      const malformedUUID = 'bad-uuid-format';
      const text = 'Line push reply';
      const payloadHash = computeCanonicalPayloadHash({
        platform: 'line',
        endpointOperation: 'push',
        recipient: 'U12345678',
        messageType: 'text',
        text,
      });

      const baseParams = {
        channelId: 'line:reply:1',
        holderId: 'holder_line',
        fencingToken: 1,
        messageId: 'msg_line_1',
        replyingAccountId: 'acc_line',
        platform: 'line',
        endpointOperation: 'push',
        recipient: 'U12345678',
        logicalReplyTarget: 'msg_line_1',
        messageType: 'text',
        text,
        payloadHash,
        nowSec,
      };

      // 1. Key with null expiry -> throws TypeError
      assert.throws(
        () => repo.enqueueAuthorizedReply({ ...baseParams, clientRequestId: 'req-bad-1', externalRetryKey: validUUID, externalRetryExpiresAt: null }),
        /must be provided together/
      );

      // 2. Key with undefined expiry -> throws TypeError
      assert.throws(
        () => repo.enqueueAuthorizedReply({ ...baseParams, clientRequestId: 'req-bad-2', externalRetryKey: validUUID, externalRetryExpiresAt: undefined }),
        /must be provided together/
      );

      // 3. Expiry without key -> throws TypeError
      assert.throws(
        () => repo.enqueueAuthorizedReply({ ...baseParams, clientRequestId: 'req-bad-3', externalRetryKey: null, externalRetryExpiresAt: nowSec + 3600 }),
        /must be provided together/
      );

      // 4. Malformed UUID + future expiry -> throws TypeError
      assert.throws(
        () => repo.enqueueAuthorizedReply({ ...baseParams, clientRequestId: 'req-bad-4', externalRetryKey: malformedUUID, externalRetryExpiresAt: nowSec + 3600 }),
        /valid 128-bit UUID/
      );

      // 5. Expired expiry (nowSec) -> throws RangeError
      assert.throws(
        () => repo.enqueueAuthorizedReply({ ...baseParams, clientRequestId: 'req-bad-5', externalRetryKey: validUUID, externalRetryExpiresAt: nowSec }),
        /must be > nowSec/
      );

      // 6. Expired expiry (nowSec - 10) -> throws RangeError
      assert.throws(
        () => repo.enqueueAuthorizedReply({ ...baseParams, clientRequestId: 'req-bad-6', externalRetryKey: validUUID, externalRetryExpiresAt: nowSec - 10 }),
        /must be > nowSec/
      );

      // 7. Far-future initial expiry > nowSec + 86400 -> throws RangeError
      assert.throws(
        () => repo.enqueueAuthorizedReply({ ...baseParams, clientRequestId: 'req-bad-7', externalRetryKey: validUUID, externalRetryExpiresAt: nowSec + 86401 }),
        /must be > nowSec .* and <= nowSec \+ 86400/
      );

      // 8. Valid UUID + unexpired initial expiry (nowSec + 3600) -> succeeds!
      const okRes = repo.enqueueAuthorizedReply({
        ...baseParams,
        clientRequestId: 'req-ok-1',
        externalRetryKey: validUUID,
        externalRetryExpiresAt: nowSec + 3600,
      });
      assert.strictEqual(okRes.success, true);
      assert.strictEqual(okRes.outboxStatus, 'QUEUED');

      const saved = repo.getOutboxCommand(okRes.commandId);
      assert.strictEqual(saved.external_retry_key, validUUID);
      assert.strictEqual(saved.external_retry_expires_at, nowSec + 3600);

      // 9. Schema pair CHECK constraint: direct raw insert with only key or only expiry fails with SQLITE_CONSTRAINT
      const rawDb = new DatabaseSync(repo.databasePath);
      try {
        // Raw insert with key but NULL expiry -> SQLITE_CONSTRAINT
        assert.throws(
          () =>
            rawDb
              .prepare(
                `INSERT INTO outbox (
                  command_id, client_request_id, payload_hash, platform, account_id,
                  endpoint_operation, recipient, message_type, body, status,
                  created_at, updated_at, external_retry_key, external_retry_expires_at
                ) VALUES ('cmd_viol_1', 'req_viol_1', '${'a'.repeat(64)}', 'line', 'acc_1', 'push', 'u1', 'text', 'b', 'QUEUED', 1, 1, 'key-only', NULL);`
              )
              .run(),
          /constraint/i
        );

        // Raw insert with expiry but NULL key -> SQLITE_CONSTRAINT
        assert.throws(
          () =>
            rawDb
              .prepare(
                `INSERT INTO outbox (
                  command_id, client_request_id, payload_hash, platform, account_id,
                  endpoint_operation, recipient, message_type, body, status,
                  created_at, updated_at, external_retry_key, external_retry_expires_at
                ) VALUES ('cmd_viol_2', 'req_viol_2', '${'b'.repeat(64)}', 'line', 'acc_1', 'push', 'u1', 'text', 'b', 'QUEUED', 1, 1, NULL, 12345);`
              )
              .run(),
          /constraint/i
        );
      } finally {
        rawDb.close();
      }
    } finally {
      repo.close();
    }
  } finally {
    harness.cleanup();
  }
});
