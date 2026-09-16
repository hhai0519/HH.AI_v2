/**
 * runtime/channel-gateway/core/channel-state-recovery.js
 *
 * ADR-0022 D10: Channel Control Durable Snapshot & Safe Restart Recovery.
 *
 * Invariants:
 * - Pure snapshot / restart recovery domain boundary between ChannelControl and DurableStateStore.
 * - Single-purpose domain codec: exports and validates snapshot, performs safe restart recovery.
 * - Zero network, zero filesystem I/O, zero process.env, zero timer side effects.
 * - Process restart safety:
 *   * currentHolder = null (never revive pre-restart holder; holder denotes active Agent/session).
 *   * lastHeartbeatAt = null (never revive pre-restart heartbeat freshness).
 *   * fencingToken = preserved from snapshot (never reset to 0, never incremented during recovery).
 *   * QUEUED messages = PRESERVED (unattended persistent backlog per D10).
 *   * CLAIMED messages = DISCARDED with reason 'GATEWAY_RESTART' (holder lost during restart per D9).
 *   * REPLIED / already DISCARDED messages = PRESERVED.
 *   * Subsequent takeover increments fencingToken N -> N+1, rendering pre-restart token stale.
 *   * Backlog count strictly counts QUEUED messages.
 * - Zero third-party dependencies (Node built-in and local core modules only).
 */

'use strict';

const { ChannelControl, MESSAGE_STATUS } = require('./channel-control');
const { validateJsonCompatiblePayload } = require('./durable-state-store');

const CHANNEL_SNAPSHOT_SCHEMA_VERSION = 1;

const ALLOWED_TOP_LEVEL_KEYS = new Set([
  'schemaVersion',
  'channelId',
  'fencingToken',
  'messages',
]);

const ALLOWED_MESSAGE_KEYS = new Set([
  'id',
  'receivingAccountId',
  'status',
  'claimedBy',
  'claimedAtToken',
  'discardReason',
  'metadata',
  'discardedByHolder',
  'discardedAtToken',
]);

const VALID_STATUSES = new Set([
  MESSAGE_STATUS.QUEUED,
  MESSAGE_STATUS.CLAIMED,
  MESSAGE_STATUS.DISCARDED,
  MESSAGE_STATUS.REPLIED,
]);

/**
 * Validates a message snapshot object.
 *
 * @param {object} msg - The message object to validate
 * @param {number} snapshotFencingToken - The parent snapshot's fencing token
 * @param {string} pathStr - Diagnostic path string
 * @throws {TypeError|Error} If message violates schema or status invariants
 */
function validateMessageSnapshot(msg, snapshotFencingToken, pathStr) {
  if (!msg || typeof msg !== 'object' || Array.isArray(msg)) {
    throw new TypeError(`${pathStr}: message must be a non-null plain object`);
  }

  const proto = Object.getPrototypeOf(msg);
  if (proto !== Object.prototype && proto !== null) {
    throw new TypeError(`${pathStr}: message must be a plain object`);
  }

  const keys = Reflect.ownKeys(msg);
  for (const key of keys) {
    if (typeof key === 'symbol') {
      throw new Error(`${pathStr}: Symbol keys are not allowed in message snapshot`);
    }

    const desc = Object.getOwnPropertyDescriptor(msg, key);
    if (!desc || desc.enumerable !== true || desc.get !== undefined || desc.set !== undefined) {
      throw new Error(`${pathStr}: invalid property descriptor for '${key}'`);
    }

    if (!ALLOWED_MESSAGE_KEYS.has(key)) {
      throw new Error(`${pathStr}: unknown message key: '${key}'`);
    }
  }

  // id validation
  if (typeof msg.id !== 'string' || !msg.id.trim()) {
    throw new TypeError(`${pathStr}.id: must be a non-empty string`);
  }

  // receivingAccountId validation
  if (typeof msg.receivingAccountId !== 'string' || !msg.receivingAccountId.trim()) {
    throw new TypeError(`${pathStr}.receivingAccountId: must be a non-empty string`);
  }

  // status validation
  if (!VALID_STATUSES.has(msg.status)) {
    throw new Error(`${pathStr}.status: invalid message status '${msg.status}'`);
  }

  // metadata validation
  if (!msg.metadata || typeof msg.metadata !== 'object' || Array.isArray(msg.metadata)) {
    throw new TypeError(`${pathStr}.metadata: must be a non-null plain object`);
  }
  const metaProto = Object.getPrototypeOf(msg.metadata);
  if (metaProto !== Object.prototype && metaProto !== null) {
    throw new TypeError(`${pathStr}.metadata: must be a plain object`);
  }
  validateJsonCompatiblePayload(msg.metadata, new Set(), `${pathStr}.metadata`);

  // Status-specific invariants
  if (msg.status === MESSAGE_STATUS.QUEUED) {
    if (msg.claimedBy !== null) {
      throw new Error(`${pathStr}: QUEUED message must have claimedBy === null`);
    }
    if (msg.claimedAtToken !== null) {
      throw new Error(`${pathStr}: QUEUED message must have claimedAtToken === null`);
    }
    if (msg.discardReason !== null) {
      throw new Error(`${pathStr}: QUEUED message must have discardReason === null`);
    }
    if (msg.discardedByHolder !== null) {
      throw new Error(`${pathStr}: QUEUED message must have discardedByHolder === null`);
    }
    if (msg.discardedAtToken !== null) {
      throw new Error(`${pathStr}: QUEUED message must have discardedAtToken === null`);
    }
  } else if (msg.status === MESSAGE_STATUS.CLAIMED) {
    if (typeof msg.claimedBy !== 'string' || !msg.claimedBy.trim()) {
      throw new Error(`${pathStr}: CLAIMED message must have non-empty claimedBy`);
    }
    if (
      typeof msg.claimedAtToken !== 'number' ||
      !Number.isSafeInteger(msg.claimedAtToken) ||
      msg.claimedAtToken < 0
    ) {
      throw new Error(`${pathStr}: CLAIMED message must have a non-negative safe integer claimedAtToken`);
    }
    if (msg.claimedAtToken !== snapshotFencingToken) {
      throw new Error(
        `${pathStr}: CLAIMED message claimedAtToken (${msg.claimedAtToken}) must match snapshot fencingToken (${snapshotFencingToken})`
      );
    }
    if (msg.discardReason !== null) {
      throw new Error(`${pathStr}: CLAIMED message must have discardReason === null`);
    }
    if (msg.discardedByHolder !== null) {
      throw new Error(`${pathStr}: CLAIMED message must have discardedByHolder === null`);
    }
    if (msg.discardedAtToken !== null) {
      throw new Error(`${pathStr}: CLAIMED message must have discardedAtToken === null`);
    }
  } else if (msg.status === MESSAGE_STATUS.REPLIED) {
    if (typeof msg.claimedBy !== 'string' || !msg.claimedBy.trim()) {
      throw new Error(`${pathStr}: REPLIED message must have non-empty claimedBy`);
    }
    if (
      typeof msg.claimedAtToken !== 'number' ||
      !Number.isSafeInteger(msg.claimedAtToken) ||
      msg.claimedAtToken < 0
    ) {
      throw new Error(`${pathStr}: REPLIED message must have a non-negative safe integer claimedAtToken`);
    }
    if (msg.claimedAtToken > snapshotFencingToken) {
      throw new Error(
        `${pathStr}: REPLIED message claimedAtToken (${msg.claimedAtToken}) cannot exceed snapshot fencingToken (${snapshotFencingToken})`
      );
    }
    if (msg.discardReason !== null) {
      throw new Error(`${pathStr}: REPLIED message must have discardReason === null`);
    }
    if (msg.discardedByHolder !== null) {
      throw new Error(`${pathStr}: REPLIED message must have discardedByHolder === null`);
    }
    if (msg.discardedAtToken !== null) {
      throw new Error(`${pathStr}: REPLIED message must have discardedAtToken === null`);
    }
  } else if (msg.status === MESSAGE_STATUS.DISCARDED) {
    if (typeof msg.discardReason !== 'string' || !msg.discardReason.trim()) {
      throw new Error(`${pathStr}: DISCARDED message must have non-empty discardReason`);
    }

    if (msg.claimedBy === null) {
      if (msg.claimedAtToken !== null) {
        throw new Error(`${pathStr}: DISCARDED message with null claimedBy must have null claimedAtToken`);
      }
    } else {
      if (typeof msg.claimedBy !== 'string' || !msg.claimedBy.trim()) {
        throw new Error(`${pathStr}: DISCARDED message claimedBy must be null or non-empty string`);
      }
      if (
        typeof msg.claimedAtToken !== 'number' ||
        !Number.isSafeInteger(msg.claimedAtToken) ||
        msg.claimedAtToken < 0 ||
        msg.claimedAtToken > snapshotFencingToken
      ) {
        throw new Error(
          `${pathStr}: DISCARDED message claimedAtToken must be non-negative safe integer <= fencingToken (${snapshotFencingToken})`
        );
      }
    }

    if (msg.discardedByHolder !== null) {
      if (typeof msg.discardedByHolder !== 'string' || !msg.discardedByHolder.trim()) {
        throw new Error(`${pathStr}: discardedByHolder must be null or non-empty string`);
      }
    }

    if (msg.discardedAtToken !== null) {
      if (
        typeof msg.discardedAtToken !== 'number' ||
        !Number.isSafeInteger(msg.discardedAtToken) ||
        msg.discardedAtToken < 0 ||
        msg.discardedAtToken > snapshotFencingToken
      ) {
        throw new Error(
          `${pathStr}: discardedAtToken must be null or non-negative safe integer <= fencingToken (${snapshotFencingToken})`
        );
      }
    }
  }
}

/**
 * Strictly validates a ChannelControl snapshot object.
 *
 * @param {object} snapshot
 * @throws {TypeError|Error}
 */
function validateChannelControlSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) {
    throw new TypeError('Snapshot must be a non-null plain object');
  }

  const proto = Object.getPrototypeOf(snapshot);
  if (proto !== Object.prototype && proto !== null) {
    throw new TypeError('Snapshot must be a plain object');
  }

  const keys = Reflect.ownKeys(snapshot);
  for (const key of keys) {
    if (typeof key === 'symbol') {
      throw new Error(`Unknown snapshot key: Symbol`);
    }

    const desc = Object.getOwnPropertyDescriptor(snapshot, key);
    if (!desc || desc.enumerable !== true || desc.get !== undefined || desc.set !== undefined) {
      throw new Error(`Invalid snapshot property descriptor for '${key}'`);
    }

    if (!ALLOWED_TOP_LEVEL_KEYS.has(key)) {
      throw new Error(`Unknown top-level snapshot key: '${key}'`);
    }
  }

  if (snapshot.schemaVersion === undefined) {
    throw new Error('Missing required snapshot field: schemaVersion');
  }
  if (snapshot.schemaVersion !== CHANNEL_SNAPSHOT_SCHEMA_VERSION) {
    throw new Error(
      `Unsupported snapshot schemaVersion: expected ${CHANNEL_SNAPSHOT_SCHEMA_VERSION}, received ${snapshot.schemaVersion}`
    );
  }

  if (typeof snapshot.channelId !== 'string' || !snapshot.channelId.trim()) {
    throw new TypeError('channelId must be a non-empty string');
  }

  if (
    typeof snapshot.fencingToken !== 'number' ||
    !Number.isSafeInteger(snapshot.fencingToken) ||
    snapshot.fencingToken < 0
  ) {
    throw new Error(
      `fencingToken must be a non-negative safe integer: received ${snapshot.fencingToken}`
    );
  }

  if (!Array.isArray(snapshot.messages)) {
    throw new TypeError('messages must be an array');
  }

  const seenIds = new Set();
  for (let i = 0; i < snapshot.messages.length; i++) {
    const msg = snapshot.messages[i];
    validateMessageSnapshot(msg, snapshot.fencingToken, `messages[${i}]`);

    if (seenIds.has(msg.id)) {
      throw new Error(`Duplicate message id in snapshot: '${msg.id}'`);
    }
    seenIds.add(msg.id);
  }
}

/**
 * Builds a clean, deep-copied canonical snapshot from a live ChannelControl instance.
 *
 * @param {ChannelControl} control
 * @returns {object} Canonical plain snapshot object
 */
function buildChannelControlSnapshot(control) {
  if (!control || !(control instanceof ChannelControl)) {
    throw new TypeError('control must be an instance of ChannelControl');
  }

  const canonicalMessages = [];
  for (const msg of control.messages) {
    canonicalMessages.push({
      id: msg.id,
      receivingAccountId: msg.receivingAccountId,
      status: msg.status,
      claimedBy: msg.claimedBy !== undefined ? msg.claimedBy : null,
      claimedAtToken: msg.claimedAtToken !== undefined ? msg.claimedAtToken : null,
      discardReason: msg.discardReason !== undefined ? msg.discardReason : null,
      metadata: JSON.parse(JSON.stringify(msg.metadata || {})),
      discardedByHolder: msg.discardedByHolder !== undefined ? msg.discardedByHolder : null,
      discardedAtToken: msg.discardedAtToken !== undefined ? msg.discardedAtToken : null,
    });
  }

  const snapshot = {
    schemaVersion: CHANNEL_SNAPSHOT_SCHEMA_VERSION,
    channelId: control.channelId,
    fencingToken: control.fencingToken,
    messages: canonicalMessages,
  };

  validateChannelControlSnapshot(snapshot);

  return snapshot;
}

/**
 * Recovers a ChannelControl instance from a durable snapshot with safe restart semantics.
 *
 * @param {object} snapshot - Untrusted snapshot object
 * @returns {{ control: ChannelControl, discardedOnRecovery: Array<object> }}
 */
function recoverChannelControlFromSnapshot(snapshot) {
  validateChannelControlSnapshot(snapshot);

  const control = new ChannelControl(snapshot.channelId);
  control.fencingToken = snapshot.fencingToken;
  control.currentHolder = null;
  control.lastHeartbeatAt = null;

  const discardedOnRecovery = [];
  const recoveredMessages = [];

  for (const msg of snapshot.messages) {
    const recoveredMsg = {
      id: msg.id,
      receivingAccountId: msg.receivingAccountId,
      status: msg.status,
      claimedBy: msg.claimedBy,
      claimedAtToken: msg.claimedAtToken,
      discardReason: msg.discardReason,
      metadata: JSON.parse(JSON.stringify(msg.metadata)),
      discardedByHolder: msg.discardedByHolder,
      discardedAtToken: msg.discardedAtToken,
    };

    // D9 / D10 Restart Safety: CLAIMED messages become DISCARDED with reason 'GATEWAY_RESTART'
    if (recoveredMsg.status === MESSAGE_STATUS.CLAIMED) {
      recoveredMsg.status = MESSAGE_STATUS.DISCARDED;
      recoveredMsg.discardReason = 'GATEWAY_RESTART';
      recoveredMsg.discardedByHolder = msg.claimedBy;
      recoveredMsg.discardedAtToken = snapshot.fencingToken;

      discardedOnRecovery.push({
        id: recoveredMsg.id,
        receivingAccountId: recoveredMsg.receivingAccountId,
        status: recoveredMsg.status,
        discardReason: recoveredMsg.discardReason,
      });
    }

    recoveredMessages.push(recoveredMsg);
  }

  control.messages = recoveredMessages;

  return {
    control,
    discardedOnRecovery,
  };
}

module.exports = {
  CHANNEL_SNAPSHOT_SCHEMA_VERSION,
  validateChannelControlSnapshot,
  buildChannelControlSnapshot,
  recoverChannelControlFromSnapshot,
};
