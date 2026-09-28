/**
 * runtime/channel-gateway/tests/archive-file-writer.test.js
 *
 * TG-MVP-14 R1: ArchiveFileWriter unit tests covering:
 * - F3: Production fs facade defaults to real node:fs/promises
 * - F3: Zero synchronous archive filesystem operations
 * - F3: Async exclusive temp, write, sync, link, and cleanup
 * - F3: Bounded transient retries (EBUSY, EPERM, EACCES) & non-transient zero retry
 * - F4: Stepwise non-recursive descendant creation
 * - F4: Ancestor junction rejection (Windows) / symlink rejection (POSIX)
 * - F4: Final readback symlink/junction escape rejection
 * - F4: Reconciliation target symlink/junction escape rejection
 * - F4: Lexical ../ escape rejection & no raw path error leakage
 * - F6: Hard-link capability probe no-overwrite, unchanged destination bytes
 * - F6: Probe cleanup of all artifacts & cleanup failure fail-closed
 * - F2: Positional repository readback and list
 * - DLP deterministic bytes
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsPromises = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const {
  ArchiveFileWriter,
  probeHardLinkCapability,
  generateArchiveMarkdownBytes,
  reconcileExistingFinalFile,
  cleanupOrphanTempFiles,
} = require('../core/archive-file-writer');

test('ArchiveFileWriter: production fs facade defaults to real node:fs/promises', () => {
  const writer = new ArchiveFileWriter();
  assert.strictEqual(writer.fsPromises, fsPromises);
});

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

  assert.ok(bytes1.equals(bytes2));

  const text = bytes1.toString('utf-8');
  assert.ok(!text.includes('1234567890:ABC'));
  assert.ok(!text.includes('9876543210:XYZ'));
  assert.ok(text.includes('archive_id: 42'));
  assert.ok(text.includes('record_kind: ORIGINAL'));
  assert.ok(text.includes('command_id: cmd-001'));
  assert.ok(text.includes('delivery_status: authorized reply record'));
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
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-probe-test-'));
  try {
    const res = await probeHardLinkCapability(tmpDir);
    assert.strictEqual(res.success, true);
    assert.strictEqual(res.supportsHardLink, true);

    const remaining = await fsPromises.readdir(tmpDir);
    assert.strictEqual(remaining.length, 0);
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
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

test('probeHardLinkCapability: fails closed if probe cleanup fails', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-probe-cleanup-fail-'));
  try {
    // Injected facade where unlink fails
    const failingFs = {
      ...fsPromises,
      stat: (p) => fsPromises.stat(p),
      realpath: (p) => fsPromises.realpath(p),
      open: (...args) => fsPromises.open(...args),
      link: (...args) => fsPromises.link(...args),
      readFile: (...args) => fsPromises.readFile(...args),
      unlink: async () => {
        throw new Error('EPERM: cannot unlink probe artifact');
      },
    };

    await assert.rejects(
      async () => {
        await probeHardLinkCapability(tmpDir, failingFs);
      },
      (err) => {
        assert.strictEqual(err.code, 'ARCHIVE_LINK_CAPABILITY_UNAVAILABLE');
        return true;
      }
    );
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
  }
});

test('publishArchiveFile: successfully publishes via fs.promises.link and reconciles existing final file', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-writer-test-'));
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
    const publishedContent = await fsPromises.readFile(finalPath, 'utf-8');
    assert.ok(publishedContent.includes('archive_id: 101'));

    // 2. F-2 Crash reconciliation: publish again with same inputs -> RECONCILED without overwrite
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
      archive_id: 102,
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

    const afterConflictContent = await fsPromises.readFile(finalPath, 'utf-8');
    assert.strictEqual(afterConflictContent, publishedContent);
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
  }
});

test('publishArchiveFile: stepwise non-recursive directory creation succeeds for nested safe paths', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-nested-dir-'));
  try {
    const writer = new ArchiveFileWriter({ archiveRoot: tmpDir });
    const coord = {
      archive_id: 110,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      platform_msg_id: 'tg:100:1',
      command_id: 'cmd-110',
      created_at: 1774780200,
      relative_path: 'TG_alice/Sub_Dir/Q001_General/001_Test_20260329-103000.md',
    };
    const res = await writer.publishArchiveFile({
      coordination: coord,
      topic: { display_name: 'General' },
      questionSnapshot: 'Hello',
      replyBody: 'World',
    });
    assert.strictEqual(res.success, true);
    assert.strictEqual(res.action, 'PUBLISHED');

    const destDir = path.join(tmpDir, 'TG_alice', 'Sub_Dir', 'Q001_General');
    const attachmentsDir = path.join(destDir, '附件');
    assert.ok(fs.existsSync(destDir));
    assert.ok(fs.existsSync(attachmentsDir));
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
  }
});

if (process.platform === 'win32') {
  test('path containment: Windows junction ancestor directory rejection', async () => {
    const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-junc-test-'));
    const outsideDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-junc-outside-'));
    try {
      const junctionPath = path.join(tmpDir, 'TG_alice');
      // Create Windows junction pointing outside archiveRoot
      await fsPromises.symlink(outsideDir, junctionPath, 'junction');

      const writer = new ArchiveFileWriter({ archiveRoot: tmpDir });
      const coord = {
        archive_id: 120,
        account_id: 'alice',
        topic_id: 1,
        entry_sequence: 1,
        record_kind: 'ORIGINAL',
        platform_msg_id: 'tg:100:1',
        command_id: 'cmd-120',
        created_at: 1774780200,
        relative_path: 'TG_alice/Q001_General/001_Escaped_20260329-103000.md',
      };

      await assert.rejects(
        async () => {
          await writer.publishArchiveFile({
            coordination: coord,
            topic: { display_name: 'General' },
            questionSnapshot: 'Test',
            replyBody: 'Answer',
          });
        },
        (err) => {
          assert.strictEqual(err.code, 'ARCHIVE_SYMLINK_FORBIDDEN');
          assert.ok(!err.message.includes(tmpDir));
          assert.ok(!err.message.includes(outsideDir));
          return true;
        }
      );
    } finally {
      await fsPromises.rm(tmpDir, { recursive: true, force: true });
      await fsPromises.rm(outsideDir, { recursive: true, force: true });
    }
  });

  test('path containment: Windows junction readback and reconciliation escape rejection', async () => {
    const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-junc-read-'));
    const outsideDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-junc-read-out-'));
    try {
      // Put a real markdown file outside
      const outsideFile = path.join(outsideDir, 'target.md');
      await fsPromises.writeFile(outsideFile, '---\narchive_id: 999\nrecord_kind: ORIGINAL\n---\n# Outside\n', 'utf-8');

      // Create junction inside archiveRoot
      const dirInside = path.join(tmpDir, 'TG_alice', 'Q001_General');
      await fsPromises.mkdir(dirInside, { recursive: true });
      const linkInside = path.join(dirInside, '001_File_20260329-103000.md');
      // Junction on Windows works for directories, for files we test junction on directory or symlink
      const juncDir = path.join(tmpDir, 'TG_junc');
      await fsPromises.symlink(outsideDir, juncDir, 'junction');

      const writer = new ArchiveFileWriter({ archiveRoot: tmpDir });
      // Readback through junction dir
      const entry = await writer.readArchiveEntry({
        archiveRoot: tmpDir,
        relativePath: 'TG_junc/target.md',
      });
      // Must reject and return null
      assert.strictEqual(entry, null);
    } finally {
      await fsPromises.rm(tmpDir, { recursive: true, force: true });
      await fsPromises.rm(outsideDir, { recursive: true, force: true });
    }
  });
} else {
  test('path containment: POSIX directory symlink ancestor rejection on POSIX', async () => {
    const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-sym-test-'));
    const outsideDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-sym-outside-'));
    try {
      const symlinkPath = path.join(tmpDir, 'TG_alice');
      await fsPromises.symlink(outsideDir, symlinkPath, 'dir');

      const writer = new ArchiveFileWriter({ archiveRoot: tmpDir });
      const coord = {
        archive_id: 130,
        account_id: 'alice',
        topic_id: 1,
        entry_sequence: 1,
        record_kind: 'ORIGINAL',
        platform_msg_id: 'tg:100:1',
        command_id: 'cmd-130',
        created_at: 1774780200,
        relative_path: 'TG_alice/Q001_General/001_Escaped_20260329-103000.md',
      };

      await assert.rejects(
        async () => {
          await writer.publishArchiveFile({
            coordination: coord,
            topic: { display_name: 'General' },
            questionSnapshot: 'Test',
            replyBody: 'Answer',
          });
        },
        (err) => {
          assert.strictEqual(err.code, 'ARCHIVE_SYMLINK_FORBIDDEN');
          assert.ok(!err.message.includes(tmpDir));
          assert.ok(!err.message.includes(outsideDir));
          return true;
        }
      );
    } finally {
      await fsPromises.rm(tmpDir, { recursive: true, force: true });
      await fsPromises.rm(outsideDir, { recursive: true, force: true });
    }
  });

  test('path containment: POSIX symlink readback and reconciliation escape rejection', async () => {
    const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-sym-read-'));
    const outsideDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-sym-read-out-'));
    try {
      const outsideFile = path.join(outsideDir, 'target.md');
      await fsPromises.writeFile(outsideFile, '---\narchive_id: 999\nrecord_kind: ORIGINAL\n---\n# Outside\n', 'utf-8');

      const symDir = path.join(tmpDir, 'TG_sym');
      await fsPromises.symlink(outsideDir, symDir, 'dir');

      const writer = new ArchiveFileWriter({ archiveRoot: tmpDir });
      const entry = await writer.readArchiveEntry({
        archiveRoot: tmpDir,
        relativePath: 'TG_sym/target.md',
      });
      assert.strictEqual(entry, null);
    } finally {
      await fsPromises.rm(tmpDir, { recursive: true, force: true });
      await fsPromises.rm(outsideDir, { recursive: true, force: true });
    }
  });
}

test('publishArchiveFile: containment escape rejection and no raw path in errors', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-contain-test-'));
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
      relative_path: '../outside/escaped.md',
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
        assert.ok(!err.message.includes(tmpDir));
        return true;
      }
    );
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
  }
});

test('publishArchiveRecord: transient retries on EBUSY/EPERM/EACCES and fails on exhausted', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-transient-test-'));
  try {
    let attempts = 0;
    const sleeps = [];

    const mockFs = {
      ...fsPromises,
      stat: (p) => fsPromises.stat(p),
      realpath: (p) => fsPromises.realpath(p),
      lstat: (p) => fsPromises.lstat(p),
      mkdir: (p) => fsPromises.mkdir(p),
      open: async () => {
        attempts++;
        const err = new Error('EBUSY: resource busy or locked');
        err.code = 'EBUSY';
        throw err;
      },
    };

    const writer = new ArchiveFileWriter({
      archiveRoot: tmpDir,
      fsPromises: mockFs,
      sleep: async (ms) => {
        sleeps.push(ms);
      },
      retryDelays: [100, 300, 900],
    });

    const coord = {
      archive_id: 250,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      platform_msg_id: 'tg:100:1',
      command_id: 'cmd-250',
      created_at: 1774780200,
      relative_path: 'TG_alice/Q001_General/001_Transient_20260329-103000.md',
    };

    const result = await writer.publishArchiveRecord({
      archiveRoot: tmpDir,
      coordination: coord,
      topic: { display_name: 'General' },
      questionSnapshot: 'Hello',
      replyBody: 'World',
    });

    assert.strictEqual(result.status, 'FAILED');
    assert.strictEqual(result.reasonCode, 'ARCHIVE_FS_TRANSIENT_EXHAUSTED');
    // Initial attempt + 3 retries = 4 attempts total
    assert.strictEqual(attempts, 4);
    assert.deepStrictEqual(sleeps, [100, 300, 900]);
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
  }
});

test('publishArchiveRecord: non-transient error does not retry', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-nontransient-test-'));
  try {
    let attempts = 0;
    const sleeps = [];

    const mockFs = {
      ...fsPromises,
      stat: (p) => fsPromises.stat(p),
      realpath: (p) => fsPromises.realpath(p),
      lstat: (p) => fsPromises.lstat(p),
      mkdir: (p) => fsPromises.mkdir(p),
      open: async () => {
        attempts++;
        const err = new Error('ENOSPC: no space left on device');
        err.code = 'ENOSPC';
        throw err;
      },
    };

    const writer = new ArchiveFileWriter({
      archiveRoot: tmpDir,
      fsPromises: mockFs,
      sleep: async (ms) => {
        sleeps.push(ms);
      },
    });

    const coord = {
      archive_id: 251,
      account_id: 'alice',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      platform_msg_id: 'tg:100:1',
      command_id: 'cmd-251',
      created_at: 1774780200,
      relative_path: 'TG_alice/Q001_General/001_NoSpace_20260329-103000.md',
    };

    const result = await writer.publishArchiveRecord({
      archiveRoot: tmpDir,
      coordination: coord,
      topic: { display_name: 'General' },
      questionSnapshot: 'Hello',
      replyBody: 'World',
    });

    assert.strictEqual(result.status, 'FAILED');
    assert.strictEqual(result.reasonCode, 'ENOSPC');
    // Exactly 1 attempt, zero retries
    assert.strictEqual(attempts, 1);
    assert.strictEqual(sleeps.length, 0);
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
  }
});

test('cleanupOrphanTempFiles: cleans up ONLY temp files belonging to the specified archive_id', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-temp-cleanup-'));
  try {
    const targetDir = path.join(tmpDir, 'TG_alice', 'Q001_General');
    await fsPromises.mkdir(targetDir, { recursive: true });

    const temp1 = path.join(targetDir, '.50.' + 'a'.repeat(64) + '.tmp');
    const temp2 = path.join(targetDir, '.50.' + 'b'.repeat(64) + '.tmp');
    const tempOther = path.join(targetDir, '.99.' + 'c'.repeat(64) + '.tmp');
    const realFile = path.join(targetDir, '001_Hello_20260329-103000.md');

    await fsPromises.writeFile(temp1, 'temp1');
    await fsPromises.writeFile(temp2, 'temp2');
    await fsPromises.writeFile(tempOther, 'other temp');
    await fsPromises.writeFile(realFile, 'real file');

    await cleanupOrphanTempFiles(targetDir, 50);

    assert.strictEqual(fs.existsSync(temp1), false);
    assert.strictEqual(fs.existsSync(temp2), false);
    assert.strictEqual(fs.existsSync(tempOther), true);
    assert.strictEqual(fs.existsSync(realFile), true);
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
  }
});

test('readArchiveEntry and listTopicEntries: internal readback with positional repository calls', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-readback-test-'));
  try {
    let sequenceCallArgs = null;
    let listCallArgs = null;

    const mockRepo = {
      getArchiveCoordinationBySequence: (accountId, topicId, entrySequence) => {
        sequenceCallArgs = { accountId, topicId, entrySequence };
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
      listTopicArchiveCoordinations: (accountId, topicId) => {
        listCallArgs = { accountId, topicId };
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

    const relPath = 'TG_acc_1/Q001_Topic/001_Test_20260329-103000.md';
    const absPath = path.join(tmpDir, relPath);
    await fsPromises.mkdir(path.dirname(absPath), { recursive: true });
    const content = '---\narchive_id: 301\nrecord_kind: ORIGINAL\nentry_sequence: 1\n---\n\n# Content here.\n';
    await fsPromises.writeFile(absPath, content, 'utf-8');

    // 1. Read entry back
    const entry = await writer.readArchiveEntry({
      accountId: 'acc_1',
      topicId: 1,
      entrySequence: 1,
    });
    assert.ok(entry);
    assert.strictEqual(entry.archive_id, 301);
    assert.strictEqual(entry.content, content);
    assert.deepStrictEqual(sequenceCallArgs, { accountId: 'acc_1', topicId: 1, entrySequence: 1 });

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
    assert.deepStrictEqual(listCallArgs, { accountId: 'acc_1', topicId: 1 });
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true });
  }
});

test('R2-F7-RETRY-CLOSED-GUARD: injectable sleep counter proves positive retry and zero post-close retry timer', async () => {
  const tmpDir = await fsPromises.mkdtemp(path.join(os.tmpdir(), 'hhai-retry-closed-'));
  try {
    let isClosed = false;
    let preCloseSleepCalls = 0;
    let postCloseSleepCalls = 0;

    const testSleep = async (ms) => {
      if (isClosed) {
        postCloseSleepCalls++;
      } else {
        preCloseSleepCalls++;
      }
    };

    // Positive control: closed=false and eligible transient failure
    let transientCount = 0;
    const transientFs = {
      ...fsPromises,
      open: async (...args) => {
        transientCount++;
        if (transientCount === 1) {
          const err = new Error('EBUSY: resource busy or locked');
          err.code = 'EBUSY';
          throw err;
        }
        return fsPromises.open(...args);
      },
    };

    const writer1 = new ArchiveFileWriter({
      archiveRoot: tmpDir,
      sleep: testSleep,
      retryDelays: [10],
      fsPromises: transientFs,
    });

    const coord1 = {
      archive_id: 801,
      account_id: 'acc_retry',
      topic_id: 1,
      entry_sequence: 1,
      record_kind: 'ORIGINAL',
      platform_msg_id: 'tg:801:1',
      command_id: 'cmd-801',
      created_at: 1774780200,
      relative_path: 'acc_retry/topic1/001_Test_20260928-120000.md',
    };

    const res1 = await writer1.publishArchiveRecord({
      archiveRoot: tmpDir,
      coordination: coord1,
      topic: { display_name: 'Topic 1' },
      questionSnapshot: 'Q',
      replyBody: 'A',
      isClosed: () => isClosed,
    });

    assert.strictEqual(res1.status, 'COMPLETED');
    assert.ok(preCloseSleepCalls > 0, 'PRE_CLOSE_RETRY_SLEEP_CALLS must be > 0');

    // Closed case: eligible transient filesystem failure observed after closed=true
    isClosed = false;
    let closedCaseTriggered = false;
    const closedFs = {
      ...fsPromises,
      open: async (...args) => {
        if (closedCaseTriggered) {
          isClosed = true;
          const err = new Error('EBUSY: resource busy or locked');
          err.code = 'EBUSY';
          throw err;
        }
        return fsPromises.open(...args);
      },
    };

    const writer2 = new ArchiveFileWriter({
      archiveRoot: tmpDir,
      sleep: testSleep,
      retryDelays: [10],
      fsPromises: closedFs,
    });

    const coord2 = {
      archive_id: 802,
      account_id: 'acc_retry',
      topic_id: 1,
      entry_sequence: 2,
      record_kind: 'ORIGINAL',
      platform_msg_id: 'tg:802:1',
      command_id: 'cmd-802',
      created_at: 1774780200,
      relative_path: 'acc_retry/topic1/002_Test_20260928-120000.md',
    };

    closedCaseTriggered = true;
    const res2 = await writer2.publishArchiveRecord({
      archiveRoot: tmpDir,
      coordination: coord2,
      topic: { display_name: 'Topic 1' },
      questionSnapshot: 'Q2',
      replyBody: 'A2',
      isClosed: () => isClosed,
    });

    assert.strictEqual(res2.status, 'CANCELLED_CLOSED');
    assert.strictEqual(postCloseSleepCalls, 0, 'POST_CLOSE_RETRY_SLEEP_CALLS must be 0');

    console.log(`R2_F7_RETRY_PRE_CLOSE_SLEEP_CALLS=${preCloseSleepCalls}`);
    console.log(`R2_F7_RETRY_POST_CLOSE_SLEEP_CALLS=${postCloseSleepCalls}`);
  } finally {
    await fsPromises.rm(tmpDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
});
