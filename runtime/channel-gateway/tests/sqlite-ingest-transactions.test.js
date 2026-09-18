/**
 * runtime/channel-gateway/tests/sqlite-ingest-transactions.test.js
 *
 * ADR-0023 / ADR-0024 / v4-ingest: Channel Gateway Atomic Inbound Event + Message + Cursor Test Suite.
 *
 * Verifies:
 * 1. Input validation matrix for ingestMessage, recordIgnoredEvent, and getIngestCursor.
 * 2. Canonical inbound event + message + cursor write in a single immediate transaction (CANARY 1).
 * 3. Unattended channel initialization with holder=NULL, token=0 (CANARY 9, 10).
 * 4. Idempotent deduplication based on (account_id, platform_event_id) and zero-mutation on duplicate (CANARY 4, 5, 6, 7).
 * 5. Independent per-account cursors and same platform_msg_id across different accounts (CANARY 8, 22).
 * 6. Exact content preservation for Traditional Chinese, empty string, and newlines (CANARY 14).
 * 7. Deterministic rollback on cursor write failure (CANARY 2).
 * 8. Deterministic rollback on inbox write failure (CANARY 3).
 * 9. Restart persistence: message and cursor survive repository close and reopen (CANARY 11, 12).
 * 10. Multi-connection durable deduplication across independent repository handles (CANARY 13).
 * 11. T7B lifecycle integration: ingested queued messages claimed FIFO by subsequent holder (CANARY 15).
 * 12. Architectural boundaries and freeze invariants (CANARY 16, 17, 18, 19, 20).
 * 13. Event Dedup Canaries (Section 38).
 * 14. Same Logical Message / New Event Canary (Section 39).
 * 15. Cross-Channel Logical Conflict Canary (Section 40).
 * 16. Cursor Comparator Canaries (Section 41).
 * 17. LINE No-Cursor Canary (Section 42).
 * 18. IGNORED Event Canaries (Section 43).
 * 19. Legacy Invalid Cursor Canary (Section 44).
 * 20. Inbound Event Rollback Canary (Section 45).
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
      platformEventId: 'evt_001',
      platformMsgId: 'msg_100',
      channelId: 'chan_tw',
      content: '測試訊息',
      cursorValue: '100',
    };

    // accountId validation
    assert.throws(() => repo.ingestMessage({ ...validBase, accountId: '' }), /accountId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, accountId: '   ' }), /accountId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, accountId: null }), TypeError);
    assert.throws(() => repo.ingestMessage({ ...validBase, accountId: 123 }), TypeError);

    // platformEventId validation
    assert.throws(() => repo.ingestMessage({ ...validBase, platformEventId: undefined }), /platformEventId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, platformEventId: null }), /platformEventId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, platformEventId: '' }), /platformEventId/);
    assert.throws(() => repo.ingestMessage({ ...validBase, platformEventId: '   ' }), /platformEventId/);

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

    // cursorValue validation (Section 37 canaries)
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: undefined }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '   ' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: -1 }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '-1' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '+1' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '01' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '1.0' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: '1e3' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: ' 1 ' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: 'abc' }), /cursorValue/);
    assert.throws(() => repo.ingestMessage({ ...validBase, cursorValue: 1.5 }), /cursorValue/);

    // Valid cursor variants
    // null is valid (no-cursor capability)
    const nullCursorRes = repo.ingestMessage({ ...validBase, platformEventId: 'evt_null_cur', cursorValue: null });
    assert.strictEqual(nullCursorRes.cursorValue, null);
    assert.strictEqual(nullCursorRes.cursorAction, 'NONE');

    // safe integer number accepted and normalized to string
    const numCursorRes = repo.ingestMessage({ ...validBase, platformEventId: 'evt_num_cur', cursorValue: 42 });
    assert.strictEqual(numCursorRes.cursorValue, '42');

    // canonical decimal string accepted
    const decCursorRes = repo.ingestMessage({ ...validBase, platformEventId: 'evt_dec_cur', cursorValue: '123456789012345678901234567890' });
    assert.strictEqual(decCursorRes.cursorValue, '123456789012345678901234567890');

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
      platformEventId: 'evt_1001',
      platformMsgId: '1001',
      channelId: 'telegram_main',
      content: '台股加權指數收盤分析',
      cursorValue: '5001',
    });

    assert.strictEqual(res.success, true);
    assert.strictEqual(res.duplicate, false);
    assert.strictEqual(res.messageCreated, true);
    assert.strictEqual(typeof res.sequence, 'number');
    assert.strictEqual(res.sequence >= 1, true);
    assert.strictEqual(typeof res.eventSequence, 'number');
    assert.strictEqual(res.eventSequence >= 1, true);
    assert.strictEqual(res.channelId, 'telegram_main');
    assert.strictEqual(res.accountId, 'acc_tw_1');
    assert.strictEqual(res.platformEventId, 'evt_1001');
    assert.strictEqual(res.platformMsgId, '1001');
    assert.strictEqual(res.cursorValue, '5001');
    assert.strictEqual(res.cursorAction, 'ADVANCE');

    // Verify cursor readback matches
    assert.strictEqual(repo.getIngestCursor('acc_tw_1'), '5001');

    // Direct SQLite table inspection
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const eventRow = rawDb
        .prepare('SELECT event_sequence, account_id, platform_event_id, event_type, channel_id, platform_msg_id FROM inbound_event WHERE event_sequence = ?;')
        .get(res.eventSequence);
      assert.ok(eventRow);
      assert.strictEqual(eventRow.account_id, 'acc_tw_1');
      assert.strictEqual(eventRow.platform_event_id, 'evt_1001');
      assert.strictEqual(eventRow.event_type, 'MESSAGE');
      assert.strictEqual(eventRow.channel_id, 'telegram_main');
      assert.strictEqual(eventRow.platform_msg_id, '1001');

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
      assert.strictEqual(curRow.cursor_value, '5001');
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
      platformEventId: 'evt_99',
      platformMsgId: 'msg_99',
      channelId: 'unattended_chan_alpha',
      content: '無人值守測試訊息',
      cursorValue: '99',
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
      platformEventId: 'evt_100',
      platformMsgId: 'msg_100',
      channelId: 'unattended_chan_alpha',
      content: '無人值守第二則訊息',
      cursorValue: '100',
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

test('T8B Test 4: Idempotent Deduplication & Zero-Mutation No-Op (CANARY 4, 5, 6, 7, T8B-F1)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Initial ingest
    const firstRes = repo.ingestMessage({
      accountId: 'acc_dedupe_1',
      platformEventId: 'evt_alpha',
      platformMsgId: 'm_alpha',
      channelId: 'chan_primary',
      content: '原始訊息內容',
      cursorValue: '100',
    });
    assert.strictEqual(firstRes.success, true);
    assert.strictEqual(firstRes.duplicate, false);
    const originalSeq = firstRes.sequence;

    // Snapshot logical tables before duplicate call to verify strict zero-mutation
    const rawDb = new DatabaseSync(repo.databasePath);
    let beforeChannels;
    let beforeEvents;
    let beforeInbox;
    let beforeCursors;
    try {
      beforeChannels = rawDb.prepare('SELECT * FROM channel_control ORDER BY channel_id ASC;').all();
      beforeEvents = rawDb.prepare('SELECT * FROM inbound_event ORDER BY event_sequence ASC;').all();
      beforeInbox = rawDb.prepare('SELECT * FROM inbox ORDER BY sequence ASC;').all();
      beforeCursors = rawDb.prepare('SELECT * FROM ingest_cursor ORDER BY account_id ASC;').all();
    } finally {
      rawDb.close();
    }

    // Second ingest: same accountId and platformEventId and same target, but caller passes higher cursor and different content
    const secondRes = repo.ingestMessage({
      accountId: 'acc_dedupe_1',
      platformEventId: 'evt_alpha',
      platformMsgId: 'm_alpha',
      channelId: 'chan_primary',
      content: '重複傳送企圖竄改內容',
      cursorValue: '999',
    });

    assert.strictEqual(secondRes.success, true);
    assert.strictEqual(secondRes.duplicate, true);
    assert.strictEqual(secondRes.sequence, originalSeq);
    assert.strictEqual(secondRes.channelId, 'chan_primary');
    assert.strictEqual(secondRes.accountId, 'acc_dedupe_1');
    assert.strictEqual(secondRes.platformEventId, 'evt_alpha');
    assert.strictEqual(secondRes.platformMsgId, 'm_alpha');
    assert.strictEqual(secondRes.cursorAction, 'NOOP');

    // CRITICAL CANARY: cursor MUST NOT be updated on duplicate replay
    assert.strictEqual(repo.getIngestCursor('acc_dedupe_1'), '100');

    // Strong zero-mutation check: logical rows must be deep equal before and after duplicate call
    const rawDbAfter = new DatabaseSync(repo.databasePath);
    try {
      const afterChannels = rawDbAfter.prepare('SELECT * FROM channel_control ORDER BY channel_id ASC;').all();
      const afterEvents = rawDbAfter.prepare('SELECT * FROM inbound_event ORDER BY event_sequence ASC;').all();
      const afterInbox = rawDbAfter.prepare('SELECT * FROM inbox ORDER BY sequence ASC;').all();
      const afterCursors = rawDbAfter.prepare('SELECT * FROM ingest_cursor ORDER BY account_id ASC;').all();
      assert.deepStrictEqual(afterChannels, beforeChannels);
      assert.deepStrictEqual(afterEvents, beforeEvents);
      assert.deepStrictEqual(afterInbox, beforeInbox);
      assert.deepStrictEqual(afterCursors, beforeCursors);
    } finally {
      rawDbAfter.close();
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
      platformEventId: 'evt_A_1',
      platformMsgId: 'shared_msg_id',
      channelId: 'chan_1',
      content: '帳號 A 的訊息',
      cursorValue: '1',
    });
    assert.strictEqual(repo.getIngestCursor('account_A'), '1');

    repo.ingestMessage({
      accountId: 'account_A',
      platformEventId: 'evt_A_2',
      platformMsgId: 'second_msg_id',
      channelId: 'chan_1',
      content: '帳號 A 第二則訊息',
      cursorValue: '2',
    });
    assert.strictEqual(repo.getIngestCursor('account_A'), '2');

    // Account 2: same platform_msg_id 'shared_msg_id' as account 1 (CANARY 8)
    const resB = repo.ingestMessage({
      accountId: 'account_B',
      platformEventId: 'evt_B_100',
      platformMsgId: 'shared_msg_id',
      channelId: 'chan_1',
      content: '帳號 B 的訊息，相同平台編號',
      cursorValue: '100',
    });
    assert.strictEqual(resB.success, true);
    assert.strictEqual(resB.duplicate, false);

    // Distinct cursors preserved
    assert.strictEqual(repo.getIngestCursor('account_A'), '2');
    assert.strictEqual(repo.getIngestCursor('account_B'), '100');

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
      platformEventId: 'evt_tc',
      platformMsgId: 'msg_tc',
      channelId: 'chan_tc',
      content: traditionalChinese,
      cursorValue: '1',
    });
    const r2 = repo.ingestMessage({
      accountId: 'acc_content',
      platformEventId: 'evt_empty',
      platformMsgId: 'msg_empty',
      channelId: 'chan_tc',
      content: emptyContent,
      cursorValue: '2',
    });
    const r3 = repo.ingestMessage({
      accountId: 'acc_content',
      platformEventId: 'evt_multi',
      platformMsgId: 'msg_multi',
      channelId: 'chan_tc',
      content: multilineContent,
      cursorValue: '3',
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
          platformEventId: 'evt_fail_cursor',
          platformMsgId: 'msg_doomed_cursor',
          channelId: 'chan_rollback_test',
          content: '這則訊息應當被完整回滾',
          cursorValue: '1',
        }),
      /Simulated cursor write failure/
    );

    // Verify zero residual rows in inbound_event, inbox, ingest_cursor, and channel_control
    const checkDb = new DatabaseSync(repo.databasePath);
    try {
      const eventRows = checkDb
        .prepare('SELECT count(*) AS cnt FROM inbound_event WHERE account_id = ?;')
        .get('acc_fail_cursor');
      assert.strictEqual(eventRows.cnt, 0);

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
      platformEventId: 'evt_fail_cursor',
      platformMsgId: 'msg_doomed_cursor',
      channelId: 'chan_rollback_test',
      content: '重試成功',
      cursorValue: '1',
    });
    assert.strictEqual(okRes.success, true);
    assert.strictEqual(okRes.duplicate, false);
    assert.strictEqual(repo.getIngestCursor('acc_fail_cursor'), '1');

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
      platformEventId: 'evt_init',
      platformMsgId: 'msg_init',
      channelId: 'chan_inbox_fail',
      content: '初始正常訊息',
      cursorValue: '10',
    });
    assert.strictEqual(repo.getIngestCursor('acc_fail_inbox'), '10');

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
          platformEventId: 'evt_fail',
          platformMsgId: 'msg_fail',
          channelId: 'chan_inbox_fail',
          content: '此訊息不可存入',
          cursorValue: '20',
        }),
      /Simulated inbox insertion failure/
    );

    // Cursor must NOT have advanced, and inbound_event must not have residual row
    assert.strictEqual(repo.getIngestCursor('acc_fail_inbox'), '10');

    const cleanDb = new DatabaseSync(repo.databasePath);
    try {
      const evt = cleanDb.prepare('SELECT * FROM inbound_event WHERE platform_event_id = ?;').get('evt_fail');
      assert.strictEqual(evt, undefined);
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
      platformEventId: 'evt_persist_1',
      platformMsgId: 'msg_persist_1',
      channelId: 'chan_restart',
      content: '跨實例重啟持久化測試',
      cursorValue: '777',
    });
    assert.strictEqual(r.success, true);
    assert.strictEqual(repo.getIngestCursor('acc_restart'), '777');

    repo.close();

    // Reopen repository fresh
    repo = SqliteStateRepository.open(harness.stateRoot);
    assert.strictEqual(repo.getIngestCursor('acc_restart'), '777');

    const state = repo.getChannelState('chan_restart');
    assert.strictEqual(state.backlogCount, 1);

    // Ingest duplicate on reopened repo
    const dupRes = repo.ingestMessage({
      accountId: 'acc_restart',
      platformEventId: 'evt_persist_1',
      platformMsgId: 'msg_persist_1',
      channelId: 'chan_restart',
      content: '嘗試覆寫',
      cursorValue: '888',
    });
    assert.strictEqual(dupRes.duplicate, true);
    assert.strictEqual(repo.getIngestCursor('acc_restart'), '777');

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
      platformEventId: 'evt_concurrent',
      platformMsgId: 'concurrent_msg',
      channelId: 'chan_multi',
      content: 'Connection A 訊息',
      cursorValue: '10',
    });
    assert.strictEqual(resA.success, true);
    assert.strictEqual(resA.duplicate, false);

    const resB = repoB.ingestMessage({
      accountId: 'acc_multi',
      platformEventId: 'evt_concurrent',
      platformMsgId: 'concurrent_msg',
      channelId: 'chan_multi',
      content: 'Connection B 重複傳送',
      cursorValue: '20',
    });
    assert.strictEqual(resB.success, true);
    assert.strictEqual(resB.duplicate, true);
    assert.strictEqual(resB.sequence, resA.sequence);

    assert.strictEqual(repoB.getIngestCursor('acc_multi'), '10');

    // Exactly one inbound_event row
    const rawDb = new DatabaseSync(repoA.databasePath);
    try {
      const evtCount = rawDb.prepare('SELECT count(*) as cnt FROM inbound_event WHERE account_id = ?;').get('acc_multi');
      assert.strictEqual(evtCount.cnt, 1);
    } finally {
      rawDb.close();
    }

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
      platformEventId: 'evt_001',
      platformMsgId: 'msg_001',
      channelId: 'chan_e2e',
      content: '台股第一則訊息',
      cursorValue: '1',
    });
    const m2 = repo.ingestMessage({
      accountId: 'acc_tg_1',
      platformEventId: 'evt_002',
      platformMsgId: 'msg_002',
      channelId: 'chan_e2e',
      content: '台股第二則訊息',
      cursorValue: '2',
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

    // CANARY 16: schema is v4
    assert.strictEqual(repo.schemaVersion, 4);
    assert.strictEqual(SQLITE_STATE_SCHEMA_VERSION, 4);

    // CANARY 17: migrations are [1, 2, 3, 4]
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const versions = rawDb
        .prepare('SELECT version FROM schema_migrations ORDER BY version ASC;')
        .all()
        .map((r) => r.version);
      assert.deepStrictEqual(versions, [1, 2, 3, 4]);

      // CANARY 20: no outbox table exists, but inbound_event exists
      const tables = rawDb
        .prepare("SELECT name FROM sqlite_master WHERE type='table';")
        .all()
        .map((r) => r.name);
      assert.strictEqual(tables.includes('outbox'), false);
      assert.strictEqual(tables.includes('inbound_event'), true);
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

test('v4-ingest Test 13: Event Dedup Canaries (Section 38)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // A. Initial event
    const r1 = repo.ingestMessage({
      accountId: 'acc_dedup_canary',
      platformEventId: 'evt_canary_1',
      platformMsgId: 'msg_canary_1',
      channelId: 'chan_dedup',
      content: '第一次事件',
      cursorValue: '100',
    });
    assert.strictEqual(r1.duplicate, false);

    // Snapshot tables
    const rawDb = new DatabaseSync(repo.databasePath);
    let beforeEvents, beforeInbox, beforeCursors, beforeChannels;
    try {
      beforeEvents = rawDb.prepare('SELECT * FROM inbound_event;').all();
      beforeInbox = rawDb.prepare('SELECT * FROM inbox;').all();
      beforeCursors = rawDb.prepare('SELECT * FROM ingest_cursor;').all();
      beforeChannels = rawDb.prepare('SELECT * FROM channel_control;').all();
    } finally {
      rawDb.close();
    }

    // A & B. Second call with same event ID, same target, but larger cursor 200
    const r2 = repo.ingestMessage({
      accountId: 'acc_dedup_canary',
      platformEventId: 'evt_canary_1',
      platformMsgId: 'msg_canary_1',
      channelId: 'chan_dedup',
      content: '重播事件企圖推進游標',
      cursorValue: '200',
    });
    assert.strictEqual(r2.duplicate, true);
    assert.strictEqual(r2.cursorAction, 'NOOP');
    assert.strictEqual(repo.getIngestCursor('acc_dedup_canary'), '100', 'Replay must not advance cursor');

    // Verify zero mutation
    const rawDbAfter = new DatabaseSync(repo.databasePath);
    try {
      const afterEvents = rawDbAfter.prepare('SELECT * FROM inbound_event;').all();
      const afterInbox = rawDbAfter.prepare('SELECT * FROM inbox;').all();
      const afterCursors = rawDbAfter.prepare('SELECT * FROM ingest_cursor;').all();
      const afterChannels = rawDbAfter.prepare('SELECT * FROM channel_control;').all();
      assert.deepStrictEqual(afterEvents, beforeEvents);
      assert.deepStrictEqual(afterInbox, beforeInbox);
      assert.deepStrictEqual(afterCursors, beforeCursors);
      assert.deepStrictEqual(afterChannels, beforeChannels);
    } finally {
      rawDbAfter.close();
    }

    // C. Same account, same platformEventId, DIFFERENT platformMsgId -> EVENT_IDENTITY_CONFLICT
    assert.throws(
      () =>
        repo.ingestMessage({
          accountId: 'acc_dedup_canary',
          platformEventId: 'evt_canary_1',
          platformMsgId: 'msg_canary_DIFFERENT',
          channelId: 'chan_dedup',
          content: '衝突訊息',
          cursorValue: '300',
        }),
      /EVENT_IDENTITY_CONFLICT/
    );

    // D. Same platformEventId, DIFFERENT account -> independent and allowed
    const rDiffAcc = repo.ingestMessage({
      accountId: 'acc_dedup_DIFFERENT',
      platformEventId: 'evt_canary_1',
      platformMsgId: 'msg_canary_1',
      channelId: 'chan_dedup',
      content: '不同帳號的相同事件編號',
      cursorValue: '100',
    });
    assert.strictEqual(rDiffAcc.success, true);
    assert.strictEqual(rDiffAcc.duplicate, false);

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('v4-ingest Test 14: Same Logical Message / New Event Canary (Section 39)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Event E1 creates the logical message
    const r1 = repo.ingestMessage({
      accountId: 'acc_same_msg',
      platformEventId: 'evt_first',
      platformMsgId: 'msg_target_1',
      channelId: 'chan_msg_test',
      content: '原始訊息內文',
      cursorValue: '10',
    });
    assert.strictEqual(r1.duplicate, false);
    assert.strictEqual(r1.messageCreated, true);
    assert.strictEqual(repo.getIngestCursor('acc_same_msg'), '10');

    // Event E2: same account, same logical message M, same channel C, but NEW event ID
    const r2 = repo.ingestMessage({
      accountId: 'acc_same_msg',
      platformEventId: 'evt_second',
      platformMsgId: 'msg_target_1',
      channelId: 'chan_msg_test',
      content: '新事件內文（不應覆寫 inbox）',
      cursorValue: '20',
    });
    assert.strictEqual(r2.duplicate, false, 'New event ID must not be duplicate event');
    assert.strictEqual(r2.messageCreated, false, 'Logical message was already created');
    assert.strictEqual(r2.cursorAction, 'ADVANCE');
    assert.strictEqual(repo.getIngestCursor('acc_same_msg'), '20');

    // Direct SQLite check: 2 inbound_event rows, 1 inbox row, inbox original content preserved
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const eventRows = rawDb.prepare('SELECT * FROM inbound_event WHERE account_id = ?;').all('acc_same_msg');
      assert.strictEqual(eventRows.length, 2);

      const inboxRows = rawDb.prepare('SELECT * FROM inbox WHERE account_id = ?;').all('acc_same_msg');
      assert.strictEqual(inboxRows.length, 1);
      assert.strictEqual(inboxRows[0].content, '原始訊息內文', 'Original content must NOT be overwritten');
      assert.strictEqual(inboxRows[0].status, 'queued');
    } finally {
      rawDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('v4-ingest Test 15: Cross-Channel Logical Conflict Canary (Section 40)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Ingest under chan_1
    repo.ingestMessage({
      accountId: 'acc_cross_chan',
      platformEventId: 'evt_chan_1',
      platformMsgId: 'msg_conflict_target',
      channelId: 'chan_1',
      content: '通道1訊息',
      cursorValue: '10',
    });

    // Ingest with NEW event ID, same account, same msg_id, but DIFFERENT channel chan_2
    assert.throws(
      () =>
        repo.ingestMessage({
          accountId: 'acc_cross_chan',
          platformEventId: 'evt_chan_2',
          platformMsgId: 'msg_conflict_target',
          channelId: 'chan_2',
          content: '企圖移至通道2',
          cursorValue: '20',
        }),
      /LOGICAL_MESSAGE_CHANNEL_MISMATCH/
    );

    // Verify fail-closed: evt_chan_2 absent from inbound_event, cursor unchanged, chan_2 not created
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const evt2 = rawDb.prepare('SELECT * FROM inbound_event WHERE platform_event_id = ?;').get('evt_chan_2');
      assert.strictEqual(evt2, undefined);

      const chan2 = rawDb.prepare('SELECT * FROM channel_control WHERE channel_id = ?;').get('chan_2');
      assert.strictEqual(chan2, undefined);

      assert.strictEqual(repo.getIngestCursor('acc_cross_chan'), '10');
    } finally {
      rawDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('v4-ingest Test 16: Cursor Comparator Canaries (Section 41)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Initial state: cursor 10
    repo.ingestMessage({
      accountId: 'acc_cur_test',
      platformEventId: 'evt_c_1',
      platformMsgId: 'msg_c_1',
      channelId: 'chan_cur',
      content: '初始化游標 10',
      cursorValue: '10',
    });
    assert.strictEqual(repo.getIngestCursor('acc_cur_test'), '10');

    // CURSOR_ADVANCE_CANARY: candidate 11 > stored 10 -> ADVANCE
    const rAdv = repo.ingestMessage({
      accountId: 'acc_cur_test',
      platformEventId: 'evt_c_2',
      platformMsgId: 'msg_c_2',
      channelId: 'chan_cur',
      content: '推進游標至 11',
      cursorValue: '11',
    });
    assert.strictEqual(rAdv.cursorAction, 'ADVANCE');
    assert.strictEqual(repo.getIngestCursor('acc_cur_test'), '11');

    // CURSOR_EQUAL_NOOP_CANARY: new event candidate 11 == stored 11 -> NOOP
    const rNoop = repo.ingestMessage({
      accountId: 'acc_cur_test',
      platformEventId: 'evt_c_3',
      platformMsgId: 'msg_c_3',
      channelId: 'chan_cur',
      content: '相同游標 11',
      cursorValue: '11',
    });
    assert.strictEqual(rNoop.cursorAction, 'NOOP');
    assert.strictEqual(repo.getIngestCursor('acc_cur_test'), '11');

    // CURSOR_REGRESSION_CANARY: candidate 10 < stored 11 -> throws CURSOR_REGRESSION
    assert.throws(
      () =>
        repo.ingestMessage({
          accountId: 'acc_cur_test',
          platformEventId: 'evt_c_4',
          platformMsgId: 'msg_c_4',
          channelId: 'chan_cur',
          content: '回歸游標 10',
          cursorValue: '10',
        }),
      /CURSOR_REGRESSION/
    );

    // Verify event evt_c_4 absent and cursor remains 11
    assert.strictEqual(repo.getIngestCursor('acc_cur_test'), '11');
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const evt4 = rawDb.prepare('SELECT * FROM inbound_event WHERE platform_event_id = ?;').get('evt_c_4');
      assert.strictEqual(evt4, undefined);
    } finally {
      rawDb.close();
    }

    // Arbitrary-length decimal comparison canary (Section 41.1):
    // candidate with more digits > stored with fewer digits
    repo.ingestMessage({
      accountId: 'acc_big_num',
      platformEventId: 'evt_big_1',
      platformMsgId: 'msg_b_1',
      channelId: 'chan_cur',
      content: '大數游標 1',
      cursorValue: '999999999999999999999',
    });
    assert.strictEqual(repo.getIngestCursor('acc_big_num'), '999999999999999999999');

    const rBigAdv = repo.ingestMessage({
      accountId: 'acc_big_num',
      platformEventId: 'evt_big_2',
      platformMsgId: 'msg_b_2',
      channelId: 'chan_cur',
      content: '大數游標 2',
      cursorValue: '1000000000000000000000',
    });
    assert.strictEqual(rBigAdv.cursorAction, 'ADVANCE');
    assert.strictEqual(repo.getIngestCursor('acc_big_num'), '1000000000000000000000');

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('v4-ingest Test 17: LINE No-Cursor Canary (Section 42)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Ingest with cursorValue = null
    const res = repo.ingestMessage({
      accountId: 'line_user_01',
      platformEventId: 'line_evt_001',
      platformMsgId: 'line_msg_001',
      channelId: 'line_channel',
      content: 'LINE 訊息測試',
      cursorValue: null,
    });
    assert.strictEqual(res.success, true);
    assert.strictEqual(res.cursorValue, null);
    assert.strictEqual(res.cursorAction, 'NONE');

    // Record ignored event with cursorValue = null
    const ignRes = repo.recordIgnoredEvent({
      accountId: 'line_user_01',
      platformEventId: 'line_evt_ignored',
      cursorValue: null,
    });
    assert.strictEqual(ignRes.success, true);
    assert.strictEqual(ignRes.cursorValue, null);
    assert.strictEqual(ignRes.cursorAction, 'NONE');

    // DB verification: zero rows in ingest_cursor for line_user_01
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const curRow = rawDb.prepare('SELECT * FROM ingest_cursor WHERE account_id = ?;').get('line_user_01');
      assert.strictEqual(curRow, undefined, 'No ingest_cursor row must exist for no-cursor account');

      const evts = rawDb.prepare('SELECT * FROM inbound_event WHERE account_id = ?;').all('line_user_01');
      assert.strictEqual(evts.length, 2);
    } finally {
      rawDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('v4-ingest Test 18: IGNORED Event Canaries (Section 43)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // A. New ignored event + monotonic cursor -> durable IGNORED event + cursor ADVANCE
    const r1 = repo.recordIgnoredEvent({
      accountId: 'acc_tg_poll',
      platformEventId: 'evt_unsupported_1',
      cursorValue: '500',
    });
    assert.strictEqual(r1.success, true);
    assert.strictEqual(r1.duplicate, false);
    assert.strictEqual(r1.cursorAction, 'ADVANCE');
    assert.strictEqual(repo.getIngestCursor('acc_tg_poll'), '500');

    // D. Inbound event shape check: event_type = IGNORED, channel_id = NULL, platform_msg_id = NULL
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      const row = rawDb.prepare('SELECT * FROM inbound_event WHERE platform_event_id = ?;').get('evt_unsupported_1');
      assert.ok(row);
      assert.strictEqual(row.event_type, 'IGNORED');
      assert.strictEqual(row.channel_id, null);
      assert.strictEqual(row.platform_msg_id, null);
    } finally {
      rawDb.close();
    }

    // B. Same ignored event replay -> duplicate: true, zero mutation, no cursor advance
    const r2 = repo.recordIgnoredEvent({
      accountId: 'acc_tg_poll',
      platformEventId: 'evt_unsupported_1',
      cursorValue: '600',
    });
    assert.strictEqual(r2.duplicate, true);
    assert.strictEqual(r2.cursorAction, 'NOOP');
    assert.strictEqual(repo.getIngestCursor('acc_tg_poll'), '500');

    // C. Ignored new event + cursor regression -> fail closed
    assert.throws(
      () =>
        repo.recordIgnoredEvent({
          accountId: 'acc_tg_poll',
          platformEventId: 'evt_unsupported_2',
          cursorValue: '400',
        }),
      /CURSOR_REGRESSION/
    );
    assert.strictEqual(repo.getIngestCursor('acc_tg_poll'), '500');

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('v4-ingest Test 19: Legacy Invalid Stored Cursor Canary (Section 44)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Direct seed invalid legacy text into ingest_cursor
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      rawDb.prepare('INSERT INTO ingest_cursor (account_id, cursor_value) VALUES (?, ?);')
        .run('acc_legacy', 'legacy_cursor_text');
    } finally {
      rawDb.close();
    }

    // Cursor-enabled new event with canonical candidate must fail closed with STORED_CURSOR_INVALID
    assert.throws(
      () =>
        repo.ingestMessage({
          accountId: 'acc_legacy',
          platformEventId: 'evt_leg_1',
          platformMsgId: 'msg_leg_1',
          channelId: 'chan_legacy',
          content: '嘗試在損壞游標下入站',
          cursorValue: '100',
        }),
      /STORED_CURSOR_INVALID/
    );

    // Verify no event row inserted, no inbox mutation, cursor remains untouched
    const checkDb = new DatabaseSync(repo.databasePath);
    try {
      const curRow = checkDb.prepare('SELECT cursor_value FROM ingest_cursor WHERE account_id = ?;').get('acc_legacy');
      assert.strictEqual(curRow.cursor_value, 'legacy_cursor_text');

      const evtRow = checkDb.prepare('SELECT * FROM inbound_event WHERE account_id = ?;').get('acc_legacy');
      assert.strictEqual(evtRow, undefined);
    } finally {
      checkDb.close();
    }

    // No-cursor event on same account must SUCCEED without checking stored cursor
    const noCurRes = repo.ingestMessage({
      accountId: 'acc_legacy',
      platformEventId: 'evt_leg_nocur',
      platformMsgId: 'msg_leg_nocur',
      channelId: 'chan_legacy',
      content: '無游標入站不受損壞游標阻擋',
      cursorValue: null,
    });
    assert.strictEqual(noCurRes.success, true);
    assert.strictEqual(noCurRes.cursorAction, 'NONE');

    repo.close();
  } finally {
    harness.cleanup();
  }
});

test('v4-ingest Test 20: Inbound Event Rollback Canary (Section 45)', () => {
  const harness = createTempHarness();
  try {
    const repo = SqliteStateRepository.open(harness.stateRoot);

    // Install trigger on inbound_event to simulate failure during inbound_event insert
    const rawDb = new DatabaseSync(repo.databasePath);
    try {
      rawDb.exec(`
        CREATE TRIGGER test_abort_inbound_event
        BEFORE INSERT ON inbound_event
        WHEN NEW.platform_event_id = 'evt_abort'
        BEGIN
          SELECT RAISE(ABORT, 'Simulated inbound_event insertion failure');
        END;
      `);
    } finally {
      rawDb.close();
    }

    // Attempt ingest with evt_abort
    assert.throws(
      () =>
        repo.ingestMessage({
          accountId: 'acc_evt_abort',
          platformEventId: 'evt_abort',
          platformMsgId: 'msg_abort',
          channelId: 'chan_abort',
          content: '應完整回滾',
          cursorValue: '100',
        }),
      /Simulated inbound_event insertion failure/
    );

    // Verify zero mutation on inbox, channel_control, and ingest_cursor
    const checkDb = new DatabaseSync(repo.databasePath);
    try {
      const inboxRows = checkDb.prepare('SELECT count(*) as cnt FROM inbox WHERE account_id = ?;').get('acc_evt_abort');
      assert.strictEqual(inboxRows.cnt, 0);

      const chanRows = checkDb.prepare('SELECT count(*) as cnt FROM channel_control WHERE channel_id = ?;').get('chan_abort');
      assert.strictEqual(chanRows.cnt, 0);

      const curRows = checkDb.prepare('SELECT count(*) as cnt FROM ingest_cursor WHERE account_id = ?;').get('acc_evt_abort');
      assert.strictEqual(curRows.cnt, 0);

      checkDb.exec('DROP TRIGGER test_abort_inbound_event;');
    } finally {
      checkDb.close();
    }

    repo.close();
  } finally {
    harness.cleanup();
  }
});
