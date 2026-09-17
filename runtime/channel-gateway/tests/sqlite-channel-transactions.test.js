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
function seedInboxMessage(databasePath, channelId, messageId, receivingAccountId = 'acc_default', status = 'queued') {
  const rawDb = new DatabaseSync(databasePath);
  try {
    const stmt = rawDb.prepare(
      'INSERT INTO inbox (channel_id, message_id, receiving_account_id, status) VALUES (?, ?, ?, ?);'
    );
    stmt.run(channelId, String(messageId), receivingAccountId, status);
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
        const rows = rawDb.prepare('SELECT message_id, status, discard_reason, discarded_by_holder, discarded_at_token FROM inbox ORDER BY sequence ASC;').all();
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
        const msgRow = rawDb.prepare("SELECT status FROM inbox WHERE message_id = 'msg_claimed';").get();
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
        const row = rawDb.prepare("SELECT status, discard_reason FROM inbox WHERE message_id = 'msg_1';").get();
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
          "CREATE TRIGGER test_abort_second_claim BEFORE UPDATE OF status ON inbox WHEN NEW.message_id = 'msg_claim_2' BEGIN SELECT RAISE(ABORT, 'forced test abort on second claim'); END;"
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
        const rows = rawDb.prepare('SELECT message_id, status FROM inbox ORDER BY sequence ASC;').all();
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
test('SqliteChannelTransactions - 16. architectural invariants: schema version 2, no ingress/outbox/account-switch', () => {
  assert.strictEqual(SQLITE_STATE_SCHEMA_VERSION, 2, 'CANARY 17: schema version must remain 2');

  const harness = createTempHarness();
  try {
    const repo = new SqliteStateRepository(harness.stateRoot);
    try {
      assert.strictEqual(repo.schemaVersion, 2, 'CANARY 18: applied schema version is 2');

      // CANARY 19: No production ingress API
      assert.strictEqual(repo.enqueueMessage, undefined);
      assert.strictEqual(repo.ingestMessage, undefined);
      assert.strictEqual(repo.receiveMessage, undefined);
      assert.strictEqual(repo.insertInboundMessage, undefined);

      // CANARY 20: No account-switch mutation
      assert.strictEqual(repo.discardQueuedForAccount, undefined);

      // CANARY 21: No outbox
      assert.strictEqual(repo.createOutbox, undefined);

      // CANARY 22: R2 safe - no reply mutation completion
      assert.strictEqual(repo.authorizeReply, undefined);

      // CANARY 23: No T8 cursor or composite dedupe
      const rawDb = new DatabaseSync(repo.databasePath, { readOnly: true });
      try {
        const tRows = rawDb.prepare("SELECT name FROM sqlite_schema WHERE type = 'table';").all();
        const tNames = tRows.map((r) => r.name);
        assert.strictEqual(tNames.includes('ingest_cursor'), false);
        assert.strictEqual(tNames.includes('outbox'), false);
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
