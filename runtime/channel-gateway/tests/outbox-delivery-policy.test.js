/**
 * runtime/channel-gateway/tests/outbox-delivery-policy.test.js
 *
 * ADR-0025 R2 Canaries & Pure Delivery Policy Test Suite.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  TRANSPORT_PHASE,
  OUTBOX_STATUS,
  POLICY_DECISION,
  computeCanonicalPayloadHash,
  evaluateDeliveryAttempt,
  evaluateStartupRecovery,
} = require('../core/outbox-delivery-policy');

test('R2-L: ACCEPTED_BY_PLATFORM never exposed as DELIVERED', () => {
  // Canonical policy statuses strictly define ACCEPTED_BY_PLATFORM, never DELIVERED
  assert.strictEqual(OUTBOX_STATUS.ACCEPTED_BY_PLATFORM, 'ACCEPTED_BY_PLATFORM');
  assert.strictEqual('DELIVERED' in OUTBOX_STATUS, false);
  assert.strictEqual('SENT' in OUTBOX_STATUS, false);
  assert.strictEqual('SUCCESS' in OUTBOX_STATUS, false);

  const command = { platform: 'telegram', endpoint_operation: 'sendMessage' };
  const result = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
    http_status: 200,
  });

  assert.strictEqual(result.decision, POLICY_DECISION.ACCEPTED_BY_PLATFORM);
  assert.notStrictEqual(result.decision, 'DELIVERED');
});

test('Canonical payload hash - deterministic and excludes transient / auth fields', () => {
  const baseParams = {
    platform: 'telegram',
    account_id: 'bot_main',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
    logical_reply_target: 'tg:12345678:999',
    message_type: 'text',
    body: 'Hello world',
  };

  const hash1 = computeCanonicalPayloadHash(baseParams);
  assert.strictEqual(typeof hash1, 'string');
  assert.strictEqual(hash1.length, 64);
  assert.match(hash1, /^[0-9a-f]{64}$/);

  // Same stable params yield identical hash
  const hash2 = computeCanonicalPayloadHash({ ...baseParams });
  assert.strictEqual(hash1, hash2);

  // Transient fields (HMAC, timestamp, nonce, attempt_count, fencing_token) do not affect hash
  const hash3 = computeCanonicalPayloadHash({
    ...baseParams,
    hmac: 'secret-hmac',
    timestamp: 1234567890,
    nonce: 'random-nonce',
    fencing_token: 5,
    attempt_count: 3,
  });
  assert.strictEqual(hash1, hash3);

  // Delivery-relevant changes MUST change the hash
  const hashDiffText = computeCanonicalPayloadHash({
    ...baseParams,
    body: 'Hello world modified',
  });
  assert.notStrictEqual(hash1, hashDiffText);

  const hashDiffRecipient = computeCanonicalPayloadHash({
    ...baseParams,
    recipient: '87654321',
  });
  assert.notStrictEqual(hash1, hashDiffRecipient);
});

test('R2-I: Telegram sendMessage MAY_HAVE_BEEN_SENT unknown -> UNCERTAIN (NO blind resend)', () => {
  const command = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
  };

  const result = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: undefined, // Timeout / connection dropped after socket write
  });

  assert.strictEqual(result.decision, POLICY_DECISION.UNCERTAIN);
  assert.strictEqual(result.reason, 'TELEGRAM_MAY_HAVE_BEEN_SENT_UNCERTAIN');
});

test('R2-J: valid Telegram retry_after -> scheduled controlled retry', () => {
  const command = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
  };

  const result = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 429,
    retry_after: 15,
  });

  assert.strictEqual(result.decision, POLICY_DECISION.RETRY);
  assert.strictEqual(result.next_attempt_delay_sec, 15);
  assert.strictEqual(result.reason, 'TELEGRAM_FLOOD_CONTROL_RETRY_AFTER');

  // Invalid / non-positive retry_after fails closed
  const invalidResult = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 429,
    retry_after: -1,
  });
  assert.strictEqual(invalidResult.decision, POLICY_DECISION.FAILED_TERMINAL);
});

test('Telegram sendMessage: NOT_SENT network error -> safe RETRY', () => {
  const command = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
  };

  const result = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
    error_code: 'ENOTFOUND',
  });

  assert.strictEqual(result.decision, POLICY_DECISION.RETRY);
  assert.strictEqual(result.reason, 'TELEGRAM_NOT_SENT_RETRY');
});

test('Telegram sendMessage: non-retryable 4xx client errors -> FAILED_TERMINAL', () => {
  const command = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
  };

  for (const status of [400, 401, 403, 404]) {
    const res = evaluateDeliveryAttempt(command, {
      transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
      http_status: status,
    });
    assert.strictEqual(res.decision, POLICY_DECISION.FAILED_TERMINAL);
  }
});

test('R2-E: synthetic LINE push retry -> same persisted retry key + same payload', () => {
  const now = 1700000000;
  const command = {
    platform: 'line',
    endpoint_operation: 'push',
    recipient: 'U1234567890abcdef',
    external_retry_key: '550e8400-e29b-41d4-a716-446655440000',
    external_retry_expires_at: now + 86400, // Valid 24h
  };

  // 500 error during send -> retry with same key
  const result500 = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 500,
    nowSec: now,
  });

  assert.strictEqual(result500.decision, POLICY_DECISION.RETRY);
  assert.strictEqual(result500.reason, 'LINE_PUSH_RETRY_WITH_SAME_KEY');

  // Expired retry key (> 24 hours) -> cannot safely retry, becomes UNCERTAIN
  const resultExpired = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 500,
    nowSec: now + 90000,
  });

  assert.strictEqual(resultExpired.decision, POLICY_DECISION.UNCERTAIN);
  assert.strictEqual(resultExpired.reason, 'LINE_PUSH_RETRY_KEY_EXPIRED_UNCERTAIN');
});

test('R2-F: LINE same-key 409 -> ACCEPTED_BY_PLATFORM / no retry', () => {
  const command = {
    platform: 'line',
    endpoint_operation: 'push',
    recipient: 'U1234567890abcdef',
    external_retry_key: '550e8400-e29b-41d4-a716-446655440000',
  };

  const result = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 409,
  });

  assert.strictEqual(result.decision, POLICY_DECISION.ACCEPTED_BY_PLATFORM);
  assert.strictEqual(result.reason, 'LINE_SAME_KEY_409_ACCEPTED');
});

test('R2-G: LINE reply policy -> X-Line-Retry-Key forbidden', () => {
  const commandWithKey = {
    platform: 'line',
    endpoint_operation: 'reply',
    recipient: 'U1234567890abcdef',
    external_retry_key: 'forbidden-key-on-reply',
  };

  // LINE reply endpoint rejects retry keys
  const result = evaluateDeliveryAttempt(commandWithKey, {
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
    http_status: 400,
  });

  assert.strictEqual(result.decision, POLICY_DECISION.FAILED_TERMINAL);
  assert.strictEqual(result.reason, 'LINE_REPLY_RETRY_KEY_FORBIDDEN');
});

test('R2-H: LINE reply MAY_HAVE_BEEN_SENT unknown -> UNCERTAIN', () => {
  const command = {
    platform: 'line',
    endpoint_operation: 'reply',
    recipient: 'U1234567890abcdef',
    external_retry_key: null,
  };

  const result = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: undefined, // Timeout after writing to network
  });

  assert.strictEqual(result.decision, POLICY_DECISION.UNCERTAIN);
  assert.strictEqual(result.reason, 'LINE_REPLY_MAY_HAVE_BEEN_SENT_UNCERTAIN');
});

test('R2-K: restart IN_FLIGHT without safe idempotency -> UNCERTAIN', () => {
  // Telegram in-flight restart
  const tgCommand = {
    status: OUTBOX_STATUS.IN_FLIGHT,
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345',
  };

  const tgRecovery = evaluateStartupRecovery(tgCommand);
  assert.strictEqual(tgRecovery.action, 'MARK_UNCERTAIN');
  assert.strictEqual(tgRecovery.target_status, OUTBOX_STATUS.UNCERTAIN);
  assert.strictEqual(tgRecovery.reason, 'IN_FLIGHT_RESTART_WITHOUT_SAFE_IDEMPOTENCY');

  // LINE reply in-flight restart
  const lineReplyCommand = {
    status: OUTBOX_STATUS.IN_FLIGHT,
    platform: 'line',
    endpoint_operation: 'reply',
    recipient: 'U123',
    external_retry_key: null,
  };
  const lineReplyRecovery = evaluateStartupRecovery(lineReplyCommand);
  assert.strictEqual(lineReplyRecovery.action, 'MARK_UNCERTAIN');
  assert.strictEqual(lineReplyRecovery.target_status, OUTBOX_STATUS.UNCERTAIN);

  // LINE push in-flight restart with valid unexpired retry key
  const now = 1700000000;
  const linePushCommandValid = {
    status: OUTBOX_STATUS.IN_FLIGHT,
    platform: 'line',
    endpoint_operation: 'push',
    recipient: 'U123',
    external_retry_key: 'valid-uuid',
    external_retry_expires_at: now + 3600,
  };
  const linePushRecoveryValid = evaluateStartupRecovery(linePushCommandValid, { nowSec: now });
  assert.strictEqual(linePushRecoveryValid.action, 'REQUEUE');
  assert.strictEqual(linePushRecoveryValid.target_status, OUTBOX_STATUS.QUEUED);

  // LINE push in-flight restart with expired retry key
  const linePushCommandExpired = {
    status: OUTBOX_STATUS.IN_FLIGHT,
    platform: 'line',
    endpoint_operation: 'push',
    recipient: 'U123',
    external_retry_key: 'expired-uuid',
    external_retry_expires_at: now - 10,
  };
  const linePushRecoveryExpired = evaluateStartupRecovery(linePushCommandExpired, { nowSec: now });
  assert.strictEqual(linePushRecoveryExpired.action, 'MARK_UNCERTAIN');
  assert.strictEqual(linePushRecoveryExpired.target_status, OUTBOX_STATUS.UNCERTAIN);
});
