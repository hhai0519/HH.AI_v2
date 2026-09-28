/**
 * runtime/channel-gateway/tests/topic-manager.test.js
 *
 * TG-MVP-14: Topic normalization, safe segment formatting, directory collision,
 * path budget validation, and TopicManager startup tests.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  normalizeTopicName,
  cleanDisplayName,
  toSafeFilenameSegment,
  formatAccountDirName,
  formatTopicDirName,
  deriveSummarySafeSegment,
  formatTimestamp,
  formatEntryFileName,
  computeRelativePath,
  validatePathBudget,
  TopicManager,
} = require('../core/topic-manager');

test('normalizeTopicName: applies NFKC, whitespace collapse, trimming, and lowercase', () => {
  // NFKC compatibility normalization (e.g. full-width characters, ligature)
  const fullWidth = 'Ｔｅｓｔ　Ｔｏｐｉｃ';
  assert.strictEqual(normalizeTopicName(fullWidth), 'test topic');

  // Whitespace collapse (multiple spaces, tabs, unicode spaces to single ASCII space)
  const messySpaces = '  hello \t\t  world  \u3000 again   ';
  assert.strictEqual(normalizeTopicName(messySpaces), 'hello world again');

  // Case normalization (locale-independent lowercase)
  const mixedCase = 'HeLLo WoRLd';
  assert.strictEqual(normalizeTopicName(mixedCase), 'hello world');

  // Non-empty requirement
  assert.throws(() => normalizeTopicName(''), /INVALID_TOPIC_NAME/);
  assert.throws(() => normalizeTopicName('   '), /INVALID_TOPIC_NAME/);
  assert.throws(() => normalizeTopicName(null), /INVALID_TOPIC_NAME/);
});

test('cleanDisplayName: preserves display casing and trims whitespace', () => {
  const display = '  My Important Topic   ';
  assert.strictEqual(cleanDisplayName(display), 'My Important Topic');
});

test('toSafeFilenameSegment: Windows-safe chars, surrogate-pair safety, and reserved basenames', () => {
  // Replaces Windows invalid chars <>:"/\\|?* with _
  const invalidChars = 'foo<bar>baz:qux"dir/path\\pipe|question?star*';
  const safe = toSafeFilenameSegment(invalidChars, 100);
  assert.strictEqual(safe, 'foo_bar_baz_qux_dir_path_pipe_question_star_');

  // Trims trailing dots and spaces
  assert.strictEqual(toSafeFilenameSegment('trailing. ', 50), 'trailing');

  // Windows reserved basenames prefixed with _
  for (const reserved of ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'LPT9', 'con', 'aux']) {
    const res = toSafeFilenameSegment(reserved, 50);
    assert.strictEqual(res, `_${reserved}`);
  }

  // Surrogate pair safety when truncating
  // Emoji \uD83D\uDE00 (grinning face) is 2 UTF-16 code units
  const withEmoji = 'abc' + '\uD83D\uDE00' + 'def';
  // If maxLen cuts between the high surrogate and low surrogate:
  // 'abc' is 3 units, high surrogate is unit 4, low surrogate is unit 5.
  // maxLen = 4 would cut the surrogate pair. It should back up to 3 units: 'abc'.
  const truncatedSafe = toSafeFilenameSegment(withEmoji, 4);
  assert.strictEqual(truncatedSafe, 'abc');
  assert.strictEqual(truncatedSafe.length, 3);
});

test('formatAccountDirName: prefixes TG_ and caps at 35 code units', () => {
  const dirName = formatAccountDirName('main_bot', 'tg-12345');
  assert.strictEqual(dirName, 'TG_main_bot');

  // Fallback to accountId if label is empty
  const fallbackDir = formatAccountDirName('', '12345');
  assert.strictEqual(fallbackDir, 'TG_12345');

  // Enforces max 35 units total (TG_ + 32)
  const longLabel = 'a'.repeat(50);
  const truncated = formatAccountDirName(longLabel, 'acc-1');
  assert.ok(truncated.startsWith('TG_'));
  assert.strictEqual(truncated.length, 35);
});

test('formatTopicDirName: formats Q<sequence>_<safe-name> with min 3 digits', () => {
  assert.strictEqual(formatTopicDirName(1, 'General'), 'Q001_General');
  assert.strictEqual(formatTopicDirName(42, 'Tech Support'), 'Q042_Tech Support');
  assert.strictEqual(formatTopicDirName(1000, 'Large'), 'Q1000_Large');

  // Truncation <= 48 code units
  const longName = 'z'.repeat(100);
  const formatted = formatTopicDirName(1, longName);
  assert.ok(formatted.length <= 48);
  assert.ok(formatted.startsWith('Q001_'));
});

test('deriveSummarySafeSegment: DLP sanitization, normalization and fallback', () => {
  // Normal question
  const summary = deriveSummarySafeSegment('What is the weather today?');
  assert.ok(summary.startsWith('What is the weather today'));

  // DLP sanitization (e.g. prompt contains token)
  const sensitive = deriveSummarySafeSegment('My bot token is 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11');
  assert.ok(!sensitive.includes('123456:ABC'));

  // Empty or unusable fallback
  assert.strictEqual(deriveSummarySafeSegment('???:::***'), '訊息');
  assert.strictEqual(deriveSummarySafeSegment(''), '訊息');
  assert.strictEqual(deriveSummarySafeSegment(null), '訊息');
});

test('formatEntryFileName and computeRelativePath: min 3 digits, UTC time, correct hierarchy', () => {
  const timeSec = 1774780200; // 2026-03-29T10:30:00Z
  const timeFormatted = formatTimestamp(timeSec);
  assert.strictEqual(timeFormatted, '20260329-103000');

  const entryName = formatEntryFileName({
    entrySequence: 5,
    summarySafeSegment: 'Help_Request',
    createdTimeSec: timeSec,
  });
  assert.strictEqual(entryName, '005_Help_Request_20260329-103000.md');

  // Sequence >= 1000
  const largeEntryName = formatEntryFileName({
    entrySequence: 1005,
    summarySafeSegment: 'Help_Request',
    createdTimeSec: timeSec,
  });
  assert.strictEqual(largeEntryName, '1005_Help_Request_20260329-103000.md');

  // Relative path calculation
  const relPath = computeRelativePath({
    accountDirName: 'TG_alice',
    topicDirName: 'Q001_General',
    entryFileName: '001_Hello_20260329-103000.md',
  });
  assert.strictEqual(relPath, 'TG_alice/Q001_General/001_Hello_20260329-103000.md');
});

test('validatePathBudget: fails closed if resolved path exceeds 240 units', () => {
  const shortDir = 'C:\\short\\path';
  assert.strictEqual(validatePathBudget(shortDir), true);

  // Exceeds budget
  const hugeDir = 'C:\\' + 'x'.repeat(200);
  assert.throws(() => validatePathBudget(hugeDir), /ARCHIVE_PATH_BUDGET_EXCEEDED/);
});

test('TopicManager.validateStartup: detects account dir collisions and label drift', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-topic-mgr-'));
  try {
    // 1. Account directory collision between two distinct accounts
    const fakeCollisionRegistry = {
      list: () => [
        { id: 'acc1', label: 'same_label' },
        { id: 'acc2', label: 'same_label' },
      ],
    };
    const mockRepo = {
      getAllAccountArchiveTopics: () => [],
    };
    assert.throws(
      () =>
        TopicManager.validateStartup({
          repository: mockRepo,
          accountRegistry: fakeCollisionRegistry,
          archiveRoot: tmpDir,
        }),
      /ARCHIVE_ACCOUNT_DIR_COLLISION/
    );

    // 2. Label drift: existing DB topic has different account_dir_name from current config
    const fakeDriftRegistry = {
      list: () => [{ id: 'acc1', label: 'new_label' }],
    };
    const mockDriftRepo = {
      getAllAccountArchiveTopics: () => [
        {
          account_id: 'acc1',
          account_dir_name: 'TG_old_label',
        },
      ],
    };
    assert.throws(
      () =>
        TopicManager.validateStartup({
          repository: mockDriftRepo,
          accountRegistry: fakeDriftRegistry,
          archiveRoot: tmpDir,
        }),
      /ARCHIVE_ACCOUNT_DIR_DRIFT/
    );

    // 3. Normal startup success
    const fakeGoodRegistry = {
      list: () => [{ id: 'acc1', label: 'alice_bot' }],
    };
    const mockGoodRepo = {
      getAllAccountArchiveTopics: () => [
        {
          account_id: 'acc1',
          account_dir_name: 'TG_alice_bot',
        },
      ],
    };
    assert.doesNotThrow(() =>
      TopicManager.validateStartup({
        repository: mockGoodRepo,
        accountRegistry: fakeGoodRegistry,
        archiveRoot: tmpDir,
      })
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});
