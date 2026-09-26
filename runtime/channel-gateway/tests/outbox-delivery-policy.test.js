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
  isValidLineRetryIdentity,
  LINE_RETRY_KEY_UUID_REGEX,
} = require('../core/outbox-delivery-policy');

test('R2-L: ACCEPTED_BY_PLATFORM never exposed as DELIVERED', () => {
  // Canonical policy statuses strictly define ACCEPTED_BY_PLATFORM, never DELIVERED
  assert.strictEqual(OUTBOX_STATUS.ACCEPTED_BY_PLATFORM, 'ACCEPTED_BY_PLATFORM');
  assert.strictEqual('DELIVERED' in OUTBOX_STATUS, false);
  assert.strictEqual('SENT' in OUTBOX_STATUS, false);
  assert.strictEqual('SUCCESS' in OUTBOX_STATUS, false);

  const command = { platform: 'telegram', endpoint_operation: 'sendMessage' };
  const result = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 200,
    success: true,
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

  // LINE push in-flight restart with valid unexpired retry key (canonical UUID)
  const now = 1700000000;
  const linePushCommandValid = {
    status: OUTBOX_STATUS.IN_FLIGHT,
    platform: 'line',
    endpoint_operation: 'push',
    recipient: 'U123',
    external_retry_key: '550e8400-e29b-41d4-a716-446655440000',
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
    external_retry_key: '550e8400-e29b-41d4-a716-446655440000',
    external_retry_expires_at: now - 10,
  };
  const linePushRecoveryExpired = evaluateStartupRecovery(linePushCommandExpired, { nowSec: now });
  assert.strictEqual(linePushRecoveryExpired.action, 'MARK_UNCERTAIN');
  assert.strictEqual(linePushRecoveryExpired.target_status, OUTBOX_STATUS.UNCERTAIN);
});

test('F1 negative controls: LINE retry credential validation fails closed', () => {
  const now = 1700000000;
  const validUUID = '550e8400-e29b-41d4-a716-446655440000';
  const malformedUUID = 'not-a-valid-uuid-format';

  // 1. Pure validation function controls
  assert.strictEqual(isValidLineRetryIdentity(validUUID, now + 3600, now), true);
  assert.strictEqual(isValidLineRetryIdentity(validUUID, null, now), false);
  assert.strictEqual(isValidLineRetryIdentity(validUUID, undefined, now), false);
  assert.strictEqual(isValidLineRetryIdentity(malformedUUID, now + 3600, now), false);
  assert.strictEqual(isValidLineRetryIdentity(validUUID, now - 1, now), false);
  assert.strictEqual(isValidLineRetryIdentity(validUUID, now, now), false);
  assert.strictEqual(isValidLineRetryIdentity(null, now + 3600, now), false);
  assert.strictEqual(isValidLineRetryIdentity(undefined, now + 3600, now), false);
  assert.strictEqual(isValidLineRetryIdentity('', now + 3600, now), false);
  assert.strictEqual(isValidLineRetryIdentity(validUUID, '1700003600', now), false);
  assert.strictEqual(isValidLineRetryIdentity(validUUID, 1.5, now), false);

  // 2. evaluateDeliveryAttempt negative controls
  const baseCmd = {
    platform: 'line',
    endpoint_operation: 'push',
    recipient: 'U1234567890abcdef',
  };

  // key + null expiry -> UNCERTAIN
  const resNullExp = evaluateDeliveryAttempt(
    { ...baseCmd, external_retry_key: validUUID, external_retry_expires_at: null },
    { transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT, http_status: 500, nowSec: now }
  );
  assert.strictEqual(resNullExp.decision, POLICY_DECISION.UNCERTAIN);

  // key + undefined expiry -> UNCERTAIN
  const resUndefExp = evaluateDeliveryAttempt(
    { ...baseCmd, external_retry_key: validUUID },
    { transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT, http_status: 500, nowSec: now }
  );
  assert.strictEqual(resUndefExp.decision, POLICY_DECISION.UNCERTAIN);

  // malformed UUID + future expiry -> UNCERTAIN
  const resBadUUID = evaluateDeliveryAttempt(
    { ...baseCmd, external_retry_key: malformedUUID, external_retry_expires_at: now + 3600 },
    { transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT, http_status: 500, nowSec: now }
  );
  assert.strictEqual(resBadUUID.decision, POLICY_DECISION.UNCERTAIN);

  // expired key -> UNCERTAIN
  const resExpired = evaluateDeliveryAttempt(
    { ...baseCmd, external_retry_key: validUUID, external_retry_expires_at: now - 1 },
    { transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT, http_status: 500, nowSec: now }
  );
  assert.strictEqual(resExpired.decision, POLICY_DECISION.UNCERTAIN);

  // 3. evaluateStartupRecovery negative controls
  const recNullExp = evaluateStartupRecovery(
    { status: OUTBOX_STATUS.IN_FLIGHT, ...baseCmd, external_retry_key: validUUID, external_retry_expires_at: null },
    { nowSec: now }
  );
  assert.strictEqual(recNullExp.target_status, OUTBOX_STATUS.UNCERTAIN);

  const recUndefExp = evaluateStartupRecovery(
    { status: OUTBOX_STATUS.IN_FLIGHT, ...baseCmd, external_retry_key: validUUID },
    { nowSec: now }
  );
  assert.strictEqual(recUndefExp.target_status, OUTBOX_STATUS.UNCERTAIN);

  const recBadUUID = evaluateStartupRecovery(
    { status: OUTBOX_STATUS.IN_FLIGHT, ...baseCmd, external_retry_key: malformedUUID, external_retry_expires_at: now + 3600 },
    { nowSec: now }
  );
  assert.strictEqual(recBadUUID.target_status, OUTBOX_STATUS.UNCERTAIN);
});

test('F2 negative controls: missing, null, or invalid transport phase must never mean NOT_SENT', () => {
  const command = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
  };

  // missing transport_phase without http_status -> UNCERTAIN (fail-closed, never NOT_SENT)
  const resMissing = evaluateDeliveryAttempt(command, {});
  assert.strictEqual(resMissing.decision, POLICY_DECISION.UNCERTAIN);
  assert.strictEqual(resMissing.reason, 'TELEGRAM_MAY_HAVE_BEEN_SENT_UNCERTAIN');

  // null transport_phase without http_status -> UNCERTAIN
  const resNull = evaluateDeliveryAttempt(command, {
    transport_phase: null,
  });
  assert.strictEqual(resNull.decision, POLICY_DECISION.UNCERTAIN);
  assert.strictEqual(resNull.reason, 'TELEGRAM_MAY_HAVE_BEEN_SENT_UNCERTAIN');

  // invalid transport_phase string without http_status -> UNCERTAIN
  const resInvalid = evaluateDeliveryAttempt(command, {
    transport_phase: 'INVALID_PHASE_STRING',
  });
  assert.strictEqual(resInvalid.decision, POLICY_DECISION.UNCERTAIN);
  assert.strictEqual(resInvalid.reason, 'TELEGRAM_MAY_HAVE_BEEN_SENT_UNCERTAIN');

  // explicit TRANSPORT_PHASE.NOT_SENT + network error -> RETRY
  const resExplicitNotSent = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
    error_code: 'ENOTFOUND',
  });
  assert.strictEqual(resExplicitNotSent.decision, POLICY_DECISION.RETRY);

  // explicit TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT without status -> UNCERTAIN
  const resMayHaveSent = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
  });
  assert.strictEqual(resMayHaveSent.decision, POLICY_DECISION.UNCERTAIN);

  // HTTP 500 on Telegram is always UNCERTAIN regardless of phase
  const res500 = evaluateDeliveryAttempt(command, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 500,
  });
  assert.strictEqual(res500.decision, POLICY_DECISION.UNCERTAIN);
  assert.strictEqual(res500.reason, 'TELEGRAM_5XX_UNCERTAIN');
});

test('D-R3-A+ retry_after exact table domain validation', () => {
  const baseCmd = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
    created_at: 1700000000,
  };
  const now = 1700000000;

  // Valid values: 1 and 2147483647 (with sufficient delivery window)
  const res1 = evaluateDeliveryAttempt(baseCmd, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 429,
    retry_after: 1,
    nowSec: now,
  });
  assert.strictEqual(res1.decision, POLICY_DECISION.RETRY);
  assert.strictEqual(res1.next_attempt_delay_sec, 1);

  // 2147483647 is syntactically valid integer safe integer, but exceeds 24h delivery window (86400s)
  // so it fails terminal with TELEGRAM_DELIVERY_WINDOW_EXCEEDED
  const resMaxInt = evaluateDeliveryAttempt(baseCmd, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 429,
    retry_after: 2147483647,
    nowSec: now,
  });
  assert.strictEqual(resMaxInt.decision, POLICY_DECISION.FAILED_TERMINAL);
  assert.strictEqual(resMaxInt.terminal_reason_code, 'TELEGRAM_DELIVERY_WINDOW_EXCEEDED');

  // Invalid values -> TELEGRAM_RETRY_AFTER_INVALID
  const invalidValues = [
    0,
    -1,
    -100,
    1.5,
    3.14,
    NaN,
    Infinity,
    -Infinity,
    '30',
    null,
    undefined,
    {},
    [],
    2147483648, // > 2147483647
    9007199254740992,
  ];

  for (const inv of invalidValues) {
    const res = evaluateDeliveryAttempt(baseCmd, {
      transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
      http_status: 429,
      retry_after: inv,
      nowSec: now,
    });
    assert.strictEqual(
      res.decision,
      POLICY_DECISION.FAILED_TERMINAL,
      `Expected FAILED_TERMINAL for retry_after: ${inv}`
    );
    assert.strictEqual(
      res.terminal_reason_code,
      'TELEGRAM_RETRY_AFTER_INVALID',
      `Expected TELEGRAM_RETRY_AFTER_INVALID for retry_after: ${inv}`
    );
  }
});

test('D-R3-C1 24h QUEUED delivery window enforcement (86400 seconds)', () => {
  const createdAt = 1700000000;
  const deadline = createdAt + 86400;
  const baseCmd = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
    created_at: createdAt,
  };

  // 1. Initial / NOT_SENT attempt: now < deadline -> RETRY
  const resBefore = evaluateDeliveryAttempt(baseCmd, {
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
    error_code: 'ENOTFOUND',
    nowSec: deadline - 10,
  });
  assert.strictEqual(resBefore.decision, POLICY_DECISION.RETRY);

  // 2. now == deadline -> eligible for retry if delay allows
  // default NOT_SENT delay is 5s: deadline - 5 + 5 = deadline <= deadline -> RETRY
  const resAtDeadline = evaluateDeliveryAttempt(baseCmd, {
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
    error_code: 'ENOTFOUND',
    nowSec: deadline - 5,
  });
  assert.strictEqual(resAtDeadline.decision, POLICY_DECISION.RETRY);

  // 3. now > deadline -> FAILED_TERMINAL (TELEGRAM_DELIVERY_WINDOW_EXCEEDED)
  const resExpired = evaluateDeliveryAttempt(baseCmd, {
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
    error_code: 'ENOTFOUND',
    nowSec: deadline + 1,
  });
  assert.strictEqual(resExpired.decision, POLICY_DECISION.FAILED_TERMINAL);
  assert.strictEqual(resExpired.terminal_reason_code, 'TELEGRAM_DELIVERY_WINDOW_EXCEEDED');

  // 4. Retry schedule exceeds deadline: nowSec + retry_after > deadline -> FAILED_TERMINAL
  const resRetryExceeds = evaluateDeliveryAttempt(baseCmd, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 429,
    retry_after: 60,
    nowSec: deadline - 30, // 30s before deadline, but needs 60s delay
  });
  assert.strictEqual(resRetryExceeds.decision, POLICY_DECISION.FAILED_TERMINAL);
  assert.strictEqual(resRetryExceeds.terminal_reason_code, 'TELEGRAM_DELIVERY_WINDOW_EXCEEDED');

  // 5. Retry schedule exactly at deadline: nowSec + retry_after === deadline -> RETRY allowed
  const resRetryExact = evaluateDeliveryAttempt(baseCmd, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 429,
    retry_after: 30,
    nowSec: deadline - 30,
  });
  assert.strictEqual(resRetryExact.decision, POLICY_DECISION.RETRY);
  assert.strictEqual(resRetryExact.next_attempt_delay_sec, 30);
});

test('Special pre-request and token failure terminal classifications', () => {
  const command = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
  };

  // 1. ACCOUNT_MISMATCH_PRE_REQUEST -> OUTBOUND_ACCOUNT_SWITCH_DISCARDED
  const resMismatch = evaluateDeliveryAttempt(command, {
    error_code: 'ACCOUNT_MISMATCH_PRE_REQUEST',
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
  });
  assert.strictEqual(resMismatch.decision, POLICY_DECISION.FAILED_TERMINAL);
  assert.strictEqual(resMismatch.terminal_reason_code, 'OUTBOUND_ACCOUNT_SWITCH_DISCARDED');

  // 2. TELEGRAM_REPLY_TARGET_INVALID -> TELEGRAM_REPLY_TARGET_INVALID
  const resReplyTarget = evaluateDeliveryAttempt(command, {
    error_code: 'TELEGRAM_REPLY_TARGET_INVALID',
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
  });
  assert.strictEqual(resReplyTarget.decision, POLICY_DECISION.FAILED_TERMINAL);
  assert.strictEqual(resReplyTarget.terminal_reason_code, 'TELEGRAM_REPLY_TARGET_INVALID');

  // 3. TELEGRAM_SECRET_UNAVAILABLE -> TELEGRAM_SECRET_UNAVAILABLE
  const resSecret = evaluateDeliveryAttempt(command, {
    error_code: 'TELEGRAM_SECRET_UNAVAILABLE',
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
  });
  assert.strictEqual(resSecret.decision, POLICY_DECISION.FAILED_TERMINAL);
  assert.strictEqual(resSecret.terminal_reason_code, 'TELEGRAM_SECRET_UNAVAILABLE');

  // 4. INVALID_TELEGRAM_TOKEN_SYNTAX -> INVALID_TELEGRAM_TOKEN_SYNTAX
  const resSyntax = evaluateDeliveryAttempt(command, {
    error_code: 'INVALID_TELEGRAM_TOKEN_SYNTAX',
    transport_phase: TRANSPORT_PHASE.NOT_SENT,
  });
  assert.strictEqual(resSyntax.decision, POLICY_DECISION.FAILED_TERMINAL);
  assert.strictEqual(resSyntax.terminal_reason_code, 'INVALID_TELEGRAM_TOKEN_SYNTAX');
});

test('Telegram 5xx vs LINE push 5xx regression isolation', () => {
  const tgCmd = {
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    recipient: '12345678',
  };
  const lineCmd = {
    platform: 'line',
    endpoint_operation: 'push',
    recipient: 'U1234567890abcdef',
    external_retry_key: '550e8400-e29b-41d4-a716-446655440000',
    external_retry_expires_at: 1700000000 + 3600,
  };

  // Telegram 500 -> UNCERTAIN (never retry)
  const tgRes = evaluateDeliveryAttempt(tgCmd, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 500,
  });
  assert.strictEqual(tgRes.decision, POLICY_DECISION.UNCERTAIN);
  assert.strictEqual(tgRes.reason, 'TELEGRAM_5XX_UNCERTAIN');

  // LINE push 500 with valid retry key -> RETRY
  const lineRes = evaluateDeliveryAttempt(lineCmd, {
    transport_phase: TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT,
    http_status: 500,
    nowSec: 1700000000,
  });
  assert.strictEqual(lineRes.decision, POLICY_DECISION.RETRY);
  assert.strictEqual(lineRes.reason, 'LINE_PUSH_RETRY_WITH_SAME_KEY');
});

