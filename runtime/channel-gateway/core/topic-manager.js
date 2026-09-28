/**
 * runtime/channel-gateway/core/topic-manager.js
 *
 * TG-MVP-14: Conversation Archive & Topics Management.
 * Provides deterministic topic name normalization, safe filename segments,
 * directory segment formatting, surrogate-pair-safe truncation,
 * startup validation (path budget, account directory collision/drift detection),
 * and TopicManager orchestration.
 */

'use strict';

const path = require('node:path');
const { sanitizeDlp } = require('../../../shared/dlpSanitizer');

const SAFE_ACCOUNT_LABEL_MAX = 32;
const FINAL_TOPIC_DIR_MAX = 48;
const SUMMARY_PAYLOAD_MAX = 48;
const FINAL_PATH_BUDGET_MAX = 240;

const WINDOWS_RESERVED_NAMES = new Set([
  'CON', 'PRN', 'AUX', 'NUL',
  'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
  'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
]);

/**
 * Truncates a UTF-16 string safely up to maxCodeUnits without splitting surrogate pairs.
 *
 * @param {string} str
 * @param {number} maxCodeUnits
 * @returns {string}
 */
function truncateSurrogateSafe(str, maxCodeUnits) {
  if (typeof str !== 'string') return '';
  if (str.length <= maxCodeUnits) return str;
  let cut = maxCodeUnits;
  if (cut > 0) {
    const code = str.charCodeAt(cut - 1);
    if (code >= 0xd800 && code <= 0xdbff) {
      cut -= 1;
    }
  }
  return str.slice(0, cut);
}

/**
 * Topic normalization (Prompt §10):
 * Unicode NFKC -> trim -> collapse Unicode whitespace to one ASCII space -> locale-independent lowercase.
 *
 * @param {string} name
 * @returns {string}
 */
function normalizeTopicName(name) {
  if (typeof name !== 'string') {
    const err = new TypeError('INVALID_TOPIC_NAME: Topic name must be a string (fail-closed)');
    err.code = 'INVALID_TOPIC_NAME';
    throw err;
  }
  const nfkc = name.normalize('NFKC').trim();
  if (nfkc.length === 0) {
    const err = new Error('INVALID_TOPIC_NAME: Topic name must not be empty after normalization (fail-closed)');
    err.code = 'INVALID_TOPIC_NAME';
    throw err;
  }
  const collapsed = nfkc.replace(/\s+/g, ' ');
  return collapsed.toLowerCase();
}

/**
 * Formats a clean display name (NFKC, trimmed, single-space collapsed, preserving case).
 *
 * @param {string} name
 * @returns {string}
 */
function cleanDisplayName(name) {
  if (typeof name !== 'string') {
    throw new TypeError('Topic name must be a string (fail-closed)');
  }
  const nfkc = name.normalize('NFKC').trim();
  if (nfkc.length === 0) {
    throw new Error('Topic name must not be empty after normalization (fail-closed)');
  }
  return nfkc.replace(/\s+/g, ' ');
}

/**
 * Filename-safe segment normalization (Prompt §10):
 * - NFKC
 * - replace Windows-invalid filename chars/control chars with '_'
 * - normalize whitespace for path use
 * - remove trailing dot / trailing space
 * - collapse repeated replacement underscores
 * - Windows reserved basename: prefix '_' deterministically
 * - never split UTF-16 surrogate pair when truncating
 * - fail closed if segment becomes empty
 *
 * @param {string} name
 * @param {number} maxCodeUnits
 * @returns {string}
 */
function toSafeFilenameSegment(name, maxCodeUnits) {
  if (typeof name !== 'string') {
    throw new TypeError('Name must be a string (fail-closed)');
  }
  const nfkc = name.normalize('NFKC');
  // Replace Windows-invalid chars and control chars with _
  let s = nfkc.replace(/[\x00-\x1F\x7F"*/:<>?\\|]/g, '_');
  // Normalize whitespace for path use
  s = s.replace(/\s+/g, ' ');
  // Remove trailing dot / trailing space
  s = s.replace(/[. ]+$/, '');
  // Collapse repeated replacement underscores
  s = s.replace(/_+/g, '_');
  s = s.trim();

  if (WINDOWS_RESERVED_NAMES.has(s.toUpperCase())) {
    s = '_' + s;
  }

  s = truncateSurrogateSafe(s, maxCodeUnits);
  s = s.replace(/[. ]+$/, '');

  if (!s || s.length === 0) {
    throw new Error('Safe filename segment is empty (fail-closed)');
  }
  return s;
}

/**
 * Formats canonical account directory segment: TG_<safe-account-label>
 * Max payload = 32 code units.
 *
 * @param {string} accountLabel
 * @returns {string}
 */
function formatAccountDirName(accountLabel, accountId = '') {
  const labelToUse = (accountLabel && String(accountLabel).trim().length > 0)
    ? String(accountLabel)
    : String(accountId || '');
  const safeLabel = toSafeFilenameSegment(labelToUse, SAFE_ACCOUNT_LABEL_MAX);
  return `TG_${safeLabel}`;
}

/**
 * Formats canonical topic directory segment: Q<topic-sequence>_<safe-topic>
 * Minimum 3 digits for sequence (Q001, Q002, ..., Q1000).
 * Total topic directory segment max = 48 code units INCLUDING Q<seq>_ prefix.
 *
 * @param {number} topicSequence
 * @param {string} topicName
 * @returns {string}
 */
function formatTopicDirName(topicSequence, topicName) {
  if (
    typeof topicSequence !== 'number' ||
    !Number.isSafeInteger(topicSequence) ||
    topicSequence < 1
  ) {
    throw new RangeError('topicSequence must be a positive safe integer (fail-closed)');
  }
  const prefix = `Q${String(topicSequence).padStart(3, '0')}_`;
  const allowedPayloadUnits = Math.max(0, FINAL_TOPIC_DIR_MAX - prefix.length);
  const safeTopic = toSafeFilenameSegment(topicName, allowedPayloadUnits);
  const dirName = prefix + safeTopic;
  if (dirName.length > FINAL_TOPIC_DIR_MAX) {
    throw new Error(`Topic directory segment exceeds ${FINAL_TOPIC_DIR_MAX} code units (fail-closed)`);
  }
  return dirName;
}

/**
 * Derives safe summary segment from question or amendment content snapshot (Prompt §13):
 * sanitizeDlp -> deterministic text normalization -> first valid filename-safe text portion -> cap 48 UTF-16 code units.
 * Fallback: '訊息'.
 *
 * @param {string} contentSnapshot
 * @returns {string}
 */
function deriveSummarySafeSegment(contentSnapshot) {
  const sanitized = sanitizeDlp(typeof contentSnapshot === 'string' ? contentSnapshot : '');
  const lines = sanitized.split(/\r?\n/);
  let firstLine = '';
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.length > 0) {
      firstLine = trimmed;
      break;
    }
  }
  if (!firstLine) {
    return '訊息';
  }
  try {
    const seg = toSafeFilenameSegment(firstLine, SUMMARY_PAYLOAD_MAX);
    if (!seg || /^_+$/.test(seg)) {
      return '訊息';
    }
    return seg;
  } catch {
    return '訊息';
  }
}

/**
 * Canonical UTC time string format: YYYYMMDD-HHmmss (no colon).
 *
 * @param {number} sec
 * @returns {string}
 */
function formatTimestamp(sec) {
  if (typeof sec !== 'number' || !Number.isSafeInteger(sec) || sec < 0) {
    throw new RangeError('Timestamp must be a non-negative safe integer (fail-closed)');
  }
  const d = new Date(sec * 1000);
  const YYYY = String(d.getUTCFullYear()).padStart(4, '0');
  const MM = String(d.getUTCMonth() + 1).padStart(2, '0');
  const DD = String(d.getUTCDate()).padStart(2, '0');
  const HH = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  const ss = String(d.getUTCSeconds()).padStart(2, '0');
  return `${YYYY}${MM}${DD}-${HH}${mm}${ss}`;
}

/**
 * Formats entry filename: <entry-sequence>_<summary>_<time>.md
 * Sequence minimum 3 digits.
 *
 * @param {number} entrySequence
 * @param {string} summaryText
 * @param {number} createdAtSec
 * @returns {string}
 */
function formatEntryFileName(entrySequenceOrOpts, summaryText, createdAtSec) {
  let entrySequence, text, sec;
  if (typeof entrySequenceOrOpts === 'object' && entrySequenceOrOpts !== null) {
    entrySequence = entrySequenceOrOpts.entrySequence;
    text = entrySequenceOrOpts.summaryText !== undefined
      ? entrySequenceOrOpts.summaryText
      : (entrySequenceOrOpts.summarySafeSegment !== undefined
          ? entrySequenceOrOpts.summarySafeSegment
          : '');
    sec = entrySequenceOrOpts.createdAtSec !== undefined
      ? entrySequenceOrOpts.createdAtSec
      : entrySequenceOrOpts.createdTimeSec;
  } else {
    entrySequence = entrySequenceOrOpts;
    text = summaryText;
    sec = createdAtSec;
  }

  if (
    typeof entrySequence !== 'number' ||
    !Number.isSafeInteger(entrySequence) ||
    entrySequence < 1
  ) {
    throw new RangeError('entrySequence must be a positive safe integer (fail-closed)');
  }
  const seqStr = String(entrySequence).padStart(3, '0');
  const summarySeg = deriveSummarySafeSegment(text);
  const timeStr = formatTimestamp(sec);
  return `${seqStr}_${summarySeg}_${timeStr}.md`;
}

/**
 * Computes deterministic relative path:
 * TG_<safe-account-label>/Q<topic-sequence>_<safe-topic>/<entry-sequence>_<summary>_<time>.md
 *
 * @param {string|object} accountDirNameOrOpts
 * @param {string} [topicDirName]
 * @param {number} [entrySequence]
 * @param {string} [summaryText]
 * @param {number} [createdAtSec]
 * @returns {string}
 */
function computeRelativePath(accountDirNameOrOpts, topicDirName, entrySequence, summaryText, createdAtSec) {
  let accDir, topDir, fileName;
  if (typeof accountDirNameOrOpts === 'object' && accountDirNameOrOpts !== null) {
    accDir = accountDirNameOrOpts.accountDirName;
    topDir = accountDirNameOrOpts.topicDirName;
    if (accountDirNameOrOpts.entryFileName) {
      fileName = accountDirNameOrOpts.entryFileName;
    } else {
      fileName = formatEntryFileName(
        accountDirNameOrOpts.entrySequence,
        accountDirNameOrOpts.summaryText || accountDirNameOrOpts.summarySafeSegment,
        accountDirNameOrOpts.createdAtSec || accountDirNameOrOpts.createdTimeSec
      );
    }
  } else {
    accDir = accountDirNameOrOpts;
    topDir = topicDirName;
    fileName = formatEntryFileName(entrySequence, summaryText, createdAtSec);
  }
  return `${accDir}/${topDir}/${fileName}`;
}

/**
 * Validates path budget for archive root (Prompt §13):
 * Must reserve enough digits for Number.MAX_SAFE_INTEGER sequences (16 digits),
 * fixed time format (15 chars), extension (3 chars), and fixed segment maxima.
 * Absolute final target <= 240 UTF-16 code units.
 *
 * @param {string} archiveRoot
 * @returns {boolean}
 */
function validatePathBudget(archiveRoot) {
  if (typeof archiveRoot !== 'string' || archiveRoot.trim().length === 0) {
    throw new Error('archiveRoot must be a non-empty string (fail-closed)');
  }
  const resolved = path.resolve(archiveRoot);
  // Account dir: TG_ (3) + 32 = 35
  const maxAccountDir = 3 + SAFE_ACCOUNT_LABEL_MAX;
  // Topic dir: 48 (including prefix)
  const maxTopicDir = FINAL_TOPIC_DIR_MAX;
  // File: 16 (MAX_SAFE_INT) + 1 + 48 (summary) + 1 + 15 (time) + 3 (.md) = 84
  const maxEntryFile = 16 + 1 + SUMMARY_PAYLOAD_MAX + 1 + 15 + 3;
  // Total relative path = maxAccountDir + 1 + maxTopicDir + 1 + maxEntryFile = 169
  const maxRelativePath = maxAccountDir + 1 + maxTopicDir + 1 + maxEntryFile;
  const maxFinalPath = resolved.length + 1 + maxRelativePath;

  if (maxFinalPath > FINAL_PATH_BUDGET_MAX) {
    const err = new Error(
      `ARCHIVE_PATH_BUDGET_EXCEEDED: archiveRoot length ${resolved.length} exceeds budget (max allowed path ${FINAL_PATH_BUDGET_MAX})`
    );
    err.code = 'ARCHIVE_PATH_BUDGET_EXCEEDED';
    throw err;
  }
  return true;
}

/**
 * TopicManager class coordinating topic operations and startup checks.
 */
class TopicManager {
  /**
   * Validates Gateway startup conditions (Prompt §10 & §13):
   * 1. Path budget calculation for archiveRoot.
   * 2. Derives archive account directory names for all registered accounts.
   *    If two different account IDs normalize/truncate to the same account_dir_name -> fail closed.
   * 3. Checks existing archive_topic rows in DB:
   *    If existing rows for an account contain an account_dir_name inconsistent with
   *    the currently derived registered label -> fail closed (no automatic directory migration).
   *
   * @param {object} params
   * @param {Array<{ id: string, label?: string, enabled?: boolean }>} [params.registeredAccounts]
   * @param {object} [params.accountRegistry]
   * @param {object} params.repository SqliteStateRepository instance
   * @param {string} params.archiveRoot Configured archiveRoot
   */
  static validateStartup(params) {
    if (!params || typeof params !== 'object') {
      throw new TypeError('params must be an object (fail-closed)');
    }
    const { archiveRoot, repository } = params;
    if (!archiveRoot) {
      throw new Error('archiveRoot is required for startup validation (fail-closed)');
    }
    validatePathBudget(archiveRoot);

    const registeredAccounts = Array.isArray(params.registeredAccounts)
      ? params.registeredAccounts
      : (params.accountRegistry && typeof params.accountRegistry.list === 'function'
          ? params.accountRegistry.list()
          : (!params.accountRegistry && params.registeredAccounts === undefined ? [] : null));

    if (!Array.isArray(registeredAccounts)) {
      throw new TypeError('registeredAccounts must be an array (fail-closed)');
    }

    const accountDirMap = new Map(); // account_id -> account_dir_name
    const dirToAccountMap = new Map(); // account_dir_name -> account_id

    for (const acc of registeredAccounts) {
      if (!acc || !acc.id) continue;
      const label = acc.label || acc.id;
      const accountDirName = formatAccountDirName(label);

      if (dirToAccountMap.has(accountDirName)) {
        const existingAccId = dirToAccountMap.get(accountDirName);
        if (existingAccId !== acc.id) {
          const err = new Error(
            `ARCHIVE_ACCOUNT_DIR_COLLISION: Accounts '${existingAccId}' and '${acc.id}' collision on '${accountDirName}'`
          );
          err.code = 'ARCHIVE_ACCOUNT_DIR_COLLISION';
          throw err;
        }
      }

      dirToAccountMap.set(accountDirName, acc.id);
      accountDirMap.set(acc.id, accountDirName);
    }

    // Check existing DB rows for account directory drift
    if (repository && typeof repository.getAllAccountArchiveTopics === 'function') {
      for (const [accId, derivedDirName] of accountDirMap.entries()) {
        const existingTopics = repository.getAllAccountArchiveTopics(accId);
        for (const t of existingTopics) {
          if (t.account_dir_name !== derivedDirName) {
            const err = new Error(
              `ARCHIVE_ACCOUNT_DIR_DRIFT: Account '${accId}' existing topic directory '${t.account_dir_name}' drifts from derived '${derivedDirName}'`
            );
            err.code = 'ARCHIVE_ACCOUNT_DIR_DRIFT';
            throw err;
          }
        }
      }
    }

    return { accountDirMap, dirToAccountMap };
  }
}

module.exports = {
  SAFE_ACCOUNT_LABEL_MAX,
  FINAL_TOPIC_DIR_MAX,
  SUMMARY_PAYLOAD_MAX,
  FINAL_PATH_BUDGET_MAX,
  truncateSurrogateSafe,
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
};
