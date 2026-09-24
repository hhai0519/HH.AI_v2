/**
 * runtime/channel-gateway/core/data-location-config.js
 *
 * ADR-0022 D24 / ADR-0023 / TG-MVP-09A: Repo-External Data Location & Gateway Config Contract.
 *
 * Invariants:
 * - Pure validation contract for resolved repo-external data location and gateway configuration.
 * - NO filesystem operations (no fs.stat, no fs.mkdir, no fs.access).
 * - NO process.env access or OS known-folder resolution (handled by runtime loader).
 * - NO credentials, tokens, secrets, bot accounts, or listener sockets.
 * - Strict schema validation: supports schemaVersion 3 with backward compatibility for v2.
 * - v2: exact v2 keys only; rejects top-level backup key; normalizes in-memory to v3 with default backup policy.
 * - v3: allows optional top-level backup block with maxTotalBytes (>0 safe integer) and minKeepCount (>=1 safe integer).
 * - Rejects unknown top-level, dataLocations, gateway, and backup keys.
 * - Path validation: all data paths must be non-empty trimmed strings and absolute.
 * - Location guard helper: rejects UNC network paths and synchronized directory segments for stateRoot ONLY.
 * - Immutability: input object is never mutated; returns a clean normalized schemaVersion 3 object.
 */

'use strict';

const path = require('node:path');

const CURRENT_SCHEMA_VERSION = 3;
const LEGACY_SUPPORTED_SCHEMA_VERSION = 2;
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

const REQUIRED_SINGLETON_PATHS = [
  'archiveRoot',
  'attachmentTempRoot',
  'stateRoot',
  'logsRoot',
];

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
 * Rules (M16 / Section 10):
 * - Rejects UNC paths: \\server\share, //server/share, \\?\UNC\server\share, //?/UNC/server/share.
 * - Rejects known sync root directory segments (case-insensitive):
 *   OneDrive, Dropbox, Google Drive, GoogleDrive, iCloudDrive.
 * - Applies strictly to stateRoot (archiveRoot and other roots are never tested here).
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
 * @returns {object} Normalized copy of the configuration (schemaVersion 3)
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
    (config.schemaVersion !== LEGACY_SUPPORTED_SCHEMA_VERSION &&
      config.schemaVersion !== CURRENT_SCHEMA_VERSION)
  ) {
    throw new Error(
      `Unsupported schemaVersion: expected ${CURRENT_SCHEMA_VERSION} or ${LEGACY_SUPPORTED_SCHEMA_VERSION}, received ${config.schemaVersion}`
    );
  }

  const inputVersion = config.schemaVersion;

  // 1. Top-level key validation based on declared version
  if (inputVersion === LEGACY_SUPPORTED_SCHEMA_VERSION) {
    for (const key of Object.keys(config)) {
      if (!ALLOWED_TOP_LEVEL_KEYS_V2.has(key)) {
        throw new Error(`Unknown top-level configuration key: '${key}'`);
      }
    }
  } else {
    for (const key of Object.keys(config)) {
      if (!ALLOWED_TOP_LEVEL_KEYS_V3.has(key)) {
        throw new Error(`Unknown top-level configuration key: '${key}'`);
      }
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

  // 6. Backup configuration validation and normalization (v3 or v2 defaults)
  let normalizedBackup = {
    maxTotalBytes: DEFAULT_MAX_TOTAL_BYTES,
    minKeepCount: DEFAULT_MIN_KEEP_COUNT,
  };

  if (inputVersion === CURRENT_SCHEMA_VERSION && config.backup !== undefined && config.backup !== null) {
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

  return {
    schemaVersion: CURRENT_SCHEMA_VERSION,
    dataLocations: normalizedLocations,
    gateway: {
      localPort: CANONICAL_GATEWAY_PORT,
    },
    backup: normalizedBackup,
  };
}

module.exports = {
  CURRENT_SCHEMA_VERSION,
  LEGACY_SUPPORTED_SCHEMA_VERSION,
  DATA_LOCATION_SCHEMA_VERSION,
  CANONICAL_GATEWAY_PORT,
  DEFAULT_MAX_TOTAL_BYTES,
  DEFAULT_MIN_KEEP_COUNT,
  ALLOWED_TOP_LEVEL_KEYS: ALLOWED_TOP_LEVEL_KEYS_V3,
  ALLOWED_DATA_LOCATIONS_KEYS,
  ALLOWED_GATEWAY_KEYS,
  ALLOWED_BACKUP_KEYS,
  REQUIRED_SINGLETON_PATHS,
  isAbsolutePath,
  assertSafeStateRootLocation,
  validateResolvedDataLocationConfig,
};
