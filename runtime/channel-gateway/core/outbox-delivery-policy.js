/**
 * runtime/channel-gateway/core/outbox-delivery-policy.js
 *
 * ADR-0025 R2: Pure Core Capability-Aware Safe Retry Decision Engine.
 *
 * Invariants:
 * - Transport-neutral, deterministic, pure mathematical function.
 * - Side-effect free: NO fetch, NO credentials, NO timers, NO DB write.
 * - Transport phase: NOT_SENT vs. MAY_HAVE_BEEN_SENT.
 * - Platform / endpoint capability modeling:
 *     Telegram sendMessage:
 *       - No client idempotency key.
 *       - NOT_SENT failure -> RETRY.
 *       - MAY_HAVE_BEEN_SENT unknown / timeout -> UNCERTAIN (NO blind resend).
 *       - Valid flood-control retry_after -> RETRY with delayed scheduling.
 *       - 2xx -> ACCEPTED_BY_PLATFORM (NEVER DELIVERED).
 *       - Non-retryable 4xx -> FAILED_TERMINAL.
 *     LINE push:
 *       - Persisted retry key (X-Line-Retry-Key) supports safe retry with same key + same payload.
 *       - 2xx -> ACCEPTED_BY_PLATFORM.
 *       - 409 same key -> ACCEPTED_BY_PLATFORM.
 *       - 5xx / timeout while key valid -> RETRY with same key/payload.
 *       - Expired retry key with uncertain outcome -> UNCERTAIN.
 *       - Non-retryable 4xx (except 409) -> FAILED_TERMINAL.
 *     LINE reply:
 *       - X-Line-Retry-Key forbidden (must not be used).
 *       - MAY_HAVE_BEEN_SENT unknown -> UNCERTAIN (NO blind retry).
 *       - NOT_SENT failure -> RETRY.
 *       - 2xx -> ACCEPTED_BY_PLATFORM.
 * - Startup crash recovery:
 *     - IN_FLIGHT -> QUEUED ONLY IF valid official idempotency identity was persisted before send.
 *     - Telegram / LINE reply / non-idempotent IN_FLIGHT -> UNCERTAIN.
 *     - Never unconditional reset IN_FLIGHT -> QUEUED.
 * - ACCEPTED_BY_PLATFORM != DELIVERED_TO_RECIPIENT (never exposed as DELIVERED).
 */

'use strict';

const crypto = require('node:crypto');

const TRANSPORT_PHASE = Object.freeze({
  NOT_SENT: 'NOT_SENT',
  MAY_HAVE_BEEN_SENT: 'MAY_HAVE_BEEN_SENT',
});

const OUTBOX_STATUS = Object.freeze({
  QUEUED: 'QUEUED',
  IN_FLIGHT: 'IN_FLIGHT',
  ACCEPTED_BY_PLATFORM: 'ACCEPTED_BY_PLATFORM',
  UNCERTAIN: 'UNCERTAIN',
  FAILED_TERMINAL: 'FAILED_TERMINAL',
});

const POLICY_DECISION = Object.freeze({
  ACCEPTED_BY_PLATFORM: 'ACCEPTED_BY_PLATFORM',
  RETRY: 'RETRY',
  UNCERTAIN: 'UNCERTAIN',
  FAILED_TERMINAL: 'FAILED_TERMINAL',
});

const LINE_RETRYABLE_PUSH_OPERATIONS = new Set([
  'push',
  'multicast',
  'narrowcast',
  'broadcast',
]);

const LINE_RETRY_KEY_UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Validates official LINE retry identity credential.
 * Fail-closed (F1):
 * 1. key must be a valid 128-bit UUID textual form (8-4-4-4-12 hex groups).
 * 2. expiresAt must be explicitly present, a safe integer, and strictly in the future (> nowSec).
 * null, undefined, non-integer, expired, or malformed -> INVALID (false).
 *
 * @param {string|null|undefined} key
 * @param {number|null|undefined} expiresAt
 * @param {number} [nowSec]
 * @returns {boolean}
 */
function isValidLineRetryIdentity(key, expiresAt, nowSec = Math.floor(Date.now() / 1000)) {
  if (typeof key !== 'string' || !LINE_RETRY_KEY_UUID_REGEX.test(key.trim())) {
    return false;
  }
  if (typeof expiresAt !== 'number' || !Number.isSafeInteger(expiresAt)) {
    return false;
  }
  if (expiresAt <= nowSec) {
    return false;
  }
  return true;
}

/**
 * Computes deterministic SHA-256 canonical payload hash.
 * Includes all delivery-relevant stable fields; excludes transient / authorization fields.
 *
 * @param {object} params
 * @param {string} [params.protocol_version='v1']
 * @param {string} params.platform
 * @param {string} params.account_id
 * @param {string} params.endpoint_operation
 * @param {string} params.recipient
 * @param {string|null} [params.logical_reply_target=null]
 * @param {string} params.message_type
 * @param {string} params.body
 * @returns {string} 64 lowercase hex characters
 */
function computeCanonicalPayloadHash(params) {
  if (!params || typeof params !== 'object') {
    throw new TypeError('Payload hash params must be an object');
  }
  const lrt =
    params.logical_reply_target !== null && params.logical_reply_target !== undefined
      ? String(params.logical_reply_target)
      : params.logicalReplyTarget !== null && params.logicalReplyTarget !== undefined
      ? String(params.logicalReplyTarget)
      : null;

  const norm = {
    account_id: String(params.account_id ?? params.accountId ?? ''),
    body: String(params.body ?? params.text ?? ''),
    endpoint_operation: String(params.endpoint_operation ?? params.endpointOperation ?? ''),
    logical_reply_target: lrt,
    message_type: String(params.message_type ?? params.messageType ?? ''),
    platform: String(params.platform || ''),
    protocol_version: 'v1',
    recipient: String(params.recipient || ''),
  };

  const deterministicJson = JSON.stringify(norm, Object.keys(norm).sort());
  return crypto.createHash('sha256').update(deterministicJson, 'utf8').digest('hex').toLowerCase();
}

const TELEGRAM_DELIVERY_WINDOW_SEC = 86400;

/**
 * Checks if proposed retry time falls within the 24-hour delivery window.
 *
 * @param {object} command
 * @param {number} delaySec
 * @param {number} nowSec
 * @returns {object|null} FAILED_TERMINAL decision if expired, null if within window
 */
function checkTelegramDeliveryWindow(command, delaySec, nowSec) {
  const createdAt = typeof command.created_at === 'number' ? command.created_at : nowSec;
  const deadline = createdAt + TELEGRAM_DELIVERY_WINDOW_SEC;
  if (nowSec + delaySec > deadline) {
    return {
      decision: POLICY_DECISION.FAILED_TERMINAL,
      terminal_reason_code: 'TELEGRAM_DELIVERY_WINDOW_EXCEEDED',
      reason: 'TELEGRAM_DELIVERY_WINDOW_EXCEEDED',
    };
  }
  return null;
}

/**
 * Pure policy evaluation for a delivery attempt outcome.
 *
 * @param {object} command The outbox command record
 * @param {object} attemptContext
 * @param {string} attemptContext.transport_phase 'NOT_SENT' | 'MAY_HAVE_BEEN_SENT'
 * @param {boolean} [attemptContext.success]
 * @param {number} [attemptContext.http_status]
 * @param {number} [attemptContext.retry_after]
 * @param {string} [attemptContext.error_code]
 * @param {number} [attemptContext.nowSec] Current timestamp in seconds
 * @returns {{
 *   decision: 'ACCEPTED_BY_PLATFORM' | 'RETRY' | 'UNCERTAIN' | 'FAILED_TERMINAL',
 *   next_attempt_delay_sec?: number,
 *   reason?: string,
 *   terminal_reason_code?: string
 * }}
 */
function evaluateDeliveryAttempt(command, attemptContext) {
  if (!command || typeof command !== 'object') {
    throw new TypeError('command must be an object');
  }
  if (!attemptContext || typeof attemptContext !== 'object') {
    throw new TypeError('attemptContext must be an object');
  }

  const { platform, endpoint_operation } = command;
  const {
    transport_phase,
    success,
    http_status,
    retry_after,
    error_code,
    nowSec = Math.floor(Date.now() / 1000),
  } = attemptContext;

  // 1. Telegram evaluation
  if (platform === 'telegram') {
    // 1a. Pre-request account mismatch -> FAILED_TERMINAL (OUTBOUND_ACCOUNT_SWITCH_DISCARDED)
    if (error_code === 'ACCOUNT_MISMATCH_PRE_REQUEST') {
      return {
        decision: POLICY_DECISION.FAILED_TERMINAL,
        terminal_reason_code: 'OUTBOUND_ACCOUNT_SWITCH_DISCARDED',
        reason: 'OUTBOUND_ACCOUNT_SWITCH_DISCARDED',
      };
    }

    // 1b. Pre-request reply target invalid -> FAILED_TERMINAL (TELEGRAM_REPLY_TARGET_INVALID)
    if (error_code === 'TELEGRAM_REPLY_TARGET_INVALID') {
      return {
        decision: POLICY_DECISION.FAILED_TERMINAL,
        terminal_reason_code: 'TELEGRAM_REPLY_TARGET_INVALID',
        reason: 'TELEGRAM_REPLY_TARGET_INVALID',
      };
    }

    // 1c. Pre-request secret unavailable -> FAILED_TERMINAL (TELEGRAM_SECRET_UNAVAILABLE)
    if (error_code === 'TELEGRAM_SECRET_UNAVAILABLE') {
      return {
        decision: POLICY_DECISION.FAILED_TERMINAL,
        terminal_reason_code: 'TELEGRAM_SECRET_UNAVAILABLE',
        reason: 'TELEGRAM_SECRET_UNAVAILABLE',
      };
    }

    // 1d. Pre-request invalid token syntax -> FAILED_TERMINAL (INVALID_TELEGRAM_TOKEN_SYNTAX)
    if (error_code === 'INVALID_TELEGRAM_TOKEN_SYNTAX') {
      return {
        decision: POLICY_DECISION.FAILED_TERMINAL,
        terminal_reason_code: 'INVALID_TELEGRAM_TOKEN_SYNTAX',
        reason: 'INVALID_TELEGRAM_TOKEN_SYNTAX',
      };
    }

    // 1e. Structured 2xx success
    if (success === true) {
      return {
        decision: POLICY_DECISION.ACCEPTED_BY_PLATFORM,
        reason: 'PLATFORM_2XX_ACCEPTED',
      };
    }
    // Ambiguous/malformed 2xx (status in 200..299 but success !== true)
    if (typeof http_status === 'number' && http_status >= 200 && http_status < 300) {
      return {
        decision: POLICY_DECISION.UNCERTAIN,
        reason: 'TELEGRAM_MAY_HAVE_BEEN_SENT_UNCERTAIN',
      };
    }

    // 1f. HTTP 429 Flood Control with retry_after (D-R3-A+ / §9)
    if (http_status === 429) {
      const isValidRetryAfter =
        typeof retry_after === 'number' &&
        Number.isSafeInteger(retry_after) &&
        retry_after >= 1 &&
        retry_after <= 2147483647;

      if (!isValidRetryAfter) {
        return {
          decision: POLICY_DECISION.FAILED_TERMINAL,
          terminal_reason_code: 'TELEGRAM_RETRY_AFTER_INVALID',
          reason: 'TELEGRAM_RETRY_AFTER_INVALID',
        };
      }

      // Check delivery window (D-R3-C1 / §10)
      const windowExceeded = checkTelegramDeliveryWindow(command, retry_after, nowSec);
      if (windowExceeded) {
        return windowExceeded;
      }

      return {
        decision: POLICY_DECISION.RETRY,
        next_attempt_delay_sec: retry_after,
        reason: 'TELEGRAM_FLOOD_CONTROL_RETRY_AFTER',
      };
    }

    // 1g. Non-retryable 4xx client errors (400, 401, 403, 404, etc.)
    if (typeof http_status === 'number' && http_status >= 400 && http_status < 500) {
      return {
        decision: POLICY_DECISION.FAILED_TERMINAL,
        terminal_reason_code: `TELEGRAM_CLIENT_ERROR_${http_status}`,
        reason: `TELEGRAM_CLIENT_ERROR_${http_status}`,
      };
    }

    // 1h. Server error 5xx -> UNCERTAIN (Telegram-only rule, §12)
    if (typeof http_status === 'number' && http_status >= 500 && http_status < 600) {
      return {
        decision: POLICY_DECISION.UNCERTAIN,
        reason: 'TELEGRAM_5XX_UNCERTAIN',
      };
    }

    // 1i. Explicit NOT_SENT -> retry only within delivery window
    if (transport_phase === TRANSPORT_PHASE.NOT_SENT) {
      const delaySec = 5;
      const windowExceeded = checkTelegramDeliveryWindow(command, delaySec, nowSec);
      if (windowExceeded) {
        return windowExceeded;
      }
      return {
        decision: POLICY_DECISION.RETRY,
        next_attempt_delay_sec: delaySec,
        reason: 'TELEGRAM_NOT_SENT_RETRY',
      };
    }

    // 1j. MAY_HAVE_BEEN_SENT or unknown -> UNCERTAIN (Telegram has no idempotency key; NO BLIND RESEND)
    return {
      decision: POLICY_DECISION.UNCERTAIN,
      reason: 'TELEGRAM_MAY_HAVE_BEEN_SENT_UNCERTAIN',
    };
  }

  // 2. Success response for non-Telegram platforms
  if (success === true || (typeof http_status === 'number' && http_status >= 200 && http_status < 300)) {
    return {
      decision: POLICY_DECISION.ACCEPTED_BY_PLATFORM,
      reason: 'PLATFORM_2XX_ACCEPTED',
    };
  }

  // 3. LINE evaluation
  if (platform === 'line') {
    const isPushOp = LINE_RETRYABLE_PUSH_OPERATIONS.has(endpoint_operation);

    if (isPushOp) {
      // 3a. LINE Push with X-Line-Retry-Key
      // HTTP 409: Same retry key already accepted in prior request -> success
      if (http_status === 409) {
        return {
          decision: POLICY_DECISION.ACCEPTED_BY_PLATFORM,
          reason: 'LINE_SAME_KEY_409_ACCEPTED',
        };
      }

      // Check if retry key is valid and unexpired (fail-closed per F1)
      const hasValidKey = isValidLineRetryIdentity(
        command.external_retry_key,
        command.external_retry_expires_at,
        nowSec
      );

      // Non-retryable 4xx client errors (e.g. 400, 401, 403)
      if (typeof http_status === 'number' && http_status >= 400 && http_status < 500) {
        return {
          decision: POLICY_DECISION.FAILED_TERMINAL,
          terminal_reason_code: `LINE_CLIENT_ERROR_${http_status}`,
          reason: `LINE_CLIENT_ERROR_${http_status}`,
        };
      }

      // Server error 5xx or timeout
      if (
        (typeof http_status === 'number' && http_status >= 500) ||
        transport_phase === TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT ||
        transport_phase === TRANSPORT_PHASE.NOT_SENT
      ) {
        if (hasValidKey) {
          return {
            decision: POLICY_DECISION.RETRY,
            next_attempt_delay_sec: 5,
            reason: 'LINE_PUSH_RETRY_WITH_SAME_KEY',
          };
        }
        // Retry key expired and outcome uncertain
        return {
          decision: POLICY_DECISION.UNCERTAIN,
          reason: 'LINE_PUSH_RETRY_KEY_EXPIRED_UNCERTAIN',
        };
      }
    } else {
      // 3b. LINE Reply endpoint: X-Line-Retry-Key is FORBIDDEN
      if (command.external_retry_key) {
        return {
          decision: POLICY_DECISION.FAILED_TERMINAL,
          terminal_reason_code: 'LINE_REPLY_RETRY_KEY_FORBIDDEN',
          reason: 'LINE_REPLY_RETRY_KEY_FORBIDDEN',
        };
      }

      // Non-retryable 4xx
      if (typeof http_status === 'number' && http_status >= 400 && http_status < 500) {
        return {
          decision: POLICY_DECISION.FAILED_TERMINAL,
          terminal_reason_code: `LINE_CLIENT_ERROR_${http_status}`,
          reason: `LINE_CLIENT_ERROR_${http_status}`,
        };
      }

      if (transport_phase === TRANSPORT_PHASE.NOT_SENT) {
        return {
          decision: POLICY_DECISION.RETRY,
          next_attempt_delay_sec: 5,
          reason: 'LINE_REPLY_NOT_SENT_RETRY',
        };
      }

      // MAY_HAVE_BEEN_SENT -> UNCERTAIN (Reply has no idempotency support)
      return {
        decision: POLICY_DECISION.UNCERTAIN,
        reason: 'LINE_REPLY_MAY_HAVE_BEEN_SENT_UNCERTAIN',
      };
    }
  }

  // 4. Generic non-retryable 4xx
  if (typeof http_status === 'number' && http_status >= 400 && http_status < 500) {
    return {
      decision: POLICY_DECISION.FAILED_TERMINAL,
      terminal_reason_code: `CLIENT_ERROR_${http_status}`,
      reason: `CLIENT_ERROR_${http_status}`,
    };
  }

  // Fallback: If not sent, can retry; otherwise UNCERTAIN
  if (transport_phase === TRANSPORT_PHASE.NOT_SENT) {
    return {
      decision: POLICY_DECISION.RETRY,
      next_attempt_delay_sec: 5,
      reason: 'GENERIC_NOT_SENT_RETRY',
    };
  }

  return {
    decision: POLICY_DECISION.UNCERTAIN,
    reason: 'GENERIC_MAY_HAVE_BEEN_SENT_UNCERTAIN',
  };
}

/**
 * Pure evaluation of crash recovery for an IN_FLIGHT command on startup.
 *
 * @param {object} command
 * @param {object} [options={}]
 * @param {number} [options.nowSec]
 * @returns {{ action: 'REQUEUE' | 'MARK_UNCERTAIN', target_status: 'QUEUED' | 'UNCERTAIN', reason: string }}
 */
function evaluateStartupRecovery(command, options = {}) {
  if (!command || typeof command !== 'object') {
    throw new TypeError('command must be an object');
  }
  const nowSec = options.nowSec !== undefined ? options.nowSec : Math.floor(Date.now() / 1000);

  if (command.status !== OUTBOX_STATUS.IN_FLIGHT) {
    throw new Error(`Cannot perform crash recovery on command with status '${command.status}'`);
  }

  // LINE push with persisted valid retry key (fail-closed per F1)
  if (
    command.platform === 'line' &&
    LINE_RETRYABLE_PUSH_OPERATIONS.has(command.endpoint_operation) &&
    isValidLineRetryIdentity(
      command.external_retry_key,
      command.external_retry_expires_at,
      nowSec
    )
  ) {
    return {
      action: 'REQUEUE',
      target_status: OUTBOX_STATUS.QUEUED,
      reason: 'LINE_PUSH_VALID_PERSISTED_RETRY_KEY',
    };
  }

  // Telegram, LINE reply, or any endpoint without safe official client idempotency
  return {
    action: 'MARK_UNCERTAIN',
    target_status: OUTBOX_STATUS.UNCERTAIN,
    reason: 'IN_FLIGHT_RESTART_WITHOUT_SAFE_IDEMPOTENCY',
  };
}

module.exports = {
  TRANSPORT_PHASE,
  OUTBOX_STATUS,
  POLICY_DECISION,
  TELEGRAM_DELIVERY_WINDOW_SEC,
  LINE_RETRYABLE_PUSH_OPERATIONS,
  LINE_RETRY_KEY_UUID_REGEX,
  isValidLineRetryIdentity,
  computeCanonicalPayloadHash,
  evaluateDeliveryAttempt,
  evaluateStartupRecovery,
};
