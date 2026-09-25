/**
 * runtime/channel-gateway/core/local-api-replay-cache.js
 *
 * TG-MVP-11: Bounded HELLO Replay Cache & Session Nonce Tracker.
 */

'use strict';

const {
  HELLO_CACHE_MAX,
  NONCE_RETENTION_SEC,
} = require('./local-api-codec');

class LocalApiReplayCache {
  /**
   * @param {object} [options]
   * @param {number} [options.maxEntries=4096]
   * @param {number} [options.retentionSec=60]
   * @param {() => number} [options.nowSec] Injectable clock returning seconds since epoch
   */
  constructor(options = {}) {
    this.maxEntries = options.maxEntries || HELLO_CACHE_MAX;
    this.retentionSec = options.retentionSec || NONCE_RETENTION_SEC;
    this.nowSec = options.nowSec || (() => Math.floor(Date.now() / 1000));

    // Map: nonce -> expiresAtSec
    this._helloCache = new Map();

    // Map: sessionId -> Set<nonce>
    this._sessionNonces = new Map();
  }

  /**
   * Prunes expired entries from the HELLO cache.
   *
   * @returns {number} Count of pruned entries
   */
  pruneExpired() {
    const now = this.nowSec();
    let pruned = 0;
    for (const [nonce, expiresAt] of this._helloCache.entries()) {
      if (expiresAt <= now) {
        this._helloCache.delete(nonce);
        pruned++;
      }
    }
    return pruned;
  }

  /**
   * Checks if a HELLO nonce can be admitted, WITHOUT adding it.
   * Prunes expired entries first.
   *
   * @param {string} nonce
   * @returns {{ allowed: boolean, reason?: 'REPLAY_DETECTED' | 'REPLAY_CACHE_FULL' }}
   */
  checkHelloAdmission(nonce) {
    if (!nonce || typeof nonce !== 'string') {
      return { allowed: false, reason: 'REPLAY_DETECTED' };
    }

    this.pruneExpired();

    const now = this.nowSec();
    const existingExpiry = this._helloCache.get(nonce);
    if (existingExpiry !== undefined && existingExpiry > now) {
      return { allowed: false, reason: 'REPLAY_DETECTED' };
    }

    // Never evict an unexpired nonce merely to admit a new one
    if (this._helloCache.size >= this.maxEntries) {
      return { allowed: false, reason: 'REPLAY_CACHE_FULL' };
    }

    return { allowed: true };
  }

  /**
   * Records a HELLO nonce into the replay cache AFTER HMAC verification succeeds.
   *
   * @param {string} nonce
   * @returns {boolean} True if recorded, false if cache was full or already exists
   */
  recordHelloNonce(nonce) {
    const admission = this.checkHelloAdmission(nonce);
    if (!admission.allowed) {
      return false;
    }
    const expiresAt = this.nowSec() + this.retentionSec;
    this._helloCache.set(nonce, expiresAt);
    return true;
  }

  /**
   * Checks and records a session nonce for the given session.
   *
   * @param {string} sessionId
   * @param {string} nonce
   * @returns {{ allowed: boolean, reason?: 'REPLAY_DETECTED' }}
   */
  checkAndRecordSessionNonce(sessionId, nonce) {
    if (!sessionId || !nonce) {
      return { allowed: false, reason: 'REPLAY_DETECTED' };
    }

    let nonces = this._sessionNonces.get(sessionId);
    if (!nonces) {
      nonces = new Set();
      this._sessionNonces.set(sessionId, nonces);
    }

    if (nonces.has(nonce)) {
      return { allowed: false, reason: 'REPLAY_DETECTED' };
    }

    nonces.add(nonce);
    return { allowed: true };
  }

  /**
   * Cleans up all nonces associated with a closed/terminated session.
   *
   * @param {string} sessionId
   */
  clearSession(sessionId) {
    if (sessionId) {
      this._sessionNonces.delete(sessionId);
    }
  }

  /**
   * Current count of HELLO cache entries.
   *
   * @returns {number}
   */
  get helloCacheSize() {
    return this._helloCache.size;
  }
}

module.exports = {
  LocalApiReplayCache,
};
