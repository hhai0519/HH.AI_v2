/**
 * runtime/channel-gateway/core/channel-state-persistence.js
 *
 * ADR-0022 D5, D9, D10: Multi-Channel Durable State Persistence Bridge.
 *
 * Invariants:
 * - Bridges pure ChannelControl snapshots with DurableStateStore.
 * - Single fixed channel-gateway-state.json file houses multiple independent channel snapshots.
 * - Zero network, zero filesystem I/O directly in this module (all I/O delegated to DurableStateStore).
 * - Zero process.env, zero timer, zero third-party dependencies.
 * - Deterministic canonical channel ordering by channelId.
 * - Cross-channel state preservation: updating or recovering one channel never drops or corrupts others.
 * - Safe restart recovery write-back: CLAIMED -> DISCARDED mutations persisted exactly once before returning.
 * - Read-only recovery idempotence: no-op recoveries do not bump durable store revision.
 * - AccountRegistry and credential persistence deliberately deferred.
 */

'use strict';

const { ChannelControl } = require('./channel-control');
const {
  validateChannelControlSnapshot,
  buildChannelControlSnapshot,
  recoverChannelControlFromSnapshot,
} = require('./channel-state-recovery');
const { DurableStateStore } = require('./durable-state-store');

const CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION = 1;

const ALLOWED_PAYLOAD_KEYS = new Set([
  'schemaVersion',
  'channels',
]);

/**
 * Validates a multi-channel state payload object.
 *
 * @param {object} payload
 * @param {string} [pathStr='payload']
 * @throws {TypeError|Error} If payload violates multi-channel schema or constraints
 */
function validateChannelStatePayload(payload, pathStr = 'payload') {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new TypeError(`${pathStr}: must be a non-null plain object`);
  }

  const proto = Object.getPrototypeOf(payload);
  if (proto !== Object.prototype && proto !== null) {
    throw new TypeError(`${pathStr}: must be a plain object`);
  }

  const keys = Reflect.ownKeys(payload);
  for (const key of keys) {
    if (typeof key === 'symbol') {
      throw new Error(`${pathStr}: Symbol keys are not allowed`);
    }

    const desc = Object.getOwnPropertyDescriptor(payload, key);
    if (!desc || desc.enumerable !== true || desc.get !== undefined || desc.set !== undefined) {
      throw new Error(`${pathStr}: invalid property descriptor for '${key}'`);
    }

    if (!ALLOWED_PAYLOAD_KEYS.has(key)) {
      throw new Error(`${pathStr}: unknown payload key: '${key}'`);
    }
  }

  if (payload.schemaVersion === undefined) {
    throw new Error(`${pathStr}: missing required field: schemaVersion`);
  }
  if (payload.schemaVersion !== CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION) {
    throw new Error(
      `${pathStr}: unsupported schemaVersion: expected ${CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION}, received ${payload.schemaVersion}`
    );
  }

  if (!Array.isArray(payload.channels)) {
    throw new TypeError(`${pathStr}.channels: must be an array`);
  }

  const seenChannelIds = new Set();
  for (let i = 0; i < payload.channels.length; i++) {
    const channelSnapshot = payload.channels[i];
    validateChannelControlSnapshot(channelSnapshot);

    if (seenChannelIds.has(channelSnapshot.channelId)) {
      throw new Error(
        `${pathStr}.channels[${i}]: duplicate channelId in payload: '${channelSnapshot.channelId}'`
      );
    }
    seenChannelIds.add(channelSnapshot.channelId);
  }
}

/**
 * Deterministically sorts an array of channel snapshots by channelId.
 * Does not mutate the input array or alter internal message ordering.
 *
 * @param {Array<object>} channels
 * @returns {Array<object>} Sorted copy
 */
function sortChannelsCanonical(channels) {
  return [...channels].sort((a, b) => {
    if (a.channelId < b.channelId) return -1;
    if (a.channelId > b.channelId) return 1;
    return 0;
  });
}

/**
 * Repository coordinating multi-channel snapshot persistence through a DurableStateStore instance.
 */
class DurableChannelStateRepository {
  /**
   * @param {DurableStateStore} store
   */
  constructor(store) {
    if (!store || !(store instanceof DurableStateStore)) {
      throw new TypeError('store must be an instance of DurableStateStore');
    }
    this._store = store;
  }

  /**
   * @returns {DurableStateStore}
   */
  get store() {
    return this._store;
  }

  /**
   * Saves a single ChannelControl instance into the multi-channel durable payload,
   * preserving all other channel snapshots and maintaining canonical sort order.
   *
   * @param {ChannelControl} control
   * @returns {{ channelId: string, revision: number, stateFilePath: string, channelCount: number }}
   */
  saveChannel(control) {
    if (!control || !(control instanceof ChannelControl)) {
      throw new TypeError('control must be an instance of ChannelControl');
    }

    // Step B: Build snapshot first. Invalid live metadata fails here before store read or write.
    const newSnapshot = buildChannelControlSnapshot(control);

    // Step C: Load existing payload from store
    const envelope = this._store.load();
    let currentChannels = [];

    if (envelope !== null) {
      validateChannelStatePayload(envelope.payload, 'envelope.payload');
      currentChannels = envelope.payload.channels;
    }

    // Step D & E: Replace existing snapshot for this channelId or append new snapshot; preserve others
    const filteredChannels = currentChannels.filter(
      (s) => s.channelId !== newSnapshot.channelId
    );
    filteredChannels.push(newSnapshot);

    // Step F: Canonical lexical sort by channelId
    const sortedChannels = sortChannelsCanonical(filteredChannels);

    const nextPayload = {
      schemaVersion: CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION,
      channels: sortedChannels,
    };

    validateChannelStatePayload(nextPayload);

    // Step G: Save to durable store exactly once
    const saveResult = this._store.save(nextPayload);

    // Step H: Return operation summary
    return {
      channelId: newSnapshot.channelId,
      revision: saveResult.revision,
      stateFilePath: saveResult.stateFilePath,
      channelCount: sortedChannels.length,
    };
  }

  /**
   * Loads a ChannelControl instance from durable store or creates a fresh instance if none exists.
   * If claimed messages were converted to discarded on restart, writes back the recovery mutation
   * immediately before returning.
   *
   * @param {string} channelId - Channel identifier (e.g. 'telegram', 'line')
   * @returns {{ control: ChannelControl, firstStart: boolean, discardedOnRecovery: Array<object>, recoveryPersisted: boolean, revision: (number|null) }}
   */
  loadOrCreateChannel(channelId) {
    if (typeof channelId !== 'string' || !channelId.trim()) {
      throw new TypeError('channelId must be a non-empty string');
    }
    const cleanChannelId = channelId.trim();

    const envelope = this._store.load();

    // Step A: Store is empty (first start across all channels)
    if (envelope === null) {
      return {
        control: new ChannelControl(cleanChannelId),
        firstStart: true,
        discardedOnRecovery: [],
        recoveryPersisted: false,
        revision: null,
      };
    }

    // Step B: Existing envelope present -> validate entire multi-channel payload
    validateChannelStatePayload(envelope.payload, 'envelope.payload');

    // Step C: Look for requested channel
    const matchingSnapshot = envelope.payload.channels.find(
      (s) => s.channelId === cleanChannelId
    );

    if (!matchingSnapshot) {
      return {
        control: new ChannelControl(cleanChannelId),
        firstStart: true,
        discardedOnRecovery: [],
        recoveryPersisted: false,
        revision: envelope.revision,
      };
    }

    // Step D: Channel found -> recover control with safe restart semantics
    const recoveryResult = recoverChannelControlFromSnapshot(matchingSnapshot);
    const recoveredControl = recoveryResult.control;
    const discardedOnRecovery = recoveryResult.discardedOnRecovery;

    let recoveryPersisted = false;
    let finalRevision = envelope.revision;

    // Section 12: If restart conversion occurred (CLAIMED -> DISCARDED), persist write-back immediately
    if (discardedOnRecovery.length > 0) {
      const recoveredSnapshot = buildChannelControlSnapshot(recoveredControl);

      const otherChannels = envelope.payload.channels.filter(
        (s) => s.channelId !== cleanChannelId
      );
      otherChannels.push(recoveredSnapshot);

      const nextPayload = {
        schemaVersion: CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION,
        channels: sortChannelsCanonical(otherChannels),
      };

      validateChannelStatePayload(nextPayload);

      // Save write-back; if this throws, caller does not receive recovered control (fail-closed)
      const saveRes = this._store.save(nextPayload);
      recoveryPersisted = true;
      finalRevision = saveRes.revision;
    }

    return {
      control: recoveredControl,
      firstStart: false,
      discardedOnRecovery,
      recoveryPersisted,
      revision: finalRevision,
    };
  }
}

module.exports = {
  CHANNEL_STATE_PAYLOAD_SCHEMA_VERSION,
  validateChannelStatePayload,
  DurableChannelStateRepository,
};
