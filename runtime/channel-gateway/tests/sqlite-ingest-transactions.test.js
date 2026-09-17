/**
 * runtime/channel-gateway/tests/sqlite-ingest-transactions.test.js
 *
 * ADR-0023 / E-03 T8B: Channel Gateway Atomic Durable Ingest + Cursor Transaction Test Suite.
 *
 * Verifies:
 * 1. Input validation matrix for ingestMessage and getIngestCursor.
 * 2. Canonical inbound ingest + cursor write in a single immediate transaction (CANARY 1).
 * 3. Unattended channel initialization with holder=NULL, token=0 (CANARY 9, 10).
 * 4. Idempotent deduplication based on (account_id, platform_msg_id) and no-op cursor (CANARY 4, 5, 6, 7).
 * 5. Independent per-account cursors and same platform_msg_id across different accounts (CANARY 8, 22).
 * 6. Exact content preservation for Traditional Chinese, empty string, and newlines (CANARY 14).
 * 7. Deterministic rollback on cursor write failure (CANARY 2).
 * 8. Deterministic rollback on inbox write failure (CANARY 3).
 * 9. Restart persistence: message and cursor survive repository close and reopen (CANARY 11, 12).
 * 10. Multi-connection durable deduplication across independent repository handles (CANARY 13).
 * 11. T7B lifecycle integration: ingested queued messages claimed FIFO by subsequent holder (CANARY 15).
 * 12. Architectural boundaries and freeze invariants (CANARY 16, 17, 18, 19, 20).
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
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-sqlite-ingest-test-'));
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

test('T8B Test 1: Input Validation Matrix', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Invalid input container
    assert.throws(() => repo.ingestMessage(null), TypeError);
    assert.throws(() => repo.ingestMessage(undefined), TypeError);
    assert.throws(() => repo.ingestMessage('not an object'), TypeError);
    assert.throws(() => repo.ingestMessage([]), TypeError);

    const validBase = {
      accountId: 'acc_001',
      platformMsgId: 'msg_100',
      channelId: 'chan_tw',
      content: '測試訊息',
      cursorValue: 'cur_001',
    };

    // accountId validation
    assert.throws(() => repo.ingestMessage({ ...validBase, accountId: '' }), /accountId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, accountId: '   ' }), /accountId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, accountId: null }), TypeError);
    assert.throws(() => repo.ingestMessage({ ...validBase, accountId: 123 }), TypeError);

    // platformMsgId validation
    assert.throws(() => repo.ingestMessage({ ...validBase, platformMsgId: null }), /platformMsgId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, platformMsgId: undefined }), /platformMsgId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, platformMsgId: '' }), /platformMsgId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, platformMsgId: '   ' }), /platformMsgId/);

    // channelId validation
    assert.throws(() => repo.ingestMessage({ ...validBase, channelId: '' }), /channelId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, channelId: '   ' }), /channelId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, channelId: null }), TypeError);
    assert.throws(() => repo.ingestMessage({ ...validBase, channelId: 456 }), TypeError);

    // cursorValue validation
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: null }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: undefined }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '   ' }), /cursorValue/);

    // content validation (must be string, empty string allowed, null/numbers rejected)
    assert.throws(() => repo.ingestMessage({ ...validBase, content: null }), TypeError);
    assert.throws(() => repo.ingestMessage({ ...validBase, content: 12345 }), TypeError);
    assert.throws(() => repo.ingestMessage({ ...validBase, content: {} }), TypeError);

    // getIngestCursor validation
    assert.throws(() => repo.getIngestCursor(''), /accountId/);
    assert.throws(() => repo.getIngestCursor('   '), /accountId/);
    assert.throws(() => repo.getIngestCursor(null), TypeError);

    repo.close();

    // Closed repository rejects operations
    assert.throws(() => repo.ingestMessage(validBase), /closed/);
    assert.throws(() => repo.getIngestCursor('acc_001'), /closed/);
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 2: Canonical Ingest & Atomic Cursor Upsert (CANARY 1)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    assert.strictEqual(repo.getIngestCursor('acc_tw_1'), null);

    const res = repo.ingestMessage({
      accountId: 'acc_tw_1',
      platformMsgId: '1001',
      channelId: 'telegram_main',
      content: '台股加權指數收盤分析',
      cursorValue: 'update_id_5001',
    });

    assert.strictEqual(res.success, true);
    assert.strictEqual(res.duplicate, false);
    assert.strictEqual(typeof res.sequence, 'number');
    assert.strictEqual(res.sequence >= 1, true);
    assert.strictEqual(res.channelId, 'telegram_main');
    assert.strictEqual(res.accountId, 'acc_tw_1');
    assert.strictEqual(res.platformMsgId, '1001');
    assert.strictEqual(res.cursorValue, 'update_id_5001');

    // Verify cursor readback matches
    assert.strictEqual(repo.getIngestCursor('acc_tw_1'), 'update_id_5001');

    // Direct SQLite table inspection
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const msgRow = rawDb
        .prepare('SELECT sequence, channel_id, account_id, platform_msg_id, content, status FROM inbox WHERE sequence = ?;')
        .get(res.sequence);
      assert.ok(msgRow);
      assert.strictEqual(msgRow.channel_id, 'telegram_main');
      assert.strictEqual(msgRow.account_id, 'acc_tw_1');
      assert.strictEqual(msgRow.platform_msg_id, '1001');
      assert.strictEqual(msgRow.content, '台股加權指數收盤分析');
      assert.strictEqual(msgRow.status, 'queued');

      const curRow = rawDb
        .prepare('SELECT account_id, cursor_value FROM ingest_cursor WHERE account_id = ?;')
        .get('acc_tw_1');
      assert.ok(curRow);
      assert.strictEqual(curRow.cursor_value, 'update_id_5001');
    } finally {
      rawDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 3: Unattended Channel Initialization & D6 Holder Invariant (CANARY 9, 10)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Ingest into a completely new, unseen channel
    const res = repo.ingestMessage({
      accountId: 'acc_unattended',
      platformMsgId: 'msg_99',
      channelId: 'unattended_chan_alpha',
      content: '無人值守測試訊息',
      cursorValue: 'c_99',
    });
    assert.strictEqual(res.success, true);
    assert.strictEqual(res.duplicate, false);

    // Inspect channel state: D6 invariant requires holder=null, token=0
    const stateBefore = repo.getChannelState('unattended_chan_alpha');
    assert.ok(stateBefore);
    assert.strictEqual(stateBefore.channelId, 'unattended_chan_alpha');
    assert.strictEqual(stateBefore.currentHolder, null);
    assert.strictEqual(stateBefore.fencingToken, 0);
    assert.strictEqual(stateBefore.lastHeartbeatAt, null);
    assert.strictEqual(stateBefore.backlogCount, 1);

    // First takeover transitions fencing_token to 1 and assigns holder
    const takeoverRes = repo.takeoverChannel('unattended_chan_alpha', 'holder_live_1');
    assert.strictEqual(takeoverRes.success, true);
    assert.strictEqual(takeoverRes.holder, 'holder_live_1');
    assert.strictEqual(takeoverRes.fencingToken, 1);
    assert.strictEqual(takeoverRes.previousHolder, null);

    // Further ingest into existing channel preserves holder and token
    repo.ingestMessage({
      accountId: 'acc_unattended',
      platformMsgId: 'msg_100',
      channelId: 'unattended_chan_alpha',
      content: '無人值守第二則訊息',
      cursorValue: 'c_100',
    });

    const stateAfter = repo.getChannelState('unattended_chan_alpha');
    assert.strictEqual(stateAfter.currentHolder, 'holder_live_1');
    assert.strictEqual(stateAfter.fencingToken, 1);
    assert.strictEqual(stateAfter.backlogCount, 2);

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 4: Idempotent Deduplication & Cursor No-Op (CANARY 4, 5, 6, 7)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Initial ingest
    const firstRes = repo.ingestMessage({
      accountId: 'acc_dedupe_1',
      platformMsgId: 'm_alpha',
      channelId: 'chan_primary',
      content: '原始訊息內容',
      cursorValue: 'cursor_100',
    });
    assert.strictEqual(firstRes.success, true);
    assert.strictEqual(firstRes.duplicate, false);
    const originalSeq = firstRes.sequence;

    // Second ingest: same accountId and platformMsgId, but different cursor, content, and channel
    const secondRes = repo.ingestMessage({
      accountId: 'acc_dedupe_1',
      platformMsgId: 'm_alpha',
      channelId: 'chan_secondary',
      content: '重複傳送企圖竄改內容',
      cursorValue: 'cursor_999_fake',
    });

    assert.strictEqual(secondRes.success, true);
    assert.strictEqual(secondRes.duplicate, true);
    assert.strictEqual(secondRes.sequence, originalSeq);
    assert.strictEqual(secondRes.channelId, 'chan_primary');
    assert.strictEqual(secondRes.accountId, 'acc_dedupe_1');
    assert.strictEqual(secondRes.platformMsgId, 'm_alpha');

    // CRITICAL CANARY: cursor MUST NOT be updated on duplicate replay
    assert.strictEqual(repo.getIngestCursor('acc_dedupe_1'), 'cursor_100');

    // Verify inbox state: exact one row, original content preserved
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const rows = rawDb
        .prepare('SELECT sequence, channel_id, content FROM inbox WHERE account_id = ? AND platform_msg_id = ?;')
        .all('acc_dedupe_1', 'm_alpha');
      assert.strictEqual(rows.length, 1);
      assert.strictEqual(rows[0].sequence, originalSeq);
      assert.strictEqual(rows[0].channel_id, 'chan_primary');
      assert.strictEqual(rows[0].content, '原始訊息內容');
    } finally {
      rawDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 5: Independent Cursors & Cross-Account Collision Isolation (CANARY 8, 22)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Account 1: sequential messages advancing cursor
    repo.ingestMessage({
      accountId: 'account_A',
      platformMsgId: 'shared_msg_id',
      channelId: 'chan_1',
      content: '帳號 A 的訊息',
      cursorValue: 'cursor_A_1',
    });
    assert.strictEqual(repo.getIngestCursor('account_A'), 'cursor_A_1');

    repo.ingestMessage({
      accountId: 'account_A',
      platformMsgId: 'second_msg_id',
      channelId: 'chan_1',
      content: '帳號 A 第二則訊息',
      cursorValue: 'cursor_A_2',
    });
    assert.strictEqual(repo.getIngestCursor('account_A'), 'cursor_A_2');

    // Account 2: same platform_msg_id 'shared_msg_id' as account 1 (CANARY 8)
    const resB = repo.ingestMessage({
      accountId: 'account_B',
      platformMsgId: 'shared_msg_id',
      channelId: 'chan_1',
      content: '帳號 B 的訊息，相同平台編號',
      cursorValue: 'cursor_B_100',
    });
    assert.strictEqual(resB.success, true);
    assert.strictEqual(resB.duplicate, false);

    // Distinct cursors preserved
    assert.strictEqual(repo.getIngestCursor('account_A'), 'cursor_A_2');
    assert.strictEqual(repo.getIngestCursor('account_B'), 'cursor_B_100');

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 6: Content Exact Persistence (CANARY 14)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    const traditionalChinese = '繁體中文測試：台股分析模型與財務指標（營收、毛利、本益比河流圖）';
    const emptyContent = '';
    const multilineContent = '第一行標題\n第二行段落內容\r\n第三行附註\n\n結尾空白保留   ';

    const r1 = repo.ingestMessage({
      accountId: 'acc_content',
      platformMsgId: 'msg_tc',
      channelId: 'chan_tc',
      content: traditionalChinese,
      cursorValue: 'cur_tc',
    });
    const r2 = repo.ingestMessage({
      accountId: 'acc_content',
      platformMsgId: 'msg_empty',
      channelId: 'chan_tc',
      content: emptyContent,
      cursorValue: 'cur_empty',
    });
    const r3 = repo.ingestMessage({
      accountId: 'acc_content',
      platformMsgId: 'msg_multi',
      channelId: 'chan_tc',
      content: multilineContent,
      cursorValue: 'cur_multi',
    });

    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const getRow = (seq) =>
        rawDb.prepare('SELECT content FROM inbox WHERE sequence = ?;').get(seq);

      assert.strictEqual(getRow(r1.sequence).content, traditionalChinese);
      assert.strictEqual(getRow(r2.sequence).content, '');
      assert.strictEqual(getRow(r3.sequence).content, multilineContent);
    } finally {
      rawDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 7: Atomic Rollback on Cursor Write Failure (CANARY 2)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Install a temporary test abort trigger on ingest_cursor via rawDb
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      rawDb.exec(`
        CREATE TRIGGER test_abort_cursor
        BEFORE INSERT ON ingest_cursor
        BEGIN
          SELECT RAISE(ABORT, 'Simulated cursor write failure for rollback canary');
        END;
      `);
    } finally {
      rawDb.close();
    }

    // Ingest attempt into a new channel must throw and completely roll back
    assert.throws(
      () =>
        repo.ingestMessage({
          accountId: 'acc_fail_cursor',
          platformMsgId: 'msg_doomed_cursor',
          channelId: 'chan_rollback_test',
          content: '這則訊息應當被完整回滾',
          cursorValue: 'c_fail',
        }),
      /Simulated cursor write failure/
    );

    // Verify zero residual rows in inbox, ingest_cursor, and channel_control
    const checkDb = new DatabaseSync(repo.databasePath);
    try {
      const inboxRows = checkDb
        .prepare('SELECT count(*) AS cnt FROM inbox WHERE account_id = ?;')
        .get('acc_fail_cursor');
      assert.strictEqual(inboxRows.cnt, 0);

      const cursorRows = checkDb
        .prepare('SELECT count(*) AS cnt FROM ingest_cursor WHERE account_id = ?;')
        .get('acc_fail_cursor');
      assert.strictEqual(cursorRows.cnt, 0);

      const chanRows = checkDb
        .prepare('SELECT count(*) AS cnt FROM channel_control WHERE channel_id = ?;')
        .get('chan_rollback_test');
      assert.strictEqual(chanRows.cnt, 0);

      // Clean up test trigger
      checkDb.exec('DROP TRIGGER test_abort_cursor;');
    } finally {
      checkDb.close();
    }

    // After dropping trigger, operation succeeds cleanly
    const okRes = repo.ingestMessage({
      accountId: 'acc_fail_cursor',
      platformMsgId: 'msg_doomed_cursor',
      channelId: 'chan_rollback_test',
      content: '重試成功',
      cursorValue: 'c_ok',
    });
    assert.strictEqual(okRes.success, true);
    assert.strictEqual(okRes.duplicate, false);
    assert.strictEqual(repo.getIngestCursor('acc_fail_cursor'), 'c_ok');

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 8: Atomic Rollback on Inbox Write Failure (CANARY 3)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Initial valid ingest established cursor C1
    repo.ingestMessage({
      accountId: 'acc_fail_inbox',
      platformMsgId: 'msg_init',
      channelId: 'chan_inbox_fail',
      content: '初始正常訊息',
      cursorValue: 'cursor_initial',
    });
    assert.strictEqual(repo.getIngestCursor('acc_fail_inbox'), 'cursor_initial');

    // Install abort trigger on inbox
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      rawDb.exec(`
        CREATE TRIGGER test_abort_inbox
        BEFORE INSERT ON inbox
        WHEN NEW.platform_msg_id = 'msg_fail'
        BEGIN
          SELECT RAISE(ABORT, 'Simulated inbox insertion failure');
        END;
      `);
    } finally {
      rawDb.close();
    }

    // Ingest fails due to inbox trigger
    assert.throws(
      () =>
        repo.ingestMessage({
          accountId: 'acc_fail_inbox',
          platformMsgId: 'msg_fail',
          channelId: 'chan_inbox_fail',
          content: '此訊息不可存入',
          cursorValue: 'cursor_advanced_fake',
        }),
      /Simulated inbox insertion failure/
    );

    // Cursor must NOT have advanced
    assert.strictEqual(repo.getIngestCursor('acc_fail_inbox'), 'cursor_initial');

    const cleanDb = new DatabaseSync(repo.databasePath);
    try {
      cleanDb.exec('DROP TRIGGER test_abort_inbox;');
    } finally {
      cleanDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 9: Restart Persistence (CANARY 11, 12)', () => {
  const harness = createTempHarness();
  try {
    let repo = SqliteStateRepository.open(harness.stateRoot);

    const r = repo.ingestMessage({
      accountId: 'acc_restart',
      platformMsgId: 'msg_persist_1',
      channelId: 'chan_restart',
      content: '跨實例重啟持久化測試',
      cursorValue: 'cursor_durable_777',
    });
    assert.strictEqual(r.success, true);
    assert.strictEqual(repo.getIngestCursor('acc_restart'), 'cursor_durable_777');

    repo.close();

    // Reopen repository fresh
    repo = SqliteStateRepository.open(harness.stateRoot);
    assert.strictEqual(repo.getIngestCursor('acc_restart'), 'cursor_durable_777');

    const state = repo.getChannelState('chan_restart');
    assert.strictEqual(state.backlogCount, 1);

    // Ingest duplicate on reopened repo
    const dupRes = repo.ingestMessage({
      accountId: 'acc_restart',
      platformMsgId: 'msg_persist_1',
      channelId: 'chan_restart',
      content: '嘗試覆寫',
      cursorValue: 'cursor_new_attempt',
    });
    assert.strictEqual(dupRes.duplicate, true);
    assert.strictEqual(repo.getIngestCursor('acc_restart'), 'cursor_durable_777');

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 10: Multi-Connection Dedupe (CANARY 13)', () => {
  const harness = createTempHarness();
  try {
    const repoA = SqliteStateRepository.open(harness.stateRoot);
    const repoB = SqliteStateRepository.open(harness.stateRoot);

    const resA = repoA.ingestMessage({
      accountId: 'acc_multi',
      platformMsgId: 'concurrent_msg',
      channelId: 'chan_multi',
      content: 'Connection A 訊息',
      cursorValue: 'cursor_A',
    });
    assert.strictEqual(resA.success, true);
    assert.strictEqual(resA.duplicate, false);

    const resB = repoB.ingestMessage({
      accountId: 'acc_multi',
      platformMsgId: 'concurrent_msg',
      channelId: 'chan_multi',
      content: 'Connection B 重複傳送',
      cursorValue: 'cursor_B',
    });
    assert.strictEqual(resB.success, true);
    assert.strictEqual(resB.duplicate, true);
    assert.strictEqual(resB.sequence, resA.sequence);

    assert.strictEqual(repoB.getIngestCursor('acc_multi'), 'cursor_A');

    repoA.close();
    repoB.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 11: T7B Integration & Backward Compatibility (CANARY 15)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // 1. Ingest two messages into channel
    const m1 = repo.ingestMessage({
      accountId: 'acc_tg_1',
      platformMsgId: 'msg_001',
      channelId: 'chan_e2e',
      content: '台股第一則訊息',
      cursorValue: 'c_1',
    });
    const m2 = repo.ingestMessage({
      accountId: 'acc_tg_1',
      platformMsgId: 'msg_002',
      channelId: 'chan_e2e',
      content: '台股第二則訊息',
      cursorValue: 'c_2',
    });

    // 2. Subsequent takeover acquires channel holder
    const takeover = repo.takeoverChannel('chan_e2e', 'agent_worker_1');
    assert.strictEqual(takeover.success, true);
    assert.strictEqual(takeover.fencingToken, 1);

    // 3. Claim messages in FIFO order (sequence ASC)
    const claimRes = repo.claimMessages('chan_e2e', 'agent_worker_1', 1, 10);
    assert.strictEqual(claimRes.success, true);
    assert.strictEqual(claimRes.claimedMessages.length, 2);
    assert.strictEqual(claimRes.claimedMessages[0].sequence, m1.sequence);
    assert.strictEqual(claimRes.claimedMessages[0].messageId, 'msg_001');
    assert.strictEqual(claimRes.claimedMessages[0].receivingAccountId, 'acc_tg_1');
    assert.strictEqual(claimRes.claimedMessages[0].status, 'claimed');
    assert.strictEqual(claimRes.claimedMessages[1].sequence, m2.sequence);
    assert.strictEqual(claimRes.claimedMessages[1].messageId, 'msg_002');
    assert.strictEqual(claimRes.remainingBacklogCount, 0);

    // 4. Validate reply authorization succeeds read-only
    const replyAuth = repo.validateReplyAuthorization(
      'chan_e2e',
      'agent_worker_1',
      1,
      'msg_001',
      'acc_tg_1'
    );
    assert.strictEqual(replyAuth.authorized, true);
    assert.strictEqual(replyAuth.messageId, 'msg_001');

    // 5. Expiry clears holder and marks claimed messages discarded
    const expireRes = repo.expireChannelHolder('chan_e2e');
    assert.strictEqual(expireRes.success, true);
    assert.strictEqual(expireRes.discardedMessages.length, 2);

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('T8B Test 12: Architectural Boundaries & Freeze Invariants (CANARY 16-20)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // CANARY 16: schema remains v3
    assert.strictEqual(repo.schemaVersion, 3);
    assert.strictEqual(SQLITE_STATE_SCHEMA_VERSION, 3);

    // CANARY 17: migrations remain [1, 2, 3]
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const versions = rawDb
        .prepare('SELECT version FROM schema_migrations ORDER BY version ASC;')
        .all()
        .map((r) => r.version);
      assert.deepStrictEqual(versions, [1, 2, 3]);

      // CANARY 20: no outbox table exists
      const tables = rawDb
        .prepare("SELECT name FROM sqlite_master WHERE type='table';")
        .all()
        .map((r) => r.name);
      assert.strictEqual(tables.includes('outbox'), false);
    } finally {
      rawDb.close();
    }

    // CANARY 18: no standalone advanceCursor method
    assert.strictEqual(typeof repo.advanceCursor, 'undefined');

    // CANARY 19: no account switching methods
    assert.strictEqual(typeof repo.switchAccount, 'undefined');
    assert.strictEqual(typeof repo.discardQueuedForAccount, 'undefined');

    repo.close();
  } finally {
    harness.cleanup();
  }
});
