/**
 * runtime/channel-gateway/core/archive-file-writer.js
 *
 * TG-MVP-14: Hard-Link Conversation Archive Publication, Capability Probe,
 * Crash Reconciliation (F-2), and Transient Retry (F-3).
 *
 * Invariants:
 * - Publication primitive MUST NOT use rename(temp, final).
 * - Hard-link no-overwrite: fs.link(temp, final).
 * - Startup hard-link capability probe: probeHardLinkCapability(archiveRoot).
 * - Crash reconciliation (F-2): byte-for-byte exact equality + embedded archive_id + metadata match.
 * - Intra-attempt transient retry (F-3): EBUSY/EPERM/EACCES only, 100/300/900ms.
 * - Non-fatal temp unlink: leftover temp unlink failure never converts a published archive to FAILED.
 * - Zero raw absolute archive paths in errors or logging.
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { sanitizeDlp } = require('../../../shared/dlpSanitizer');

const CANONICAL_TEMP_REGEX = /^\.([0-9]+)\.([0-9a-f]{64})\.tmp$/;
const TRANSIENT_FS_CODES = new Set(['EBUSY', 'EPERM', 'EACCES']);
const DEFAULT_TRANSIENT_BACKOFF_MS = [100, 300, 900];

/**
 * Checks path containment under canonical root.
 *
 * @param {string} targetPath
 * @param {string} canonicalRoot
 */
function assertPathConfinement(targetPath, canonicalRoot) {
  const resolved = path.resolve(targetPath);
  const rel = path.relative(canonicalRoot, resolved);
  if (rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel)) {
    const err = new Error('ARCHIVE_CONTAINMENT_VIOLATION: Path escapes archive root (fail-closed)');
    err.code = 'ARCHIVE_CONTAINMENT_VIOLATION';
    throw err;
  }
}

/**
 * Ensures directory is not a symlink/junction escaping canonicalRoot.
 *
 * @param {string} dirPath
 * @param {string} canonicalRoot
 */
function assertDirectorySafety(dirPath, canonicalRoot) {
  assertPathConfinement(dirPath, canonicalRoot);
  let lstat;
  try {
    lstat = fs.lstatSync(dirPath);
  } catch (err) {
    if (err && err.code === 'ENOENT') return;
    throw new Error('ARCHIVE_FS_INSPECTION_FAILED');
  }
  if (lstat.isSymbolicLink()) {
    throw new Error('ARCHIVE_SYMLINK_FORBIDDEN: Symbolic links are forbidden in archive path (fail-closed)');
  }
  const real = fs.realpathSync(dirPath);
  assertPathConfinement(real, canonicalRoot);
}

/**
 * Generates deterministic expected Markdown bytes for an archive coordination record (Prompt §15).
 * Pure deterministic function of persisted inputs.
 *
 * @param {object} params
 * @param {object} params.coordination
 * @param {object} params.topic
 * @param {string} [params.outboxBody]
 * @returns {Buffer}
 */
function generateArchiveMarkdownBytes(params) {
  if (!params || typeof params !== 'object') {
    throw new TypeError('params must be an object');
  }
  const { coordination } = params;
  if (!coordination || typeof coordination !== 'object') {
    throw new TypeError('coordination must be an object');
  }

  const isoTime = new Date(coordination.created_at * 1000).toISOString();
  let frontmatter = '';
  let bodyContent = '';

  if (coordination.record_kind === 'ORIGINAL') {
    const question = coordination.content_snapshot !== undefined ? coordination.content_snapshot : params.questionSnapshot;
    const sanitizedQuestion = sanitizeDlp(question || '');
    const reply = params.outboxBody !== undefined ? params.outboxBody : params.replyBody;
    const sanitizedReply = sanitizeDlp(reply || '');

    frontmatter = [
      '---',
      `archive_id: ${coordination.archive_id}`,
      `record_kind: ORIGINAL`,
      `account_id: ${coordination.account_id}`,
      `topic_id: ${coordination.topic_id}`,
      `entry_sequence: ${coordination.entry_sequence}`,
      `platform_msg_id: ${coordination.platform_msg_id}`,
      `command_id: ${coordination.command_id}`,
      `delivery_status: authorized reply record`,
      `created_at: ${isoTime}`,
      '---',
    ].join('\n');

    bodyContent = [
      '',
      '# Question',
      '',
      sanitizedQuestion,
      '',
      '# Reply',
      '',
      sanitizedReply,
      '',
    ].join('\n');
  } else if (coordination.record_kind === 'AMENDMENT') {
    const amendment = coordination.content_snapshot !== undefined ? coordination.content_snapshot : params.amendmentSnapshot;
    const sanitizedAmendment = sanitizeDlp(amendment || '');

    frontmatter = [
      '---',
      `archive_id: ${coordination.archive_id}`,
      `record_kind: AMENDMENT`,
      `account_id: ${coordination.account_id}`,
      `topic_id: ${coordination.topic_id}`,
      `entry_sequence: ${coordination.entry_sequence}`,
      `platform_msg_id: ${coordination.platform_msg_id}`,
      `original_archive_id: ${coordination.original_archive_id}`,
      `source_platform_event_id: ${coordination.source_platform_event_id}`,
      `created_at: ${isoTime}`,
      '---',
    ].join('\n');

    bodyContent = [
      '',
      '# Amendment',
      '',
      sanitizedAmendment,
      '',
    ].join('\n');
  } else {
    throw new Error(`Unsupported record_kind: ${coordination.record_kind}`);
  }

  const fullText = frontmatter + '\n' + bodyContent;
  return Buffer.from(fullText, 'utf8');
}

/**
 * Hard-link capability probe (Prompt §17):
 * Mechanically proves inside archiveRoot:
 * A. Exclusive temp creation works (wx)
 * B. Hard-link source -> new destination works
 * C. Hard-link to existing destination fails with EEXIST / fail-without-replacement
 * D. Existing destination bytes remain unchanged
 * E. Probe cleanup succeeds
 *
 * @param {string} archiveRoot
 */
function probeHardLinkCapability(archiveRoot) {
  const makeErr = () => {
    const err = new Error('ARCHIVE_LINK_CAPABILITY_UNAVAILABLE');
    err.code = 'ARCHIVE_LINK_CAPABILITY_UNAVAILABLE';
    return err;
  };

  if (typeof archiveRoot !== 'string' || archiveRoot.trim().length === 0) {
    throw makeErr();
  }

  let canonicalRoot;
  try {
    const stat = fs.statSync(archiveRoot);
    if (!stat.isDirectory()) {
      throw makeErr();
    }
    canonicalRoot = fs.realpathSync(archiveRoot);
  } catch {
    throw makeErr();
  }

  const probeUuid = crypto.randomUUID().replace(/-/g, '').toLowerCase();
  const probeTemp = path.join(canonicalRoot, `.${probeUuid}.probe.tmp`);
  const probeLink = path.join(canonicalRoot, `.${probeUuid}.probe.link`);
  const testBytes = Buffer.from('ARCHIVE_PROBE_CAPABILITY_VALIDATION', 'utf8');

  try {
    // A. Exclusive temp creation works
    const fd = fs.openSync(probeTemp, 'wx');
    try {
      fs.writeSync(fd, testBytes);
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }

    // B. Hard-link source -> new destination works
    fs.linkSync(probeTemp, probeLink);
    const linkBytes = fs.readFileSync(probeLink);
    if (Buffer.compare(linkBytes, testBytes) !== 0) {
      throw new Error('Probe link content mismatch');
    }

    // C. Attempting hard-link to already-existing destination fails with EEXIST
    let failedWithEexist = false;
    try {
      fs.linkSync(probeTemp, probeLink);
    } catch (linkErr) {
      if (linkErr.code === 'EEXIST') {
        failedWithEexist = true;
      }
    }
    if (!failedWithEexist) {
      throw new Error('Hard-link to existing destination did not fail with EEXIST');
    }

    // D. Existing destination bytes remain unchanged
    const afterBytes = fs.readFileSync(probeLink);
    if (Buffer.compare(afterBytes, testBytes) !== 0) {
      throw new Error('Destination bytes were corrupted on duplicate link attempt');
    }

    return { success: true, supportsHardLink: true };
  } catch (err) {
    if (err && err.code === 'ARCHIVE_LINK_CAPABILITY_UNAVAILABLE') {
      throw err;
    }
    throw makeErr();
  } finally {
    try { fs.unlinkSync(probeTemp); } catch (_) {}
    try { fs.unlinkSync(probeLink); } catch (_) {}
  }
}

/**
 * Reconciles an existing final archive file against expected bytes and metadata (F-2).
 *
 * @param {string} finalPath
 * @param {Buffer} expectedBytes
 * @param {object} coordination
 * @returns {boolean} True if exact match, false if conflict
 */
function reconcileExistingFinalFile(finalPath, expectedBytes, coordination) {
  try {
    const existingBytes = fs.readFileSync(finalPath);
    // 1. Byte-for-byte exact equality
    if (Buffer.compare(existingBytes, expectedBytes) !== 0) {
      return false;
    }

    // 2. Embedded archive_id and metadata validation
    const text = existingBytes.toString('utf8');
    const expectedIdMarker = `archive_id: ${coordination.archive_id}`;
    if (!text.includes(expectedIdMarker)) {
      return false;
    }

    if (!text.includes(`record_kind: ${coordination.record_kind}`)) {
      return false;
    }
    if (!text.includes(`account_id: ${coordination.account_id}`)) {
      return false;
    }
    if (!text.includes(`topic_id: ${coordination.topic_id}`)) {
      return false;
    }
    if (!text.includes(`entry_sequence: ${coordination.entry_sequence}`)) {
      return false;
    }
    if (!text.includes(`platform_msg_id: ${coordination.platform_msg_id}`)) {
      return false;
    }

    return true;
  } catch {
    return false;
  }
}

/**
 * Cleans up orphan canonical temp files matching exact syntax for a specific archive_id.
 *
 * @param {string} destDir
 * @param {number} archiveId
 */
function cleanupOrphanTempFiles(destDir, archiveId) {
  try {
    const files = fs.readdirSync(destDir);
    for (const file of files) {
      const match = CANONICAL_TEMP_REGEX.exec(file);
      if (match) {
        const fileArchiveId = parseInt(match[1], 10);
        if (fileArchiveId === archiveId) {
          try {
            fs.unlinkSync(path.join(destDir, file));
          } catch (_) {}
        }
      }
    }
  } catch (_) {}
}

/**
 * Cleans up canonical archive temp files whose archive_id is NOT currently PENDING (Prompt §20).
 *
 * @param {string} archiveRoot
 * @param {Set<number>} pendingArchiveIds
 */
function cleanupNonPendingTempFiles(archiveRoot, pendingArchiveIds) {
  try {
    function walkDir(dir) {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walkDir(fullPath);
        } else if (entry.isFile()) {
          const match = CANONICAL_TEMP_REGEX.exec(entry.name);
          if (match) {
            const archiveId = parseInt(match[1], 10);
            if (!pendingArchiveIds.has(archiveId)) {
              try {
                fs.unlinkSync(fullPath);
              } catch (_) {}
            }
          }
        }
      }
    }
    walkDir(archiveRoot);
  } catch (_) {}
}

class ArchiveFileWriter {
  #archiveRoot;
  #repository;
  #sleep;
  #retryDelays;

  /**
   * @param {object} [options]
   * @param {string} [options.archiveRoot]
   * @param {object} [options.repository]
   * @param {(ms: number) => Promise<void>} [options.sleep]
   * @param {number[]} [options.retryDelays]
   */
  constructor(options = {}) {
    this.#archiveRoot = options.archiveRoot || null;
    this.#repository = options.repository || null;
    this.#sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.#retryDelays = options.retryDelays || DEFAULT_TRANSIENT_BACKOFF_MS;
  }

  /**
   * Publishes one archive record using hard-link no-overwrite primitive (Prompt §16, §18, §19).
   *
   * @param {object} params
   * @param {string} [params.archiveRoot]
   * @param {object} params.coordination
   * @param {object} params.topic
   * @param {string} [params.outboxBody]
   * @returns {Promise<{ status: 'COMPLETED'|'FAILED', reasonCode?: string, reconciled?: boolean }>}
   */
  async publishArchiveRecord({ archiveRoot, coordination, topic, outboxBody, questionSnapshot, amendmentSnapshot }) {
    const root = archiveRoot || this.#archiveRoot;
    if (!root || typeof root !== 'string') {
      return { status: 'FAILED', reasonCode: 'ARCHIVE_ROOT_INVALID' };
    }
    if (!coordination || typeof coordination !== 'object') {
      return { status: 'FAILED', reasonCode: 'COORDINATION_INVALID' };
    }

    let canonicalRoot;
    try {
      const rootStat = fs.statSync(root);
      if (!rootStat.isDirectory()) {
        return { status: 'FAILED', reasonCode: 'ARCHIVE_ROOT_NOT_DIRECTORY' };
      }
      canonicalRoot = fs.realpathSync(root);
    } catch {
      return { status: 'FAILED', reasonCode: 'ARCHIVE_ROOT_UNAVAILABLE' };
    }

    // Resolve target path and verify containment
    const targetPath = path.join(canonicalRoot, coordination.relative_path);
    if (targetPath.length > 240) {
      return { status: 'FAILED', reasonCode: 'ARCHIVE_PATH_BUDGET_EXCEEDED' };
    }

    const destDir = path.dirname(targetPath);
    try {
      assertDirectorySafety(destDir, canonicalRoot);
    } catch (err) {
      return { status: 'FAILED', reasonCode: err.code || 'ARCHIVE_PATH_SAFETY_VIOLATION' };
    }

    // Create managed destination directory and reserved 附件/ directory if not existing
    try {
      fs.mkdirSync(destDir, { recursive: true });
      const attachmentsDir = path.join(destDir, '附件');
      fs.mkdirSync(attachmentsDir, { recursive: true });
    } catch {
      return { status: 'FAILED', reasonCode: 'ARCHIVE_DIR_CREATE_FAILED' };
    }

    // Generate expected deterministic bytes
    let expectedBytes;
    try {
      expectedBytes = generateArchiveMarkdownBytes({
        coordination,
        topic,
        outboxBody,
        questionSnapshot,
        amendmentSnapshot,
      });
    } catch (err) {
      return { status: 'FAILED', reasonCode: 'ARCHIVE_BYTES_GENERATION_FAILED' };
    }

    // Check if target file already exists -> F-2 Crash reconciliation
    let targetExists = false;
    try {
      targetExists = fs.existsSync(targetPath);
    } catch (_) {}

    if (targetExists) {
      const match = reconcileExistingFinalFile(targetPath, expectedBytes, coordination);
      if (match) {
        cleanupOrphanTempFiles(destDir, coordination.archive_id);
        return { status: 'COMPLETED', reconciled: true };
      }
      return { status: 'FAILED', reasonCode: 'ARCHIVE_TARGET_CONFLICT' };
    }

    // Transient retry loop for hard-link publication (F-3)
    const delays = this.#retryDelays;
    for (let attempt = 0; attempt <= delays.length; attempt++) {
      const randomHex = crypto.randomBytes(32).toString('hex').toLowerCase();
      const tempFilename = `.${coordination.archive_id}.${randomHex}.tmp`;
      const tempPath = path.join(destDir, tempFilename);

      let fd = null;
      let tempCreated = false;

      try {
        // Step 4: Create unique temp file with wx
        fd = fs.openSync(tempPath, 'wx');
        tempCreated = true;

        // Step 5: Write complete bytes
        fs.writeSync(fd, expectedBytes);

        // Step 6: File sync
        fs.fsyncSync(fd);

        // Step 7: Close temp file
        fs.closeSync(fd);
        fd = null;

        // Step 8: Hard-link publication
        fs.linkSync(tempPath, targetPath);

        // Step 9 & 10: Link succeeded; temp unlink is NON-FATAL best-effort
        try {
          fs.unlinkSync(tempPath);
        } catch (_) {}

        // Step 11: Directory fsync best-effort
        try {
          const dirFd = fs.openSync(destDir, 'r');
          fs.fsyncSync(dirFd);
          fs.closeSync(dirFd);
        } catch (_) {}

        // Cleanup any older orphan temp files for this archive_id
        cleanupOrphanTempFiles(destDir, coordination.archive_id);

        return { status: 'COMPLETED', reconciled: false };
      } catch (err) {
        if (fd !== null) {
          try { fs.closeSync(fd); } catch (_) {}
          fd = null;
        }

        // Clean up our own temp file on failure
        if (tempCreated) {
          try { fs.unlinkSync(tempPath); } catch (_) {}
        }

        // If target already exists (EEXIST), re-attempt F-2 crash reconciliation
        if (err.code === 'EEXIST') {
          const match = reconcileExistingFinalFile(targetPath, expectedBytes, coordination);
          if (match) {
            cleanupOrphanTempFiles(destDir, coordination.archive_id);
            return { status: 'COMPLETED', reconciled: true };
          }
          return { status: 'FAILED', reasonCode: 'ARCHIVE_TARGET_CONFLICT' };
        }

        // Check if transient error eligible for bounded retry
        if (attempt < delays.length && TRANSIENT_FS_CODES.has(err.code)) {
          await this.#sleep(delays[attempt]);
          continue;
        }

        if (TRANSIENT_FS_CODES.has(err.code)) {
          return { status: 'FAILED', reasonCode: 'ARCHIVE_FS_TRANSIENT_EXHAUSTED' };
        }

        return { status: 'FAILED', reasonCode: err.code || 'ARCHIVE_FS_ERROR' };
      }
    }

    return { status: 'FAILED', reasonCode: 'ARCHIVE_FS_TRANSIENT_EXHAUSTED' };
  }

  /**
   * Helper method for publication with exception throwing (convenience wrapper).
   */
  async publishArchiveFile(params) {
    const archiveRoot = params.archiveRoot || this.#archiveRoot;
    const res = await this.publishArchiveRecord({
      archiveRoot,
      coordination: params.coordination,
      topic: params.topic,
      outboxBody: params.replyBody !== undefined ? params.replyBody : params.outboxBody,
      questionSnapshot: params.questionSnapshot,
      amendmentSnapshot: params.amendmentSnapshot,
    });
    if (res.status === 'COMPLETED') {
      return {
        success: true,
        action: res.reconciled ? 'RECONCILED' : 'PUBLISHED',
      };
    }
    const err = new Error(res.reasonCode || 'ARCHIVE_PUBLISH_FAILED');
    err.code = res.reasonCode || 'ARCHIVE_PUBLISH_FAILED';
    throw err;
  }

  /**
   * Internal readback for one canonical archive entry (Prompt §27).
   * Supports { accountId, topicId, entrySequence } using repository or { archiveRoot, relativePath }.
   *
   * @param {object} params
   * @param {string} [params.archiveRoot]
   * @param {string} [params.relativePath]
   * @param {string} [params.accountId]
   * @param {number} [params.topicId]
   * @param {number} [params.entrySequence]
   * @returns {{ metadata: object, body: string, raw: string, content: string, archive_id?: number } | null}
   */
  readArchiveEntry(params) {
    const archiveRoot = params.archiveRoot || this.#archiveRoot;
    if (!archiveRoot) {
      return null;
    }
    let relativePath = params.relativePath;
    if (!relativePath && this.#repository && params.accountId && params.topicId && params.entrySequence) {
      const coord = this.#repository.getArchiveCoordinationBySequence({
        accountId: params.accountId,
        topicId: params.topicId,
        entrySequence: params.entrySequence,
      });
      if (!coord) {
        return null;
      }
      relativePath = coord.relative_path;
    }
    if (!relativePath) {
      return null;
    }

    const canonicalRoot = fs.realpathSync(archiveRoot);
    const fullPath = path.join(canonicalRoot, relativePath);
    assertPathConfinement(fullPath, canonicalRoot);

    if (!fs.existsSync(fullPath)) {
      return null;
    }

    const raw = fs.readFileSync(fullPath, 'utf8');
    const metadata = {};
    let body = '';

    if (raw.startsWith('---\n')) {
      const endFm = raw.indexOf('\n---\n', 4);
      if (endFm !== -1) {
        const fmBlock = raw.slice(4, endFm);
        body = raw.slice(endFm + 5);
        for (const line of fmBlock.split('\n')) {
          const idx = line.indexOf(':');
          if (idx !== -1) {
            const key = line.slice(0, idx).trim();
            const val = line.slice(idx + 1).trim();
            metadata[key] = val;
          }
        }
      }
    }

    const archiveId = metadata.archive_id ? parseInt(metadata.archive_id, 10) : undefined;
    return { archive_id: archiveId, content: raw, metadata, body, raw };
  }

  /**
   * Internal list of entries for a topic in entry_sequence ASC order (Prompt §27).
   * Supports { accountId, topicId } with repository or { archiveRoot, accountDirName, topicDirName }.
   */
  listTopicEntries(params) {
    const archiveRoot = params.archiveRoot || this.#archiveRoot;
    if (!archiveRoot) {
      return [];
    }

    if (this.#repository && params.accountId && params.topicId) {
      const coords = this.#repository.listTopicArchiveCoordinations({
        accountId: params.accountId,
        topicId: params.topicId,
      });
      const results = [];
      for (const coord of coords) {
        const entry = this.readArchiveEntry({
          archiveRoot,
          relativePath: coord.relative_path,
        });
        if (entry) {
          results.push({ ...coord, ...entry });
        }
      }
      return results;
    }

    const canonicalRoot = fs.realpathSync(archiveRoot);
    const topicPath = path.join(canonicalRoot, params.accountDirName, params.topicDirName);
    assertPathConfinement(topicPath, canonicalRoot);

    if (!fs.existsSync(topicPath)) {
      return [];
    }

    const files = fs.readdirSync(topicPath).filter((f) => f.endsWith('.md')).sort();
    const entries = [];
    for (const f of files) {
      const relPath = path.join(params.accountDirName, params.topicDirName, f);
      try {
        const entry = this.readArchiveEntry({ archiveRoot: canonicalRoot, relativePath: relPath });
        entries.push({ filename: f, relativePath: relPath, ...entry });
      } catch (_) {}
    }

    // Sort by entry_sequence ASC
    entries.sort((a, b) => {
      const seqA = parseInt(a.metadata.entry_sequence || '0', 10);
      const seqB = parseInt(b.metadata.entry_sequence || '0', 10);
      return seqA - seqB;
    });

    return entries;
  }
}

module.exports = {
  CANONICAL_TEMP_REGEX,
  TRANSIENT_FS_CODES,
  DEFAULT_TRANSIENT_BACKOFF_MS,
  generateArchiveMarkdownBytes,
  probeHardLinkCapability,
  reconcileExistingFinalFile,
  cleanupOrphanTempFiles,
  cleanupNonPendingTempFiles,
  ArchiveFileWriter,
};
