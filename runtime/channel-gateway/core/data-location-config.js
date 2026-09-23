/**
 * runtime/channel-gateway/core/data-location-config.js
 *
 * ADR-0022 D24 / ADR-0025: Repo-External Data Location & Gateway Config Contract.
 *
 * Invariants:
 * - Pure validation contract for resolved repo-external data location and gateway configuration.
 * - NO filesystem operations (no fs.stat, no fs.mkdir, no fs.access).
 * - NO process.env access or OS known-folder resolution (handled by runtime loader).
 * - NO credentials, tokens, secrets, bot accounts, or listener sockets.
 * - Strict schema validation: rejects unknown top-level, dataLocations, and gateway keys.
 * - Path validation: all data paths must be non-empty trimmed strings and absolute.
 * - Cross-platform absolute path checking: compatible with Windows and POSIX absolute paths.
 * - Gateway configuration: gateway.localPort must be present, integer, and strictly 3003.
 * - Immutability: input object is never mutated; returns a clean normalized object.
 */

'use strict';

const path = require('node:path');

const DATA_LOCATION_SCHEMA_VERSION = 2;
const CANONICAL_GATEWAY_PORT = 3003;

const ALLOWED_TOP_LEVEL_KEYS = new Set([
  'schemaVersion',
  'dataLocations',
  'gateway',
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
 * Validates and normalizes a resolved data location and gateway configuration object.
 *
 * @param {object} config - Resolved configuration object
 * @returns {object} Normalized copy of the configuration
 * @throws {TypeError|Error} If schema, types, or paths are invalid
 */
function validateResolvedDataLocationConfig(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new TypeError('Configuration must be a non-null object');
  }

  // 1. Strict top-level schema validation
  for (const key of Object.keys(config)) {
    if (!ALLOWED_TOP_LEVEL_KEYS.has(key)) {
      throw new Error(`Unknown top-level configuration key: '${key}'`);
    }
  }

  if (config.schemaVersion === undefined) {
    throw new Error('Missing required field: schemaVersion');
  }

  if (
    typeof config.schemaVersion !== 'number' ||
    !Number.isInteger(config.schemaVersion) ||
    config.schemaVersion !== DATA_LOCATION_SCHEMA_VERSION
  ) {
    throw new Error(
      `Unsupported schemaVersion: expected ${DATA_LOCATION_SCHEMA_VERSION}, received ${config.schemaVersion}`
    );
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
      `Invalid gateway localPort: expected ${CANONICAL_GATEWAY_PORT}, received ${portVal}`
    );
  }

  return {
    schemaVersion: DATA_LOCATION_SCHEMA_VERSION,
    dataLocations: normalizedLocations,
    gateway: {
      localPort: CANONICAL_GATEWAY_PORT,
    },
  };
}

module.exports = {
  DATA_LOCATION_SCHEMA_VERSION,
  CANONICAL_GATEWAY_PORT,
  validateResolvedDataLocationConfig,
  isAbsolutePath,
};
