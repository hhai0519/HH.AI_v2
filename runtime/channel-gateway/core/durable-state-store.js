/**
 * runtime/channel-gateway/core/durable-state-store.js
 *
 * ADR-0022 D10: Channel Gateway Atomic Durable State Store Foundation.
 *
 * Invariants:
 * - Local durable state storage primitive for Channel Gateway.
 * - Single-purpose storage primitive: stores JSON snapshots in a versioned envelope.
 * - Zero domain knowledge: does NOT import or know ChannelControl, AccountRegistry, or AccountSwitchCoordinator.
 * - Constructor validates stateRoot: absolute, existing directory, readable, writable, canonicalized via fs.realpathSync.
 * - Zero auto-creation: NEVER calls fs.mkdirSync.
 * - Fixed state filename: channel-gateway-state.json (no caller override, zero path traversal surface).
 * - Strict versioned envelope:
 *   { schemaVersion: 1, revision: <non-negative safe integer>, payload: <plain object> }
 * - Strict recursive JSON compatibility validation: rejects undefined, function, symbol, bigint,
 *   NaN, Infinity, circular references, Date, Map, Set, or class instances (no silent-drop).
 * - Atomic file write: delegates exclusively to shared/atomicFs.js (writeStateAtomic).
 * - Fail-closed error handling on corrupt or invalid files: no auto-repair, no deletion, no partial returns.
 * - Symlink / non-regular file rejection on state file: fail-closed.
 * - Zero environment access (no process.env), zero credentials, zero network, zero ports.
 * - Zero third-party dependencies (Node.js built-ins node:fs, node:path and shared/atomicFs.js only).
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { writeStateAtomic } = require('../../../shared/atomicFs');
const { isAbsolutePath } = require('./data-location-config');

const STATE_FILENAME = 'channel-gateway-state.json';
const STATE_SCHEMA_VERSION = 1;

const ALLOWED_ENVELOPE_KEYS = new Set([
  'schemaVersion',
  'revision',
  'payload',
]);

/**
 * Recursively validates that a value is strictly JSON-compatible without silent data loss.
 *
 * @param {*} val - Value to validate
 * @param {Set<object>} [seen=new Set()] - Set of seen objects for circular reference detection
 * @param {string} [pathStr='payload'] - Current property path for clear error messages
 * @throws {TypeError} If any non-JSON-compatible value is found
 */
function validateJsonCompatiblePayload(val, seen = new Set(), pathStr = 'payload') {
  if (val === null) {
    return;
  }

  const valType = typeof val;

  if (valType === 'string' || valType === 'boolean') {
    return;
  }

  if (valType === 'number') {
    if (!Number.isFinite(val)) {
      throw new TypeError(`${pathStr}: number must be finite, received ${val}`);
    }
    return;
  }

  if (valType === 'bigint') {
    throw new TypeError(`${pathStr}: BigInt is not JSON-compatible`);
  }

  if (valType === 'undefined') {
    throw new TypeError(`${pathStr}: undefined is not JSON-compatible`);
  }

  if (valType === 'function') {
    throw new TypeError(`${pathStr}: function is not JSON-compatible`);
  }

  if (valType === 'symbol') {
    throw new TypeError(`${pathStr}: symbol is not JSON-compatible`);
  }

  if (valType === 'object') {
    if (seen.has(val)) {
      throw new TypeError(`${pathStr}: circular reference detected`);
    }

    seen.add(val);

    try {
      if (Array.isArray(val)) {
        const proto = Object.getPrototypeOf(val);
        if (proto !== Array.prototype) {
          throw new TypeError(`${pathStr}: array must not be a subclass instance`);
        }

        const len = val.length;
        if (typeof len !== 'number' || !Number.isSafeInteger(len) || len < 0) {
          throw new TypeError(`${pathStr}: array length must be a non-negative safe integer`);
        }

        for (let i = 0; i < len; i++) {
          const idxStr = String(i);
          if (!Object.prototype.hasOwnProperty.call(val, idxStr)) {
            throw new TypeError(`${pathStr}[${i}]: sparse arrays with holes are not allowed`);
          }
          const desc = Object.getOwnPropertyDescriptor(val, idxStr);
          if (!desc) {
            throw new TypeError(`${pathStr}[${i}]: unable to read element descriptor`);
          }
          if (desc.get !== undefined || desc.set !== undefined || !('value' in desc)) {
            throw new TypeError(`${pathStr}[${i}]: accessor properties on array indices are not allowed`);
          }
          if (desc.enumerable !== true) {
            throw new TypeError(`${pathStr}[${i}]: array elements must be enumerable`);
          }
        }

        const ownKeys = Reflect.ownKeys(val);
        for (const key of ownKeys) {
          if (typeof key === 'symbol') {
            throw new TypeError(`${pathStr}: Symbol-keyed properties on arrays are not allowed`);
          }

          if (key === 'length') {
            continue;
          }

          const num = Number(key);
          if (!Number.isInteger(num) || num < 0 || num >= len || String(num) !== key) {
            throw new TypeError(`${pathStr}: extra own property '${String(key)}' on array is not allowed`);
          }
        }

        for (let i = 0; i < len; i++) {
          validateJsonCompatiblePayload(val[i], seen, `${pathStr}[${i}]`);
        }
        return;
      }

      const proto = Object.getPrototypeOf(val);
      if (proto !== Object.prototype && proto !== null) {
        const ctorName = val.constructor ? val.constructor.name : 'custom prototype';
        throw new TypeError(`${pathStr}: object must be a plain object, received ${ctorName}`);
      }

      const ownKeys = Reflect.ownKeys(val);
      for (const key of ownKeys) {
        if (typeof key === 'symbol') {
          throw new TypeError(`${pathStr}: Symbol-keyed properties are not allowed`);
        }

        const desc = Object.getOwnPropertyDescriptor(val, key);
        if (!desc) {
          throw new TypeError(`${pathStr}.${key}: unable to read property descriptor`);
        }

        if (desc.get !== undefined || desc.set !== undefined || !('value' in desc)) {
          throw new TypeError(`${pathStr}.${key}: accessor properties (getters/setters) are not allowed`);
        }

        if (desc.enumerable !== true) {
          throw new TypeError(`${pathStr}.${key}: non-enumerable properties are not allowed`);
        }

        validateJsonCompatiblePayload(desc.value, seen, `${pathStr}.${key}`);
      }
    } finally {
      seen.delete(val);
    }
    return;
  }

  throw new TypeError(`${pathStr}: unsupported type '${valType}'`);
}

/**
 * Validates a state envelope object.
 *
 * @param {object} envelope
 * @throws {TypeError|Error}
 */
function validateEnvelope(envelope) {
  if (!envelope || typeof envelope !== 'object' || Array.isArray(envelope)) {
    throw new TypeError('Envelope must be a non-null plain object');
  }

  const envProto = Object.getPrototypeOf(envelope);
  if (envProto !== Object.prototype && envProto !== null) {
    throw new TypeError('Envelope must be a plain object');
  }

  const envKeys = Reflect.ownKeys(envelope);
  for (const key of envKeys) {
    if (typeof key === 'symbol') {
      throw new Error(`Unknown envelope key: '${String(key)}'`);
    }

    const desc = Object.getOwnPropertyDescriptor(envelope, key);
    if (!desc || desc.enumerable !== true || desc.get !== undefined || desc.set !== undefined) {
      throw new Error(`Invalid envelope property descriptor for '${key}'`);
    }

    if (!ALLOWED_ENVELOPE_KEYS.has(key)) {
      throw new Error(`Unknown envelope key: '${key}'`);
    }
  }

  if (envelope.schemaVersion === undefined) {
    throw new Error('Missing required envelope field: schemaVersion');
  }

  if (envelope.schemaVersion !== STATE_SCHEMA_VERSION) {
    throw new Error(
      `Unsupported schemaVersion: expected ${STATE_SCHEMA_VERSION}, received ${envelope.schemaVersion}`
    );
  }

  if (envelope.revision === undefined) {
    throw new Error('Missing required envelope field: revision');
  }

  if (
    typeof envelope.revision !== 'number' ||
    !Number.isSafeInteger(envelope.revision) ||
    envelope.revision < 0
  ) {
    throw new Error(
      `revision must be a non-negative safe integer: received ${envelope.revision}`
    );
  }

  if (!envelope.payload || typeof envelope.payload !== 'object' || Array.isArray(envelope.payload)) {
    throw new TypeError('payload must be a non-null plain object');
  }

  const payloadProto = Object.getPrototypeOf(envelope.payload);
  if (payloadProto !== Object.prototype && payloadProto !== null) {
    throw new TypeError('payload must be a plain object');
  }

  validateJsonCompatiblePayload(envelope.payload, new Set(), 'payload');
}

class DurableStateStore {
  /**
   * @param {string} stateRoot - Absolute path to existing, writable directory for state files.
   */
  constructor(stateRoot) {
    if (typeof stateRoot !== 'string') {
      throw new TypeError('stateRoot must be a string');
    }

    const trimmed = stateRoot.trim();
    if (!trimmed) {
      throw new Error('stateRoot must be a non-empty string');
    }

    if (!isAbsolutePath(trimmed)) {
      throw new Error(`stateRoot must be an absolute path: received '${stateRoot}'`);
    }

    const nominal = path.resolve(trimmed);
    let stat;
    try {
      stat = fs.statSync(nominal);
    } catch (err) {
      throw new Error(
        `stateRoot does not exist or cannot be accessed: '${nominal}' (${err.message})`
      );
    }

    if (!stat.isDirectory()) {
      throw new Error(`stateRoot must be a directory: '${nominal}'`);
    }

    try {
      fs.accessSync(nominal, fs.constants.R_OK | fs.constants.W_OK);
    } catch (err) {
      throw new Error(
        `stateRoot must be readable and writable: '${nominal}' (${err.message})`
      );
    }

    this.canonicalStateRoot = fs.realpathSync(nominal);
    this.stateFilePath = path.join(this.canonicalStateRoot, STATE_FILENAME);
  }

  /**
   * Loads and validates the current durable state envelope from disk.
   *
   * @returns {object|null} The validated envelope object, or null if no state file exists.
   * @throws {Error|TypeError} If file is a symlink, not regular, corrupt, or invalid schema.
   */
  load() {
    if (!fs.existsSync(this.stateFilePath)) {
      return null;
    }

    let lstat;
    try {
      lstat = fs.lstatSync(this.stateFilePath);
    } catch (err) {
      throw new Error(`Failed to stat state file: '${this.stateFilePath}' (${err.message})`);
    }

    if (lstat.isSymbolicLink()) {
      throw new Error(`State file must not be a symbolic link: '${this.stateFilePath}'`);
    }

    if (!lstat.isFile()) {
      throw new Error(`State file must be a regular file: '${this.stateFilePath}'`);
    }

    let canonicalFile;
    try {
      canonicalFile = fs.realpathSync(this.stateFilePath);
    } catch (err) {
      throw new Error(`Failed to resolve canonical path for state file: '${this.stateFilePath}' (${err.message})`);
    }

    const rel = path.relative(this.canonicalStateRoot, canonicalFile);
    if (rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel)) {
      throw new Error(
        `State file resolves outside canonical state root: '${canonicalFile}' is not within '${this.canonicalStateRoot}'`
      );
    }

    let raw;
    try {
      raw = fs.readFileSync(canonicalFile, 'utf8');
    } catch (err) {
      throw new Error(`Failed to read state file: '${canonicalFile}' (${err.message})`);
    }

    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      throw new Error(`Failed to parse state file as JSON: '${canonicalFile}' (${err.message})`);
    }

    validateEnvelope(parsed);

    return parsed;
  }

  /**
   * Atomically saves a new snapshot to the durable state file.
   *
   * @param {object} payload - Plain JSON-compatible object to store.
   * @returns {{ revision: number, stateFilePath: string }} Metadata of the saved snapshot.
   * @throws {TypeError|Error} If payload is invalid or write fails.
   */
  save(payload) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new TypeError('payload must be a non-null plain object');
    }

    const proto = Object.getPrototypeOf(payload);
    if (proto !== Object.prototype && proto !== null) {
      throw new TypeError('payload must be a plain object');
    }

    validateJsonCompatiblePayload(payload, new Set(), 'payload');

    if (fs.existsSync(this.stateFilePath)) {
      const lstat = fs.lstatSync(this.stateFilePath);
      if (lstat.isSymbolicLink()) {
        throw new Error(`Cannot save: existing state file is a symbolic link: '${this.stateFilePath}'`);
      }
      if (!lstat.isFile()) {
        throw new Error(`Cannot save: existing state file is not a regular file: '${this.stateFilePath}'`);
      }
    }

    let nextRevision = 1;
    if (fs.existsSync(this.stateFilePath)) {
      const current = this.load();
      if (current && typeof current.revision === 'number') {
        nextRevision = current.revision + 1;
      }
    }

    const envelope = {
      schemaVersion: STATE_SCHEMA_VERSION,
      revision: nextRevision,
      payload: JSON.parse(JSON.stringify(payload)),
    };

    validateEnvelope(envelope);

    const serialized = JSON.stringify(envelope, null, 2) + '\n';

    writeStateAtomic(this.stateFilePath, serialized);

    return {
      revision: nextRevision,
      stateFilePath: this.stateFilePath,
    };
  }
}

module.exports = {
  STATE_FILENAME,
  STATE_SCHEMA_VERSION,
  validateJsonCompatiblePayload,
  validateEnvelope,
  DurableStateStore,
};
