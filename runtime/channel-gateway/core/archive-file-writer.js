/**
 * runtime/channel-gateway/core/archive-file-writer.js
 *
 * TG-MVP-14: Hard-Link Conversation Archive Publication, Capability Probe,
 * Crash Reconciliation (F-2), and Transient Retry (F-3).
 *
 * Invariants:
 * - Publication primitive MUST NOT use rename(temp, final).
 * - Hard-link no-overwrite: fs.promises.link(temp, final).
 * - 100% async fs.promises; zero synchronous filesystem I/O.
 * - Startup hard-link capability probe: probeHardLinkCapability(archiveRoot, fsPromises).
 * - Crash reconciliation (F-2): byte-for-byte exact equality + embedded archive_id + metadata match.
 * - Intra-attempt transient retry (F-3): EBUSY/EPERM/EACCES only, 100/300/900ms.
 * - Closed guard: checked before each fs step and before retry sleep.
 * - Non-fatal temp unlink: leftover temp unlink failure never converts a published archive to FAILED.
 * - Path containment (F-4): stepwise non-recursive directory creation, lstat/realpath symlink/junction rejection.
 * - Readback / reconciliation containment: lstat/realpath symlink/junction rejection before reading final file.
 * - Zero raw absolute archive paths in errors or logging.
 */

'use strict';

const fsPromisesDefault = require('node:fs/promises');
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
 * Creates destination directory and all intermediate directories stepwise from canonicalRoot (F-4).
 * For each component:
 * - If exists: lstat, reject if isSymbolicLink(), realpath, assert containment.
 * - If absent: mkdir non-recursively, lstat, reject if isSymbolicLink(), realpath, assert containment.
 * Strictly no recursive:true!
 *
 * @param {string} destDir
 * @param {string} canonicalRoot
 * @param {object} fsPromises
 */
async function ensureManagedDirectoryStepwise(destDir, canonicalRoot, fsPromises, isClosed = () => false) {
  assertPathConfinement(destDir, canonicalRoot);
  const rel = path.relative(canonicalRoot, destDir);
  if (!rel || rel === '.') {
    return;
  }
  const parts = rel.split(/[\\/]+/).filter(Boolean);
  let current = canonicalRoot;

  for (const part of parts) {
    if (isClosed()) return;
    current = path.join(current, part);
    assertPathConfinement(current, canonicalRoot);

    let stat = null;
    try {
      if (isClosed()) return;
      stat = await fsPromises.lstat(current);
    } catch (err) {
      if (err && err.code !== 'ENOENT') {
        const wrapErr = new Error('ARCHIVE_FS_INSPECTION_FAILED');
        wrapErr.code = 'ARCHIVE_FS_INSPECTION_FAILED';
        throw wrapErr;
      }
    }
    if (isClosed()) return;

    if (stat) {
      if (stat.isSymbolicLink()) {
        const err = new Error('ARCHIVE_SYMLINK_FORBIDDEN: Symbolic links are forbidden in archive path (fail-closed)');
        err.code = 'ARCHIVE_SYMLINK_FORBIDDEN';
        throw err;
      }
      if (!stat.isDirectory()) {
        const err = new Error('ARCHIVE_DIR_CREATE_FAILED: Path component is not a directory');
        err.code = 'ARCHIVE_DIR_CREATE_FAILED';
        throw err;
      }
      if (isClosed()) return;
      const real = await fsPromises.realpath(current);
      if (isClosed()) return;
      assertPathConfinement(real, canonicalRoot);
    } else {
      if (isClosed()) return;
      // Absent: mkdir exactly ONE level NON-RECURSIVELY
      try {
        await fsPromises.mkdir(current);
      } catch (mkdirErr) {
        if (mkdirErr && mkdirErr.code === 'EEXIST') {
          // Concurrent creation: will be checked by postStat below
        } else {
          const err = new Error('ARCHIVE_DIR_CREATE_FAILED');
          err.code = 'ARCHIVE_DIR_CREATE_FAILED';
          throw err;
        }
      }
      if (isClosed()) return;

      const postStat = await fsPromises.lstat(current);
      if (isClosed()) return;
      if (postStat.isSymbolicLink()) {
        const err = new Error('ARCHIVE_SYMLINK_FORBIDDEN: Symbolic links are forbidden in archive path (fail-closed)');
        err.code = 'ARCHIVE_SYMLINK_FORBIDDEN';
        throw err;
      }
      if (!postStat.isDirectory()) {
        const err = new Error('ARCHIVE_DIR_CREATE_FAILED: Created component is not a directory');
        err.code = 'ARCHIVE_DIR_CREATE_FAILED';
        throw err;
      }
      if (isClosed()) return;
      const real = await fsPromises.realpath(current);
      if (isClosed()) return;
      assertPathConfinement(real, canonicalRoot);
    }
  }
}

/**
 * Generates deterministic expected Markdown bytes for an archive coordination record.
 * Pure deterministic function of persisted inputs.
 *
 * @param {object} params
 * @param {object} params.coordination
 * @param {object} [params.topic]
 * @param {string} [params.outboxBody]
 * @param {string} [params.replyBody]
 * @param {string} [params.questionSnapshot]
 * @param {string} [params.amendmentSnapshot]
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
 * Hard-link capability probe (F-6):
 * Mechanically proves inside archiveRoot:
 * A. Exclusive temp creation works (wx)
 * B. Hard-link source -> new destination works
 * C. Hard-link to existing destination fails without replacement (EEXIST)
 * D. Existing destination bytes remain unchanged
 * E. Cleanup of ALL owned probe artifacts succeeds
 *
 * @param {string} archiveRoot
 * @param {object} [fsPromises=fsPromisesDefault]
 * @returns {Promise<{ success: true, supportsHardLink: true }>}
 */
async function probeHardLinkCapability(archiveRoot, fsPromises = fsPromisesDefault) {
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
    const stat = await fsPromises.stat(archiveRoot);
    if (!stat.isDirectory()) {
      throw makeErr();
    }
    canonicalRoot = await fsPromises.realpath(archiveRoot);
  } catch {
    throw makeErr();
  }

  const probeUuid = crypto.randomUUID().replace(/-/g, '').toLowerCase();
  const probeTemp = path.join(canonicalRoot, `.${probeUuid}.probe.tmp`);
  const probeLink = path.join(canonicalRoot, `.${probeUuid}.probe.link`);
  const testBytes = Buffer.from('ARCHIVE_PROBE_CAPABILITY_VALIDATION', 'utf8');

  let probeTempCreated = false;
  let probeLinkCreated = false;
  let probeSuccess = false;

  try {
    // A. Exclusive temp creation works
    let handle;
    try {
      handle = await fsPromises.open(probeTemp, 'wx');
      probeTempCreated = true;
      await handle.writeFile(testBytes);
      await handle.sync();
    } finally {
      if (handle) {
        await handle.close();
      }
    }

    // B. Hard-link source -> new destination works
    await fsPromises.link(probeTemp, probeLink);
    probeLinkCreated = true;
    const linkBytes = await fsPromises.readFile(probeLink);
    if (Buffer.compare(linkBytes, testBytes) !== 0) {
      throw new Error('Probe link content mismatch');
    }

    // C. Attempting hard-link to already-existing destination fails with EEXIST / without replacement
    let failedWithEexist = false;
    try {
      await fsPromises.link(probeTemp, probeLink);
    } catch (linkErr) {
      if (linkErr && linkErr.code === 'EEXIST') {
        failedWithEexist = true;
      }
    }
    if (!failedWithEexist) {
      throw new Error('Hard-link to existing destination did not fail with EEXIST');
    }

    // D. Existing destination bytes remain unchanged
    const afterBytes = await fsPromises.readFile(probeLink);
    if (Buffer.compare(afterBytes, testBytes) !== 0) {
      throw new Error('Destination bytes were corrupted on duplicate link attempt');
    }

    probeSuccess = true;
  } catch (err) {
    if (err && err.code === 'ARCHIVE_LINK_CAPABILITY_UNAVAILABLE') {
      throw err;
    }
    throw makeErr();
  } finally {
    // E. Attempt cleanup of ALL owned probe artifacts even if one fails
    let cleanupFailed = false;
    if (probeTempCreated) {
      try {
        await fsPromises.unlink(probeTemp);
      } catch {
        cleanupFailed = true;
      }
    }
    if (probeLinkCreated) {
      try {
        await fsPromises.unlink(probeLink);
      } catch {
        cleanupFailed = true;
      }
    }
    // If cleanup success cannot be established, startup fail closed
    if (cleanupFailed) {
      throw makeErr();
    }
  }

  if (!probeSuccess) {
    throw makeErr();
  }

  return { success: true, supportsHardLink: true };
}

/**
 * Reconciles an existing final archive file against expected bytes and metadata (F-2, F-4).
 * Lexical relative checks alone are insufficient:
 * 1. lstat final target
 * 2. reject symbolic link/junction
 * 3. realpath final target
 * 4. verify canonical containment under archiveRoot
 * 5. read bytes
 *
 * @param {string} finalPath
 * @param {Buffer} expectedBytes
 * @param {object} coordination
 * @param {string} canonicalRoot
 * @param {object} fsPromises
 * @returns {Promise<boolean>} True if exact match, false if conflict
 */
async function reconcileExistingFinalFile(finalPath, expectedBytes, coordination, canonicalRoot, fsPromises, isClosed = () => false) {
  try {
    if (isClosed()) {
      return false;
    }
    assertPathConfinement(finalPath, canonicalRoot);
    const stat = await fsPromises.lstat(finalPath);
    if (isClosed()) {
      return false;
    }
    if (stat.isSymbolicLink()) {
      return false;
    }
    if (!stat.isFile()) {
      return false;
    }
    const real = await fsPromises.realpath(finalPath);
    if (isClosed()) {
      return false;
    }
    assertPathConfinement(real, canonicalRoot);

    const existingBytes = await fsPromises.readFile(real);
    if (isClosed()) {
      return false;
    }
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
 * @param {object} [fsPromises=fsPromisesDefault]
 * @param {() => boolean} [isClosed=() => false]
 */
async function cleanupOrphanTempFiles(destDir, archiveId, fsPromises = fsPromisesDefault, isClosed = () => false) {
  try {
    if (isClosed()) {
      return;
    }
    const files = await fsPromises.readdir(destDir);
    if (isClosed()) {
      return;
    }
    for (const file of files) {
      if (isClosed()) {
        return;
      }
      const match = CANONICAL_TEMP_REGEX.exec(file);
      if (match) {
        const fileArchiveId = parseInt(match[1], 10);
        if (fileArchiveId === archiveId) {
          if (isClosed()) {
            return;
          }
          try {
            await fsPromises.unlink(path.join(destDir, file));
          } catch (_) {}
        }
      }
    }
  } catch (_) {}
}

/**
 * Cleans up canonical archive temp files whose archive_id is NOT currently PENDING.
 *
 * @param {string} archiveRoot
 * @param {Set<number>} pendingArchiveIds
 * @param {object} [fsPromises=fsPromisesDefault]
 * @param {() => boolean} [isClosed=() => false]
 */
async function cleanupNonPendingTempFiles(archiveRoot, pendingArchiveIds, fsPromises = fsPromisesDefault, isClosed = () => false) {
  async function walkDir(dir) {
    if (isClosed()) {
      return;
    }
    const entries = await fsPromises.readdir(dir, { withFileTypes: true });
    if (isClosed()) {
      return;
    }
    for (const entry of entries) {
      if (isClosed()) {
        return;
      }
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walkDir(fullPath);
      } else if (entry.isFile()) {
        const match = CANONICAL_TEMP_REGEX.exec(entry.name);
        if (match) {
          const archiveId = parseInt(match[1], 10);
          if (!pendingArchiveIds.has(archiveId)) {
            if (isClosed()) {
              return;
            }
            try {
              await fsPromises.unlink(fullPath);
            } catch (_) {}
          }
        }
      }
    }
  }
  if (isClosed()) {
    return;
  }
  await walkDir(archiveRoot);
}

class ArchiveFileWriter {
  #archiveRoot;
  #repository;
  #sleep;
  #retryDelays;
  #fs;

  /**
   * @param {object} [options]
   * @param {string} [options.archiveRoot]
   * @param {object} [options.repository]
   * @param {(ms: number) => Promise<void>} [options.sleep]
   * @param {number[]} [options.retryDelays]
   * @param {object} [options.fsPromises]
   */
  constructor(options = {}) {
    this.#archiveRoot = options.archiveRoot || null;
    this.#repository = options.repository || null;
    this.#sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.#retryDelays = options.retryDelays || DEFAULT_TRANSIENT_BACKOFF_MS;
    this.#fs = options.fsPromises || fsPromisesDefault;
  }

  get fsPromises() {
    return this.#fs;
  }

  /**
   * Publishes one archive record using hard-link no-overwrite primitive (F-2, F-3, F-4).
   *
   * @param {object} params
   * @param {string} [params.archiveRoot]
   * @param {object} params.coordination
   * @param {object} [params.topic]
   * @param {string} [params.outboxBody]
   * @param {string} [params.replyBody]
   * @param {string} [params.questionSnapshot]
   * @param {string} [params.amendmentSnapshot]
   * @param {() => boolean} [params.isClosed]
   * @returns {Promise<{ status: 'COMPLETED'|'FAILED'|'CANCELLED_CLOSED', reasonCode?: string, reconciled?: boolean }>}
   */
  async publishArchiveRecord({
    archiveRoot,
    coordination,
    topic,
    outboxBody,
    replyBody,
    questionSnapshot,
    amendmentSnapshot,
    isClosed = () => false,
  }) {
    if (isClosed()) {
      return { status: 'CANCELLED_CLOSED' };
    }

    const root = archiveRoot || this.#archiveRoot;
    if (!root || typeof root !== 'string') {
      return { status: 'FAILED', reasonCode: 'ARCHIVE_ROOT_INVALID' };
    }
    if (!coordination || typeof coordination !== 'object') {
      return { status: 'FAILED', reasonCode: 'COORDINATION_INVALID' };
    }

    let canonicalRoot;
    try {
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      const rootStat = await this.#fs.stat(root);
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      if (!rootStat.isDirectory()) {
        return { status: 'FAILED', reasonCode: 'ARCHIVE_ROOT_NOT_DIRECTORY' };
      }
      canonicalRoot = await this.#fs.realpath(root);
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
    } catch {
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      return { status: 'FAILED', reasonCode: 'ARCHIVE_ROOT_UNAVAILABLE' };
    }

    if (isClosed()) {
      return { status: 'CANCELLED_CLOSED' };
    }

    // Resolve target path and verify containment
    const targetPath = path.join(canonicalRoot, coordination.relative_path);
    if (targetPath.length > 240) {
      return { status: 'FAILED', reasonCode: 'ARCHIVE_PATH_BUDGET_EXCEEDED' };
    }

    const destDir = path.dirname(targetPath);
    try {
      await ensureManagedDirectoryStepwise(destDir, canonicalRoot, this.#fs, isClosed);
    } catch (err) {
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      return { status: 'FAILED', reasonCode: err.code || 'ARCHIVE_PATH_SAFETY_VIOLATION' };
    }

    if (isClosed()) {
      return { status: 'CANCELLED_CLOSED' };
    }

    // Ensure reserved 附件/ directory
    try {
      const attachmentsDir = path.join(destDir, '附件');
      await ensureManagedDirectoryStepwise(attachmentsDir, canonicalRoot, this.#fs, isClosed);
    } catch (err) {
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      return { status: 'FAILED', reasonCode: err.code || 'ARCHIVE_DIR_CREATE_FAILED' };
    }

    if (isClosed()) {
      return { status: 'CANCELLED_CLOSED' };
    }

    // Generate expected deterministic bytes
    let expectedBytes;
    try {
      expectedBytes = generateArchiveMarkdownBytes({
        coordination,
        topic,
        outboxBody: outboxBody !== undefined ? outboxBody : replyBody,
        questionSnapshot,
        amendmentSnapshot,
      });
    } catch {
      return { status: 'FAILED', reasonCode: 'ARCHIVE_BYTES_GENERATION_FAILED' };
    }

    if (isClosed()) {
      return { status: 'CANCELLED_CLOSED' };
    }

    // Check if target file already exists -> F-2 Crash reconciliation
    let targetExists = false;
    try {
      const targetStat = await this.#fs.lstat(targetPath);
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      if (targetStat.isSymbolicLink()) {
        return { status: 'FAILED', reasonCode: 'ARCHIVE_SYMLINK_FORBIDDEN' };
      }
      targetExists = true;
    } catch (err) {
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      if (err && err.code !== 'ENOENT') {
        return { status: 'FAILED', reasonCode: 'ARCHIVE_FS_INSPECTION_FAILED' };
      }
    }

    if (isClosed()) {
      return { status: 'CANCELLED_CLOSED' };
    }

    if (targetExists) {
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      const match = await reconcileExistingFinalFile(targetPath, expectedBytes, coordination, canonicalRoot, this.#fs, isClosed);
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }
      if (match) {
        await cleanupOrphanTempFiles(destDir, coordination.archive_id, this.#fs, isClosed);
        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }
        return { status: 'COMPLETED', reconciled: true };
      }
      return { status: 'FAILED', reasonCode: 'ARCHIVE_TARGET_CONFLICT' };
    }

    // Transient retry loop for hard-link publication (F-3)
    const delays = this.#retryDelays;
    for (let attempt = 0; attempt <= delays.length; attempt++) {
      if (isClosed()) {
        return { status: 'CANCELLED_CLOSED' };
      }

      const randomHex = crypto.randomBytes(32).toString('hex').toLowerCase();
      const tempFilename = `.${coordination.archive_id}.${randomHex}.tmp`;
      const tempPath = path.join(destDir, tempFilename);

      let handle = null;
      let tempCreated = false;

      try {
        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }
        // Step 4: Create unique temp file with wx
        handle = await this.#fs.open(tempPath, 'wx');
        tempCreated = true;

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // Step 5: Write complete bytes
        await handle.writeFile(expectedBytes);

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // Step 6: File sync
        await handle.sync();

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // Step 7: Close temp file
        await handle.close();
        handle = null;

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // Step 8: Hard-link publication
        await this.#fs.link(tempPath, targetPath);

        // Immediate post-link closed guard (Canary target)
        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // Step 9 & 10: Link succeeded; temp unlink is NON-FATAL best-effort
        try {
          await this.#fs.unlink(tempPath);
        } catch (_) {}

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // Step 11: Directory fsync best-effort
        let dirHandle = null;
        try {
          dirHandle = await this.#fs.open(destDir, 'r');
          if (isClosed()) {
            return { status: 'CANCELLED_CLOSED' };
          }
          await dirHandle.sync();
        } catch (_) {
        } finally {
          if (dirHandle && !isClosed()) {
            try { await dirHandle.close(); } catch (_) {}
          }
        }

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // Cleanup any older orphan temp files for this archive_id
        await cleanupOrphanTempFiles(destDir, coordination.archive_id, this.#fs, isClosed);

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        return { status: 'COMPLETED', reconciled: false };
      } catch (err) {
        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        if (handle) {
          try {
            if (!isClosed()) {
              await handle.close();
            }
          } catch (_) {}
          handle = null;
        }

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // Clean up our own temp file on failure
        if (tempCreated) {
          try {
            if (!isClosed()) {
              await this.#fs.unlink(tempPath);
            }
          } catch (_) {}
        }

        if (isClosed()) {
          return { status: 'CANCELLED_CLOSED' };
        }

        // If target already exists (EEXIST), re-attempt F-2 crash reconciliation
        if (err && err.code === 'EEXIST') {
          if (isClosed()) {
            return { status: 'CANCELLED_CLOSED' };
          }
          const match = await reconcileExistingFinalFile(targetPath, expectedBytes, coordination, canonicalRoot, this.#fs, isClosed);
          if (isClosed()) {
            return { status: 'CANCELLED_CLOSED' };
          }
          if (match) {
            await cleanupOrphanTempFiles(destDir, coordination.archive_id, this.#fs, isClosed);
            if (isClosed()) {
              return { status: 'CANCELLED_CLOSED' };
            }
            return { status: 'COMPLETED', reconciled: true };
          }
          return { status: 'FAILED', reasonCode: 'ARCHIVE_TARGET_CONFLICT' };
        }

        // Check if transient error eligible for bounded retry
        if (attempt < delays.length && err && TRANSIENT_FS_CODES.has(err.code)) {
          if (isClosed()) {
            return { status: 'CANCELLED_CLOSED' };
          }
          await this.#sleep(delays[attempt]);
          if (isClosed()) {
            return { status: 'CANCELLED_CLOSED' };
          }
          continue;
        }

        if (err && TRANSIENT_FS_CODES.has(err.code)) {
          return { status: 'FAILED', reasonCode: 'ARCHIVE_FS_TRANSIENT_EXHAUSTED' };
        }

        return { status: 'FAILED', reasonCode: (err && err.code) || 'ARCHIVE_FS_ERROR' };
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
   * Internal readback for one canonical archive entry (F-2, F-4).
   * Supports positional repository call: getArchiveCoordinationBySequence(accountId, topicId, entrySequence).
   *
   * @param {object} params
   * @param {string} [params.archiveRoot]
   * @param {string} [params.relativePath]
   * @param {string} [params.accountId]
   * @param {number} [params.topicId]
   * @param {number} [params.entrySequence]
   * @returns {Promise<{ metadata: object, body: string, raw: string, content: string, archive_id?: number } | null>}
   */
  async readArchiveEntry(params) {
    const archiveRoot = params.archiveRoot || this.#archiveRoot;
    if (!archiveRoot) {
      return null;
    }
    let relativePath = params.relativePath;
    if (!relativePath && this.#repository && params.accountId && params.topicId && params.entrySequence) {
      const coord = this.#repository.getArchiveCoordinationBySequence(
        params.accountId,
        params.topicId,
        params.entrySequence
      );
      if (!coord) {
        return null;
      }
      relativePath = coord.relative_path;
    }
    if (!relativePath) {
      return null;
    }

    let canonicalRoot;
    try {
      canonicalRoot = await this.#fs.realpath(archiveRoot);
    } catch {
      return null;
    }

    const fullPath = path.join(canonicalRoot, relativePath);
    try {
      assertPathConfinement(fullPath, canonicalRoot);
    } catch {
      return null;
    }

    let stat;
    try {
      stat = await this.#fs.lstat(fullPath);
    } catch {
      return null;
    }

    if (stat.isSymbolicLink() || !stat.isFile()) {
      return null;
    }

    let real;
    try {
      real = await this.#fs.realpath(fullPath);
      assertPathConfinement(real, canonicalRoot);
    } catch {
      return null;
    }

    let raw;
    try {
      raw = await this.#fs.readFile(real, 'utf8');
    } catch {
      return null;
    }

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
   * Internal list of entries for a topic in entry_sequence ASC order (F-2, F-4).
   * Supports positional repository call: listTopicArchiveCoordinations(accountId, topicId).
   */
  async listTopicEntries(params) {
    const archiveRoot = params.archiveRoot || this.#archiveRoot;
    if (!archiveRoot) {
      return [];
    }

    if (this.#repository && params.accountId && params.topicId) {
      const coords = this.#repository.listTopicArchiveCoordinations(
        params.accountId,
        params.topicId
      );
      const results = [];
      for (const coord of coords) {
        const entry = await this.readArchiveEntry({
          archiveRoot,
          relativePath: coord.relative_path,
        });
        if (entry) {
          results.push({ ...coord, ...entry });
        }
      }
      return results;
    }

    let canonicalRoot;
    try {
      canonicalRoot = await this.#fs.realpath(archiveRoot);
    } catch {
      return [];
    }

    const topicPath = path.join(canonicalRoot, params.accountDirName, params.topicDirName);
    try {
      assertPathConfinement(topicPath, canonicalRoot);
    } catch {
      return [];
    }

    let stat;
    try {
      stat = await this.#fs.lstat(topicPath);
    } catch {
      return [];
    }
    if (stat.isSymbolicLink() || !stat.isDirectory()) {
      return [];
    }

    let realTopicPath;
    try {
      realTopicPath = await this.#fs.realpath(topicPath);
      assertPathConfinement(realTopicPath, canonicalRoot);
    } catch {
      return [];
    }

    let files;
    try {
      files = (await this.#fs.readdir(realTopicPath)).filter((f) => f.endsWith('.md')).sort();
    } catch {
      return [];
    }

    const entries = [];
    for (const f of files) {
      const relPath = path.join(params.accountDirName, params.topicDirName, f);
      try {
        const entry = await this.readArchiveEntry({ archiveRoot: canonicalRoot, relativePath: relPath });
        if (entry) {
          entries.push({ filename: f, relativePath: relPath, ...entry });
        }
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
