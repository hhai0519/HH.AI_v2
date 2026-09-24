/**
 * runtime/channel-gateway/core/data-location-config.js
 *
 * ADR-0022 D24 / ADR-0023 / TG-MVP-09A / TG-MVP-10: Repo-External Data Location & Gateway Config Contract.
 *
 * Invariants:
 * - Pure validation contract for resolved repo-external data location and gateway configuration.
 * - NO filesystem operations (no fs.stat, no fs.mkdir, no fs.access).
 * - NO process.env access or OS known-folder resolution (handled by runtime loader).
 * - NO credentials, tokens, secrets, bot accounts, or listener sockets.
 * - Strict schema validation: supports schemaVersion 4 with backward compatibility for v2 and v3.
 * - v2: exact v2 keys only; rejects top-level backup/accounts keys; normalizes in-memory to v4 with default backup policy and accounts.telegram = [].
 * - v3: allows optional top-level backup block; rejects accounts; normalizes in-memory to v4 with accounts.telegram = [].
 * - v4: allows optional top-level backup block and optional top-level accounts block.
 * - accounts in v4: allows only 'telegram' key containing non-secret account metadata (id, label, description, enabled default false).
 * - Rejects unknown top-level, dataLocations, gateway, backup, and accounts keys.
 * - Path validation: all data paths must be non-empty trimmed strings and absolute.
 * - Location guard helper: rejects UNC network paths and synchronized directory segments for stateRoot ONLY.
 * - Immutability: input object is never mutated; returns a clean normalized schemaVersion 4 object.
 */

'use strict';

const path = require('node:path');

const CURRENT_SCHEMA_VERSION = 4;
const LEGACY_SUPPORTED_SCHEMA_VERSIONS = new Set([2, 3]);
const DATA_LOCATION_SCHEMA_VERSION = CURRENT_SCHEMA_VERSION;
const CANONICAL_GATEWAY_PORT = 3003;

const DEFAULT_MAX_TOTAL_BYTES = 1_000_000_000;
const DEFAULT_MIN_KEEP_COUNT = 3;

const ALLOWED_TOP_LEVEL_KEYS_V2 = new Set([
  'schemaVersion',
  'dataLocations',
  'gateway',
]);

const ALLOWED_TOP_LEVEL_KEYS_V3 = new Set([
  'schemaVersion',
  'dataLocations',
  'gateway',
  'backup',
]);

const ALLOWED_TOP_LEVEL_KEYS_V4 = new Set([
  'schemaVersion',
  'dataLocations',
  'gateway',
  'backup',
  'accounts',
]);

const ALLOWED_DATA_LOCATIONS_KEYS = new Set([
  'archiveRoot',
  'attachmentTempRoot',
  'stateRoot',
  'logsRoot',
  'protectedRoots',
]);

const ALLOWED_GATEWAY_KEYS = new Set([
  'localPort',
]);

const ALLOWED_BACKUP_KEYS = new Set([
  'maxTotalBytes',
  'minKeepCount',
]);

const ALLOWED_ACCOUNTS_KEYS = new Set([
  'telegram',
]);

const ALLOWED_TELEGRAM_ACCOUNT_KEYS = new Set([
  'id',
  'label',
  'description',
  'enabled',
]);

const FORBIDDEN_SECRET_NAMES = new Set([
  'token',
  'bottoken',
  'secret',
  'password',
  'secretref',
  'credential',
  'apikey',
  'api_key',
  'private_key',
  'accesstoken',
  'channelsecret',
]);

const CONTROL_CHAR_REGEX = /[\x00-\x1F\x7F]/;

const REQUIRED_SINGLETON_PATHS = [
  'archiveRoot',
  'attachmentTempRoot',
  'stateRoot',
  'logsRoot',
];

/**
 * Validates that a string contains only well-formed UTF-16 code units.
 *
 * @param {string} str
 * @returns {boolean}
 */
function isWellFormedUtf16(str) {
  if (typeof str !== 'string') {
    return false;
  }
  const len = str.length;
  for (let i = 0; i < len; i++) {
    const code = str.charCodeAt(i);
    if (code >= 0xD800 && code <= 0xDBFF) {
      if (i + 1 >= len) {
        return false;
      }
      const nextCode = str.charCodeAt(i + 1);
      if (nextCode < 0xDC00 || nextCode > 0xDFFF) {
        return false;
      }
      i++;
    } else if (code >= 0xDC00 && code <= 0xDFFF) {
      return false;
    }
  }
  return true;
}

/**
 * Check if a path string is absolute on either Windows or POSIX.
 *
 * @param {string} val
 * @returns {boolean}
 */
function isAbsolutePath(val) {
  if (typeof val !== 'string') {
    return false;
  }
  return path.win32.isAbsolute(val) || path.posix.isAbsolute(val);
}

/**
 * Validates that stateRoot is not located on a UNC network share or synchronized directory.
 *
 * @param {string} stateRootPath - Path string to validate.
 * @throws {Error} If path is UNC or inside a synchronized folder.
 */
function assertSafeStateRootLocation(stateRootPath) {
  if (typeof stateRootPath !== 'string' || !stateRootPath.trim()) {
    throw new Error('stateRoot path must be a non-empty string');
  }

  const trimmed = stateRootPath.trim();

  // 1. UNC checks (extended UNC checked first)
  if (/^[\\/]{2,}\?[\\/]+UNC[\\/]+/i.test(trimmed)) {
    throw new Error(`stateRoot must not be an extended UNC network path (fail-closed): '${stateRootPath}'`);
  }
  if (trimmed.startsWith('\\\\') || trimmed.startsWith('//')) {
    throw new Error(`stateRoot must not be a UNC network path (fail-closed): '${stateRootPath}'`);
  }

  // 2. Synchronized directory segment checks
  const segments = trimmed.split(/[\\/]+/);
  for (const seg of segments) {
    const lower = seg.toLowerCase().trim();
    if (
      lower.startsWith('onedrive') ||
      lower === 'dropbox' ||
      lower === 'google drive' ||
      lower === 'googledrive' ||
      lower === 'iclouddrive'
    ) {
      throw new Error(
        `stateRoot must not reside within a synchronized folder ('${seg}') (fail-closed): '${stateRootPath}'`
      );
    }
  }
}

/**
 * Validates and normalizes a resolved data location and gateway configuration object.
 *
 * @param {object} config - Resolved configuration object
 * @returns {object} Normalized copy of the configuration (schemaVersion 4)
 * @throws {TypeError|Error} If schema, types, or paths are invalid
 */
function validateResolvedDataLocationConfig(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new TypeError('Configuration must be a non-null object');
  }

  if (config.schemaVersion === undefined) {
    throw new Error('Missing required field: schemaVersion');
  }

  if (
    typeof config.schemaVersion !== 'number' ||
    !Number.isInteger(config.schemaVersion) ||
    (config.schemaVersion !== CURRENT_SCHEMA_VERSION &&
      !LEGACY_SUPPORTED_SCHEMA_VERSIONS.has(config.schemaVersion))
  ) {
    throw new Error(
      `Unsupported schemaVersion: expected ${CURRENT_SCHEMA_VERSION} or supported legacy versions (2, 3), received ${config.schemaVersion}`
    );
  }

  const inputVersion = config.schemaVersion;

  // 1. Top-level key validation based on declared version
  let allowedTopKeys;
  if (inputVersion === 2) {
    allowedTopKeys = ALLOWED_TOP_LEVEL_KEYS_V2;
  } else if (inputVersion === 3) {
    allowedTopKeys = ALLOWED_TOP_LEVEL_KEYS_V3;
  } else {
    allowedTopKeys = ALLOWED_TOP_LEVEL_KEYS_V4;
  }

  for (const key of Object.keys(config)) {
    if (!allowedTopKeys.has(key)) {
      throw new Error(`Unknown top-level configuration key: '${key}'`);
    }
  }

  // 2. Strict dataLocations schema validation
  if (!config.dataLocations || typeof config.dataLocations !== 'object' || Array.isArray(config.dataLocations)) {
    throw new TypeError('dataLocations must be a non-null object');
  }

  for (const key of Object.keys(config.dataLocations)) {
    if (!ALLOWED_DATA_LOCATIONS_KEYS.has(key)) {
      throw new Error(`Unknown dataLocations key: '${key}'`);
    }
  }

  // 3. Singleton path validation
  const normalizedLocations = {};

  for (const field of REQUIRED_SINGLETON_PATHS) {
    const val = config.dataLocations[field];
    if (val === undefined || val === null) {
      throw new Error(`Missing required dataLocations field: '${field}'`);
    }
    if (typeof val !== 'string') {
      throw new TypeError(`'${field}' must be a string`);
    }
    const trimmed = val.trim();
    if (!trimmed) {
      throw new Error(`'${field}' must be a non-empty string`);
    }
    if (!isAbsolutePath(trimmed)) {
      throw new Error(`'${field}' must be an absolute path: received '${val}'`);
    }
    normalizedLocations[field] = trimmed;
  }

  // 4. Protected roots validation
  const protectedRootsVal = config.dataLocations.protectedRoots;
  if (protectedRootsVal === undefined || protectedRootsVal === null) {
    throw new Error("Missing required dataLocations field: 'protectedRoots'");
  }
  if (!Array.isArray(protectedRootsVal)) {
    throw new TypeError('protectedRoots must be an array of absolute paths');
  }

  const normalizedProtectedRoots = [];
  for (let i = 0; i < protectedRootsVal.length; i++) {
    const entry = protectedRootsVal[i];
    if (typeof entry !== 'string') {
      throw new TypeError(`protectedRoots[${i}] must be a string`);
    }
    const trimmed = entry.trim();
    if (!trimmed) {
      throw new Error(`protectedRoots[${i}] must be a non-empty string`);
    }
    if (!isAbsolutePath(trimmed)) {
      throw new Error(`protectedRoots[${i}] must be an absolute path: received '${entry}'`);
    }
    normalizedProtectedRoots.push(trimmed);
  }

  normalizedLocations.protectedRoots = normalizedProtectedRoots;

  // 5. Strict gateway schema validation
  if (config.gateway === undefined || config.gateway === null) {
    throw new Error("Missing required field: gateway");
  }

  if (typeof config.gateway !== 'object' || Array.isArray(config.gateway)) {
    throw new TypeError('gateway must be a non-null object');
  }

  for (const key of Object.keys(config.gateway)) {
    if (!ALLOWED_GATEWAY_KEYS.has(key)) {
      throw new Error(`Unknown gateway configuration key: '${key}'`);
    }
  }

  const portVal = config.gateway.localPort;
  if (portVal === undefined || portVal === null) {
    throw new Error("Missing required gateway field: 'localPort'");
  }

  if (typeof portVal !== 'number' || !Number.isInteger(portVal)) {
    throw new TypeError("'localPort' must be an integer");
  }

  if (portVal !== CANONICAL_GATEWAY_PORT) {
    throw new Error(
      `Invalid 'localPort': Gateway v1 strictly requires port ${CANONICAL_GATEWAY_PORT}, received ${portVal}`
    );
  }

  // 6. Backup configuration validation and normalization (v3/v4 or v2 defaults)
  let normalizedBackup = {
    maxTotalBytes: DEFAULT_MAX_TOTAL_BYTES,
    minKeepCount: DEFAULT_MIN_KEEP_COUNT,
  };

  if ((inputVersion === 3 || inputVersion === CURRENT_SCHEMA_VERSION) && config.backup !== undefined && config.backup !== null) {
    if (typeof config.backup !== 'object' || Array.isArray(config.backup)) {
      throw new TypeError('backup must be a non-null object');
    }

    for (const key of Object.keys(config.backup)) {
      if (!ALLOWED_BACKUP_KEYS.has(key)) {
        throw new Error(`Unknown backup configuration key: '${key}'`);
      }
    }

    if (config.backup.maxTotalBytes !== undefined) {
      const val = config.backup.maxTotalBytes;
      if (typeof val !== 'number' || !Number.isInteger(val) || !Number.isSafeInteger(val) || val <= 0) {
        throw new Error(`maxTotalBytes must be a positive safe integer, received ${val}`);
      }
      normalizedBackup.maxTotalBytes = val;
    }

    if (config.backup.minKeepCount !== undefined) {
      const val = config.backup.minKeepCount;
      if (typeof val !== 'number' || !Number.isInteger(val) || !Number.isSafeInteger(val) || val < 1) {
        throw new Error(`minKeepCount must be an integer >= 1, received ${val}`);
      }
      normalizedBackup.minKeepCount = val;
    }
  }

  // 7. Accounts configuration validation and normalization (v4 only, optional)
  let normalizedAccounts = {
    telegram: [],
  };

  if (inputVersion === CURRENT_SCHEMA_VERSION && config.accounts !== undefined && config.accounts !== null) {
    if (typeof config.accounts !== 'object' || Array.isArray(config.accounts)) {
      throw new TypeError('accounts must be a non-null object');
    }

    for (const key of Object.keys(config.accounts)) {
      if (!ALLOWED_ACCOUNTS_KEYS.has(key)) {
        throw new Error(`Unknown accounts configuration key: '${key}'`);
      }
    }

    if (config.accounts.telegram !== undefined && config.accounts.telegram !== null) {
      if (!Array.isArray(config.accounts.telegram)) {
        throw new TypeError('accounts.telegram must be an array');
      }

      const seenIds = new Set();
      const normalizedTg = [];

      for (let i = 0; i < config.accounts.telegram.length; i++) {
        const item = config.accounts.telegram[i];
        if (!item || typeof item !== 'object' || Array.isArray(item)) {
          throw new TypeError(`accounts.telegram[${i}] must be a non-null object`);
        }

        for (const itemKey of Object.keys(item)) {
          const lower = itemKey.toLowerCase();
          if (FORBIDDEN_SECRET_NAMES.has(lower)) {
            throw new Error(`Security rejection: Field '${itemKey}' is forbidden in accounts configuration (fail-closed)`);
          }
          if (!ALLOWED_TELEGRAM_ACCOUNT_KEYS.has(itemKey)) {
            throw new Error(`Unknown account field '${itemKey}' in accounts.telegram[${i}] (fail-closed)`);
          }
        }

        const { id, label, description, enabled } = item;

        if (typeof id !== 'string') {
          throw new TypeError(`accounts.telegram[${i}].id must be a non-empty string`);
        }
        if (CONTROL_CHAR_REGEX.test(id)) {
          throw new Error(`accounts.telegram[${i}].id contains forbidden control characters`);
        }
        if (!isWellFormedUtf16(id)) {
          throw new Error(`accounts.telegram[${i}].id contains ill-formed Unicode surrogate code units`);
        }
        const cleanId = id.trim();
        if (!cleanId) {
          throw new Error(`accounts.telegram[${i}].id must be a non-empty string`);
        }
        if (seenIds.has(cleanId)) {
          throw new Error(`Duplicate account id '${cleanId}' in accounts.telegram (fail-closed)`);
        }
        seenIds.add(cleanId);

        if (typeof label !== 'string' || !label.trim()) {
          throw new TypeError(`accounts.telegram[${i}].label must be a non-empty string`);
        }

        if (description !== undefined && typeof description !== 'string') {
          throw new TypeError(`accounts.telegram[${i}].description must be a string`);
        }

        if (enabled !== undefined && typeof enabled !== 'boolean') {
          throw new TypeError(`accounts.telegram[${i}].enabled must be a boolean`);
        }

        normalizedTg.push({
          id: cleanId,
          label: label.trim(),
          description: description !== undefined ? description.trim() : '',
          enabled: enabled !== undefined ? enabled : false, // Default is false per M3/M5
        });
      }

      normalizedAccounts.telegram = normalizedTg;
    }
  }

  return {
    schemaVersion: CURRENT_SCHEMA_VERSION,
    dataLocations: normalizedLocations,
    gateway: {
      localPort: CANONICAL_GATEWAY_PORT,
    },
    backup: normalizedBackup,
    accounts: normalizedAccounts,
  };
}

module.exports = {
  CURRENT_SCHEMA_VERSION,
  LEGACY_SUPPORTED_SCHEMA_VERSIONS: Array.from(LEGACY_SUPPORTED_SCHEMA_VERSIONS),
  LEGACY_SUPPORTED_SCHEMA_VERSION: 3, // For backward compatibility with older tests referencing this export
  DATA_LOCATION_SCHEMA_VERSION,
  CANONICAL_GATEWAY_PORT,
  DEFAULT_MAX_TOTAL_BYTES,
  DEFAULT_MIN_KEEP_COUNT,
  ALLOWED_TOP_LEVEL_KEYS: ALLOWED_TOP_LEVEL_KEYS_V4,
  ALLOWED_DATA_LOCATIONS_KEYS,
  ALLOWED_GATEWAY_KEYS,
  ALLOWED_BACKUP_KEYS,
  ALLOWED_ACCOUNTS_KEYS,
  REQUIRED_SINGLETON_PATHS,
  isAbsolutePath,
  assertSafeStateRootLocation,
  validateResolvedDataLocationConfig,
};
