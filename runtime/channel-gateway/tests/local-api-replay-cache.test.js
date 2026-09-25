/**
 * runtime/channel-gateway/tests/local-api-replay-cache.test.js
 *
 * Tests for LocalApiReplayCache: HELLO bounds, retention, expiry, capacity & session nonces.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { LocalApiReplayCache } = require('../core/local-api-replay-cache');

test('replay cache: admits and records fresh HELLO nonce', { timeout: 5000 }, () => {
  let currentTime = 1000;
  const cache = new LocalApiReplayCache({ nowSec: () => currentTime });

  const admission = cache.checkHelloAdmission('nonce-1');
  assert.equal(admission.allowed, true);

  const recorded = cache.recordHelloNonce('nonce-1');
  assert.equal(recorded, true);
  assert.equal(cache.helloCacheSize, 1);
});

test('replay cache: rejects duplicate HELLO nonce within retention window (T8)', { timeout: 5000 }, () => {
  let currentTime = 1000;
  const cache = new LocalApiReplayCache({
    retentionSec: 60,
    nowSec: () => currentTime,
  });

  assert.equal(cache.recordHelloNonce('nonce-dup'), true);

  // Immediate second check
  const dupCheck = cache.checkHelloAdmission('nonce-dup');
  assert.equal(dupCheck.allowed, false);
  assert.equal(dupCheck.reason, 'REPLAY_DETECTED');

  // Advance clock within retention (59s)
  currentTime = 1059;
  const stillDup = cache.checkHelloAdmission('nonce-dup');
  assert.equal(stillDup.allowed, false);
  assert.equal(stillDup.reason, 'REPLAY_DETECTED');
});

test('replay cache: admits nonce after retention window expires', { timeout: 5000 }, () => {
  let currentTime = 1000;
  const cache = new LocalApiReplayCache({
    retentionSec: 60,
    nowSec: () => currentTime,
  });

  assert.equal(cache.recordHelloNonce('nonce-exp'), true);

  // Advance clock past 60s
  currentTime = 1061;
  const expiredCheck = cache.checkHelloAdmission('nonce-exp');
  assert.equal(expiredCheck.allowed, true);

  assert.equal(cache.recordHelloNonce('nonce-exp'), true);
});

test('replay cache: returns REPLAY_CACHE_FULL when maxEntries reached without evicting unexpired nonces', { timeout: 5000 }, () => {
  let currentTime = 1000;
  const cache = new LocalApiReplayCache({
    maxEntries: 3,
    retentionSec: 60,
    nowSec: () => currentTime,
  });

  assert.equal(cache.recordHelloNonce('n1'), true);
  assert.equal(cache.recordHelloNonce('n2'), true);
  assert.equal(cache.recordHelloNonce('n3'), true);
  assert.equal(cache.helloCacheSize, 3);

  // 4th nonce cannot be admitted
  const fullCheck = cache.checkHelloAdmission('n4');
  assert.equal(fullCheck.allowed, false);
  assert.equal(fullCheck.reason, 'REPLAY_CACHE_FULL');
  assert.equal(cache.recordHelloNonce('n4'), false);

  // Advance clock so n1, n2 expire
  currentTime = 1065;
  const admitAfterPrune = cache.checkHelloAdmission('n4');
  assert.equal(admitAfterPrune.allowed, true);
  assert.equal(cache.recordHelloNonce('n4'), true);
});

test('replay cache: session nonce tracking detects replay within session and isolates across sessions', { timeout: 5000 }, () => {
  const cache = new LocalApiReplayCache();

  const r1 = cache.checkAndRecordSessionNonce('session-a', 'nonce-1');
  assert.equal(r1.allowed, true);

  const r2 = cache.checkAndRecordSessionNonce('session-a', 'nonce-1');
  assert.equal(r2.allowed, false);
  assert.equal(r2.reason, 'REPLAY_DETECTED');

  // Same nonce in different session is allowed
  const r3 = cache.checkAndRecordSessionNonce('session-b', 'nonce-1');
  assert.equal(r3.allowed, true);

  // Clear session-a
  cache.clearSession('session-a');
  const r4 = cache.checkAndRecordSessionNonce('session-a', 'nonce-1');
  assert.equal(r4.allowed, true);
});
