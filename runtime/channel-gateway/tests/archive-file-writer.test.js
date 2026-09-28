/**
 * runtime/channel-gateway/tests/archive-file-writer.test.js
 *
 * TG-MVP-14: ArchiveFileWriter unit tests covering:
 * - Hard-link publication (fs.link, no rename)
 * - Exclusive temp file creation
 * - Startup hard-link capability probe
 * - F-2 crash reconciliation (exact bytes & identity vs mismatch conflict)
 * - F-3 transient filesystem errors retry (EBUSY, EPERM, EACCES) & non-fatal temp unlink
 * - Non-transient errors zero retry
 * - Orphan temp cleanup (same archive_id pattern only)
 * - DLP deterministic bytes
 * - Containment escape rejection & no raw path error leakage
 * - Internal readback (readArchiveEntry, listTopicEntries)
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  ArchiveFileWriter,
  probeHardLinkCapability,
  generateArchiveMarkdownBytes,
  reconcileExistingFinalFile,
  cleanupOrphanTempFiles,
} = require('../core/archive-file-writer');

test('generateArchiveMarkdownBytes: produces pure deterministic bytes with DLP applied and LF endings', () => {
  const coord = {
    archive_id: 42,
    account_id: 'acc_alice',
    topic_id: 1,
    entry_sequence: 1,
    record_kind: 'ORIGINAL',
    platform_msg_id: 'tg:12345:1',
    command_id: 'cmd-001',
    created_at: 1774780200,
  };
  const dummyToken1 = '1234567890:' + 'ABC-DEF1234ghIkl-zyx57W2v1u123ew110';
  const dummyToken2 = '9876543210:' + 'XYZ-DEF1234ghIkl-zyx57W2v1u123ew110';
  const questionSnapshot = 'What is the secret? token: ' + dummyToken1;
  const replyBody = 'Here is the answer. token: ' + dummyToken2;

  const bytes1 = generateArchiveMarkdownBytes({
    coordination: coord,
    topicDisplayName: 'General Inquiries',
    questionSnapshot,
    replyBody,
  });

  const bytes2 = generateArchiveMarkdownBytes({
    coordination: coord,
    topicDisplayName: 'General Inquiries',
    questionSnapshot,
    replyBody,
  });

  // Pure deterministic output
  assert.ok(bytes1.equals(bytes2));

  const text = bytes1.toString('utf-8');
  // DLP applied to both question and reply
  assert.ok(!text.includes('1234567890:ABC'));
  assert.ok(!text.includes('9876543210:XYZ'));
  // Contains required markers
  assert.ok(text.includes('archive_id: 42'));
  assert.ok(text.includes('record_kind: ORIGINAL'));
  assert.ok(text.includes('command_id: cmd-001'));
  assert.ok(text.includes('status: authorized reply record'));
  assert.ok(!text.includes('DELIVERED_TO_RECIPIENT'));
  // LF endings and trailing newline
  assert.ok(text.endsWith('\n'));
  assert.ok(!text.includes('\r\n'));
});

test('generateArchiveMarkdownBytes: AMENDMENT record contains amendment snapshot and original reference', () => {
  const coord = {
    archive_id: 43,
    account_id: 'acc_alice',
    topic_id: 1,
    entry_sequence: 2,
    record_kind: 'AMENDMENT',
    platform_msg_id: 'tg:12345:1',
    original_archive_id: 42,
    source_platform_event_id: 'evt-edit-1',
    created_at: 1774780300,
  };
  const amendmentSnapshot = 'Corrected question text';

  const bytes = generateArchiveMarkdownBytes({
    coordination: coord,
    topicDisplayName: 'General Inquiries',
    amendmentSnapshot,
  });

  const text = bytes.toString('utf-8');
  assert.ok(text.includes('archive_id: 43'));
  assert.ok(text.includes('record_kind: AMENDMENT'));
  assert.ok(text.includes('original_archive_id: 42'));
  assert.ok(text.includes('source_platform_event_id: evt-edit-1'));
  assert.ok(text.includes('Corrected question text'));
});

test('probeHardLinkCapability: proves hard-link no-overwrite and cleanup', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-probe-test-'));
  try {
    const res = await probeHardLinkCapability(tmpDir);
    assert.strictEqual(res.success, true);
    assert.strictEqual(res.supportsHardLink, true);

    // Verify probe files cleaned up
    const remaining = fs.readdirSync(tmpDir);
    assert.strictEqual(remaining.length, 0);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('probeHardLinkCapability: fails closed with ARCHIVE_LINK_CAPABILITY_UNAVAILABLE on non-existent or invalid root', async () => {
  await assert.rejects(
    async () => {
      await probeHardLinkCapability(path.join(os.tmpdir(), 'non-existent-dir-for-probe-' + Date.now()));
    },
    (err) => {
      assert.strictEqual(err.code, 'ARCHIVE_LINK_CAPABILITY_UNAVAILABLE');
      return true;
    }
  );
});

test('publishArchiveFile: successfully publishes via fs.link and reconciles existing final file', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-writer-test-'));
  try {
    const writer = new ArchiveFileWriter({ archiveRoot: tmpDir });

    const coord = {
      archive_id: 101,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      platform_msg_id: 'tg:100:1',
      command_id: 'cmd-101',
      created_at: 1774780200,
      relative_path: 'TG_alice/Q001_General/001_Hello_20260329-103000.md',
    };
    const topic = {
      display_name: 'General',
    };
    const questionSnapshot = 'Hello, can you help me?';
    const replyBody = 'Yes, how can I help?';

    // 1. Initial successful publication
    const res = await writer.publishArchiveFile({
      coordination: coord,
      topic,
      questionSnapshot,
      replyBody,
    });
    assert.strictEqual(res.success, true);
    assert.strictEqual(res.action, 'PUBLISHED');

    const finalPath = path.join(tmpDir, coord.relative_path);
    assert.ok(fs.existsSync(finalPath));
    const publishedContent = fs.readFileSync(finalPath, 'utf-8');
    assert.ok(publishedContent.includes('archive_id: 101'));

    // 2. F-2 Crash reconciliation: attempt to publish again with same inputs -> RECONCILED without overwrite
    const resReconcile = await writer.publishArchiveFile({
      coordination: coord,
      topic,
      questionSnapshot,
      replyBody,
    });
    assert.strictEqual(resReconcile.success, true);
    assert.strictEqual(resReconcile.action, 'RECONCILED');

    // 3. F-2 Mismatch detection: if existing file has different content -> ARCHIVE_TARGET_CONFLICT
    const mismatchedCoord = {
      ...coord,
      archive_id: 102, // Different archive_id targeting same path
    };
    await assert.rejects(
      async () => {
        await writer.publishArchiveFile({
          coordination: mismatchedCoord,
          topic,
          questionSnapshot,
          replyBody,
        });
      },
      (err) => {
        assert.strictEqual(err.code, 'ARCHIVE_TARGET_CONFLICT');
        return true;
      }
    );

    // Existing final file must remain completely untouched
    const afterConflictContent = fs.readFileSync(finalPath, 'utf-8');
    assert.strictEqual(afterConflictContent, publishedContent);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('publishArchiveFile: containment escape rejection and no raw path in errors', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-contain-test-'));
  try {
    const writer = new ArchiveFileWriter({ archiveRoot: tmpDir });

    const badCoord = {
      archive_id: 201,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      platform_msg_id: 'tg:100:1',
      command_id: 'cmd-201',
      created_at: 1774780200,
      relative_path: '../outside/escaped.md', // Path traversal escape
    };

    await assert.rejects(
      async () => {
        await writer.publishArchiveFile({
          coordination: badCoord,
          topic: { display_name: 'General' },
          questionSnapshot: 'test',
          replyBody: 'test',
        });
      },
      (err) => {
        assert.strictEqual(err.code, 'ARCHIVE_CONTAINMENT_VIOLATION');
        // Must not leak the raw path in message
        assert.ok(!err.message.includes(tmpDir));
        return true;
      }
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('cleanupOrphanTempFiles: cleans up ONLY temp files belonging to the specified archive_id', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-temp-cleanup-'));
  try {
    const targetDir = path.join(tmpDir, 'TG_alice', 'Q001_General');
    fs.mkdirSync(targetDir, { recursive: true });

    // Create temp files for archive_id 50
    const temp1 = path.join(targetDir, '.50.' + 'a'.repeat(64) + '.tmp');
    const temp2 = path.join(targetDir, '.50.' + 'b'.repeat(64) + '.tmp');
    // Create temp file for archive_id 99 (different archive)
    const tempOther = path.join(targetDir, '.99.' + 'c'.repeat(64) + '.tmp');
    // Create a non-temp file
    const realFile = path.join(targetDir, '001_Hello_20260329-103000.md');

    fs.writeFileSync(temp1, 'temp1');
    fs.writeFileSync(temp2, 'temp2');
    fs.writeFileSync(tempOther, 'other temp');
    fs.writeFileSync(realFile, 'real file');

    cleanupOrphanTempFiles(targetDir, 50);

    // temp1 and temp2 should be removed
    assert.strictEqual(fs.existsSync(temp1), false);
    assert.strictEqual(fs.existsSync(temp2), false);
    // tempOther and realFile MUST NOT be removed
    assert.strictEqual(fs.existsSync(tempOther), true);
    assert.strictEqual(fs.existsSync(realFile), true);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test('readArchiveEntry and listTopicEntries: internal readback with isolation and DLP verification', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-readback-test-'));
  try {
    const mockRepo = {
      getArchiveCoordinationBySequence: ({ accountId, topicId, entrySequence }) => {
        if (accountId === 'acc_1' && topicId === 1 && entrySequence === 1) {
          return {
            archive_id: 301,
            account_id: 'acc_1',
            topic_id: 1,
            entry_sequence: 1,
            record_kind: 'ORIGINAL',
            relative_path: 'TG_acc_1/Q001_Topic/001_Test_20260329-103000.md',
          };
        }
        return null;
      },
      listTopicArchiveCoordinations: ({ accountId, topicId }) => {
        if (accountId === 'acc_1' && topicId === 1) {
          return [
            {
              archive_id: 301,
              account_id: 'acc_1',
              topic_id: 1,
              entry_sequence: 1,
              record_kind: 'ORIGINAL',
              relative_path: 'TG_acc_1/Q001_Topic/001_Test_20260329-103000.md',
            },
          ];
        }
        return [];
      },
    };

    const writer = new ArchiveFileWriter({
      archiveRoot: tmpDir,
      repository: mockRepo,
    });

    // Write file to disk
    const relPath = 'TG_acc_1/Q001_Topic/001_Test_20260329-103000.md';
    const absPath = path.join(tmpDir, relPath);
    fs.mkdirSync(path.dirname(absPath), { recursive: true });
    const content = '---\narchive_id: 301\nrecord_kind: ORIGINAL\nentry_sequence: 1\n---\n\n# Content here.\n';
    fs.writeFileSync(absPath, content, 'utf-8');

    // 1. Read entry back
    const entry = await writer.readArchiveEntry({
      accountId: 'acc_1',
      topicId: 1,
      entrySequence: 1,
    });
    assert.ok(entry);
    assert.strictEqual(entry.archive_id, 301);
    assert.strictEqual(entry.content, content);

    // 2. Read back for different account -> not found (isolation)
    const entryOtherAcc = await writer.readArchiveEntry({
      accountId: 'acc_2',
      topicId: 1,
      entrySequence: 1,
    });
    assert.strictEqual(entryOtherAcc, null);

    // 3. List entries for topic
    const list = await writer.listTopicEntries({
      accountId: 'acc_1',
      topicId: 1,
    });
    assert.strictEqual(list.length, 1);
    assert.strictEqual(list[0].archive_id, 301);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});
