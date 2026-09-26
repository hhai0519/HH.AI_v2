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
 *   reason?: string
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

  // 1. Success response (HTTP 2xx or explicit success)
  if (success === true || (typeof http_status === 'number' && http_status >= 200 && http_status < 300)) {
    return {
      decision: POLICY_DECISION.ACCEPTED_BY_PLATFORM,
      reason: 'PLATFORM_2XX_ACCEPTED',
    };
  }

  // 2. Telegram evaluation
  if (platform === 'telegram') {
    // 2a. HTTP 429 Flood Control with retry_after
    if (http_status === 429) {
      if (
        typeof retry_after === 'number' &&
        Number.isSafeInteger(retry_after) &&
        retry_after > 0
      ) {
        return {
          decision: POLICY_DECISION.RETRY,
          next_attempt_delay_sec: retry_after,
          reason: 'TELEGRAM_FLOOD_CONTROL_RETRY_AFTER',
        };
      }
      // Invalid / non-positive retry_after on 429: fail closed, do NOT blind resend immediately
      return {
        decision: POLICY_DECISION.FAILED_TERMINAL,
        reason: 'TELEGRAM_INVALID_RETRY_AFTER',
      };
    }

    // 2b. Non-retryable 4xx client errors (400, 401, 403, 404, etc.)
    if (typeof http_status === 'number' && http_status >= 400 && http_status < 500) {
      return {
        decision: POLICY_DECISION.FAILED_TERMINAL,
        reason: `TELEGRAM_CLIENT_ERROR_${http_status}`,
      };
    }

    // 2c. Phase analysis
    if (transport_phase === TRANSPORT_PHASE.NOT_SENT) {
      // Safe to retry on NOT_SENT
      return {
        decision: POLICY_DECISION.RETRY,
        next_attempt_delay_sec: 5,
        reason: 'TELEGRAM_NOT_SENT_RETRY',
      };
    }

    // MAY_HAVE_BEEN_SENT or unknown -> UNCERTAIN (Telegram has no idempotency key; NO BLIND RESEND)
    return {
      decision: POLICY_DECISION.UNCERTAIN,
      reason: 'TELEGRAM_MAY_HAVE_BEEN_SENT_UNCERTAIN',
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

      // Check if retry key is expired (LINE retry key valid 24h)
      const hasValidKey =
        Boolean(command.external_retry_key) &&
        (command.external_retry_expires_at === null ||
          command.external_retry_expires_at === undefined ||
          command.external_retry_expires_at > nowSec);

      // Non-retryable 4xx client errors (e.g. 400, 401, 403)
      if (typeof http_status === 'number' && http_status >= 400 && http_status < 500) {
        return {
          decision: POLICY_DECISION.FAILED_TERMINAL,
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
          reason: 'LINE_REPLY_RETRY_KEY_FORBIDDEN',
        };
      }

      // Non-retryable 4xx
      if (typeof http_status === 'number' && http_status >= 400 && http_status < 500) {
        return {
          decision: POLICY_DECISION.FAILED_TERMINAL,
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

  // LINE push with persisted valid retry key
  if (
    command.platform === 'line' &&
    LINE_RETRYABLE_PUSH_OPERATIONS.has(command.endpoint_operation) &&
    Boolean(command.external_retry_key) &&
    (command.external_retry_expires_at === null ||
      command.external_retry_expires_at === undefined ||
      command.external_retry_expires_at > nowSec)
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
  LINE_RETRYABLE_PUSH_OPERATIONS,
  computeCanonicalPayloadHash,
  evaluateDeliveryAttempt,
  evaluateStartupRecovery,
};
