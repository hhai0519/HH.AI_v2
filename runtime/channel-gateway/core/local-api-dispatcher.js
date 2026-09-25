/**
 * runtime/channel-gateway/core/local-api-dispatcher.js
 *
 * TG-MVP-11: Request Schema Validation, Endpoint Dispatcher & Synchronous Poll Critical Section.
 */

'use strict';

const {
  POLL_LIMIT_MIN,
  POLL_LIMIT_MAX,
  REPLY_TEXT_MAX_UTF16,
} = require('./local-api-codec');

const ALLOWED_REPLY_REASONS = new Set([
  'NOT_CURRENT_HOLDER',
  'STALE_FENCING_TOKEN',
  'ACCOUNT_MISMATCH',
  'MESSAGE_NOT_FOUND',
  'MESSAGE_NOT_CLAIMED',
  'CLAIM_MISMATCH',
]);

/**
 * Checks if value is a plain JSON object (not Array, not null).
 */
function isJsonObject(val) {
  return typeof val === 'object' && val !== null && !Array.isArray(val);
}

/**
 * Checks if value is a non-empty string.
 */
function isNonEmptyString(val) {
  return typeof val === 'string' && val.trim().length > 0;
}

/**
 * Checks if value is a non-negative safe integer.
 */
function isNonNegativeSafeInteger(val) {
  return typeof val === 'number' && Number.isSafeInteger(val) && val >= 0;
}

/**
 * Checks if value is an integer within [min, max].
 */
function isBoundedInteger(val, min, max) {
  return typeof val === 'number' && Number.isSafeInteger(val) && val >= min && val <= max;
}

class LocalApiDispatcher {
  /**
   * @param {object} dependencies
   * @param {object} dependencies.repository SqliteStateRepository instance
   * @param {() => number} [dependencies.nowSec] Optional clock for timestamps
   */
  constructor(dependencies) {
    if (!dependencies || !dependencies.repository) {
      throw new Error('LocalApiDispatcher requires a repository dependency');
    }
    this.repository = dependencies.repository;
    this.nowSec = dependencies.nowSec || (() => Math.floor(Date.now() / 1000));
  }

  /**
   * Dispatches an authenticated business request to the appropriate handler.
   *
   * @param {string} path Endpoint path (e.g. '/v1/status')
   * @param {object} body Parsed JSON body
   * @returns {{ status: number, body: object }} Response status and body
   */
  dispatch(path, body) {
    try {
      if (!isJsonObject(body)) {
        return { status: 400, body: { ok: false, code: 'INVALID_REQUEST' } };
      }

      switch (path) {
        case '/v1/status':
          return this._handleStatus(body);
        case '/v1/takeover':
          return this._handleTakeover(body);
        case '/v1/poll':
          return this._handlePoll(body);
        case '/v1/heartbeat':
          return this._handleHeartbeat(body);
        case '/v1/reply':
          return this._handleReply(body);
        default:
          return { status: 400, body: { ok: false, code: 'INVALID_REQUEST' } };
      }
    } catch {
      // Repository validator/business method exceptions that THROW are treated as unexpected internal failures:
      // HTTP 500 INTERNAL_ERROR with zero detail/stack leakage
      return { status: 500, body: { ok: false, code: 'INTERNAL_ERROR' } };
    }
  }

  /**
   * POST /v1/status
   * Body: { "channel_id": string }
   */
  _handleStatus(body) {
    const keys = Object.keys(body);
    if (keys.length !== 1 || !isNonEmptyString(body.channel_id)) {
      return { status: 400, body: { ok: false, code: 'INVALID_REQUEST' } };
    }

    const state = this.repository.getChannelState(body.channel_id);
    if (state === null) {
      return { status: 404, body: { ok: false, code: 'CHANNEL_NOT_FOUND' } };
    }

    return {
      status: 200,
      body: {
        ok: true,
        code: 'OK',
        channel_id: state.channelId,
        current_holder: state.currentHolder,
        fencing_token: state.fencingToken,
        last_heartbeat_at: state.lastHeartbeatAt,
        queued_count: state.backlogCount,
      },
    };
  }

  /**
   * POST /v1/takeover
   * Body: { "channel_id": string, "holder_id": string }
   * Only this endpoint may call takeoverChannel().
   */
  _handleTakeover(body) {
    const keys = Object.keys(body);
    if (
      keys.length !== 2 ||
      !isNonEmptyString(body.channel_id) ||
      !isNonEmptyString(body.holder_id)
    ) {
      return { status: 400, body: { ok: false, code: 'INVALID_REQUEST' } };
    }

    const res = this.repository.takeoverChannel(body.channel_id, body.holder_id, {
      timestamp: this.nowSec(),
    });

    const discardedIds = Array.isArray(res.discardedMessages)
      ? res.discardedMessages.map((m) => m.messageId)
      : [];

    return {
      status: 200,
      body: {
        ok: true,
        code: 'OK',
        fencing_token: res.fencingToken,
        previous_holder: res.previousHolder,
        discarded_message_ids: discardedIds,
      },
    };
  }

  /**
   * POST /v1/poll
   * Body: {
   *   "channel_id": string,
   *   "holder_id": string,
   *   "fencing_token": non-negative safe integer,
   *   "limit": integer (1..50)
   * }
   *
   * Exact Synchronous Poll Critical Section (Section 10):
   * MUST execute in ONE synchronous, non-yielding JavaScript section.
   * NO await between repository calls.
   */
  _handlePoll(body) {
    const keys = Object.keys(body);
    if (
      keys.length !== 4 ||
      !isNonEmptyString(body.channel_id) ||
      !isNonEmptyString(body.holder_id) ||
      !isNonNegativeSafeInteger(body.fencing_token) ||
      !isBoundedInteger(body.limit, POLL_LIMIT_MIN, POLL_LIMIT_MAX)
    ) {
      return { status: 400, body: { ok: false, code: 'INVALID_REQUEST' } };
    }

    const channelId = body.channel_id;
    const holderId = body.holder_id;
    const fencingToken = body.fencing_token;
    const requestLimit = body.limit;

    // Synchronous critical section
    const existing = this.repository.getClaimedMessages(channelId, holderId, fencingToken);
    const n = existing.length;
    const remainingCapacity = 50 - n;
    const claimLimit = Math.min(requestLimit, remainingCapacity);

    if (claimLimit > 0) {
      const claimResult = this.repository.claimMessages(channelId, holderId, fencingToken, claimLimit);
      if (!claimResult.success) {
        if (claimResult.reason === 'NOT_CURRENT_HOLDER') {
          return { status: 409, body: { ok: false, code: 'NOT_CURRENT_HOLDER' } };
        }
        if (claimResult.reason === 'STALE_FENCING_TOKEN') {
          return { status: 409, body: { ok: false, code: 'STALE_FENCING_TOKEN' } };
        }
      }
    }

    const finalClaimed = this.repository.getClaimedMessages(channelId, holderId, fencingToken);

    return {
      status: 200,
      body: {
        ok: true,
        code: 'OK',
        messages: finalClaimed.map((m) => ({
          sequence: m.sequence,
          channel_id: m.channel_id,
          message_id: m.message_id,
          account_id: m.account_id,
          status: 'claimed',
          claimed_by: m.claimed_by,
          claimed_at_token: m.claimed_at_token,
          content: m.content,
        })),
      },
    };
  }

  /**
   * POST /v1/heartbeat
   * Body: {
   *   "channel_id": string,
   *   "holder_id": string,
   *   "fencing_token": non-negative safe integer
   * }
   */
  _handleHeartbeat(body) {
    const keys = Object.keys(body);
    if (
      keys.length !== 3 ||
      !isNonEmptyString(body.channel_id) ||
      !isNonEmptyString(body.holder_id) ||
      !isNonNegativeSafeInteger(body.fencing_token)
    ) {
      return { status: 400, body: { ok: false, code: 'INVALID_REQUEST' } };
    }

    const res = this.repository.heartbeatChannel(
      body.channel_id,
      body.holder_id,
      body.fencing_token,
      { timestamp: this.nowSec() }
    );

    if (res.success) {
      return { status: 200, body: { ok: true, code: 'OK' } };
    }

    if (res.reason === 'HOLDER_MISMATCH') {
      return { status: 409, body: { ok: false, code: 'HOLDER_MISMATCH' } };
    }

    if (res.reason === 'STALE_FENCING_TOKEN') {
      return { status: 409, body: { ok: false, code: 'STALE_FENCING_TOKEN' } };
    }

    return { status: 500, body: { ok: false, code: 'INTERNAL_ERROR' } };
  }

  /**
   * POST /v1/reply
   * Body: {
   *   "client_request_id": string,
   *   "channel_id": string,
   *   "holder_id": string,
   *   "fencing_token": non-negative safe integer,
   *   "message_id": string,
   *   "replying_account_id": string,
   *   "text": string
   * }
   */
  _handleReply(body) {
    const keys = Object.keys(body);
    if (
      keys.length !== 7 ||
      !isNonEmptyString(body.client_request_id) ||
      !isNonEmptyString(body.channel_id) ||
      !isNonEmptyString(body.holder_id) ||
      !isNonNegativeSafeInteger(body.fencing_token) ||
      !isNonEmptyString(body.message_id) ||
      !isNonEmptyString(body.replying_account_id) ||
      !isNonEmptyString(body.text) ||
      body.text.length > REPLY_TEXT_MAX_UTF16
    ) {
      return { status: 400, body: { ok: false, code: 'INVALID_REQUEST' } };
    }

    const authResult = this.repository.validateReplyAuthorization(
      body.channel_id,
      body.holder_id,
      body.fencing_token,
      body.message_id,
      body.replying_account_id
    );

    if (authResult.authorized === false) {
      if (ALLOWED_REPLY_REASONS.has(authResult.reason)) {
        return {
          status: 403,
          body: {
            ok: false,
            code: 'REPLY_NOT_AUTHORIZED',
            reason: authResult.reason,
          },
        };
      }
      return { status: 500, body: { ok: false, code: 'INTERNAL_ERROR' } };
    }

    // TG-MVP-11 boundary: authorized reply returns 501 OUTBOUND_NOT_READY
    return {
      status: 501,
      body: {
        ok: false,
        code: 'OUTBOUND_NOT_READY',
      },
    };
  }
}

module.exports = {
  LocalApiDispatcher,
};
