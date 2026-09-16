/**
 * runtime/channel-gateway/core/channel-control.js
 *
 * ADR-0022 D5–D10: Pure in-memory channel control state transition domain model.
 *
 * Invariants:
 * - Channel is the lock / duty unit (Telegram and LINE states are strictly independent).
 * - Only explicit takeover operations can acquire or replace a holder.
 * - Heartbeat, poll, and reply validation NEVER perform implicit takeover.
 * - Each successful takeover increments a monotonic fencing/version token.
 * - Stale holders / stale fencing tokens are rejected from reply authorization.
 * - Regular takeover: claimed messages by old holder are DISCARDED; queued messages PRESERVED.
 * - Heartbeat expiry: claimed messages are DISCARDED; queued messages PRESERVED; holder reset to null.
 * - When there is no holder: incoming messages enter queued domain state; backlog count reflects queued messages.
 * - Zero external dependencies. Zero network / filesystem / timer side effects.
 *
 * NOTE: This is an in-memory pure transition model, NOT a durable persistence provider (D10).
 */

'use strict';

const MESSAGE_STATUS = {
  QUEUED: 'queued',
  CLAIMED: 'claimed',
  DISCARDED: 'discarded',
  REPLIED: 'replied',
};

class ChannelControl {
  /**
   * @param {string} channelId - Channel identity (e.g. 'telegram', 'line')
   */
  constructor(channelId) {
    if (!channelId || typeof channelId !== 'string' || !channelId.trim()) {
      throw new TypeError('channelId must be a non-empty string');
    }
    this.channelId = channelId.trim();
    this.currentHolder = null;
    this.fencingToken = 0;
    this.lastHeartbeatAt = null;
    this.messages = [];
  }

  /**
   * Explicit takeover operation (D6).
   * Only this operation can acquire or replace a holder.
   *
   * @param {string} holderId - Identity of the acquiring agent
   * @param {object} [metadata] - Optional deterministic metadata (e.g. timestamp)
   * @returns {object} Takeover transition result
   */
  takeover(holderId, metadata = {}) {
    if (!holderId || typeof holderId !== 'string' || !holderId.trim()) {
      throw new TypeError('holderId must be a non-empty string');
    }
    const cleanHolderId = holderId.trim();
    const previousHolder = this.currentHolder;

    // Monotonically increment fencing token
    this.fencingToken += 1;
    const currentToken = this.fencingToken;

    // D9: Messages claimed by previous holder but not yet replied -> DISCARD
    const discardedMessages = [];
    for (const msg of this.messages) {
      if (msg.status === MESSAGE_STATUS.CLAIMED) {
        msg.status = MESSAGE_STATUS.DISCARDED;
        msg.discardReason = 'TAKEOVER';
        msg.discardedByHolder = cleanHolderId;
        msg.discardedAtToken = currentToken;
        discardedMessages.push({
          id: msg.id,
          receivingAccountId: msg.receivingAccountId,
          status: msg.status,
          discardReason: msg.discardReason,
        });
      }
      // Messages with status === QUEUED remain QUEUED (preserved for new holder)
    }

    this.currentHolder = cleanHolderId;
    this.lastHeartbeatAt = metadata.timestamp !== undefined ? metadata.timestamp : null;

    return {
      success: true,
      channelId: this.channelId,
      holder: this.currentHolder,
      fencingToken: this.fencingToken,
      previousHolder,
      discardedMessages,
      backlogCount: this.getBacklogCount(),
    };
  }

  /**
   * Heartbeat to keep duty alive (D6).
   * Must NOT perform implicit takeover.
   *
   * @param {string} holderId
   * @param {number} fencingToken
   * @param {object} [metadata]
   * @returns {object} Heartbeat result
   */
  heartbeat(holderId, fencingToken, metadata = {}) {
    if (!this.currentHolder || this.currentHolder !== holderId) {
      return {
        success: false,
        reason: 'HOLDER_MISMATCH',
        currentHolder: this.currentHolder,
      };
    }
    if (fencingToken !== this.fencingToken) {
      return {
        success: false,
        reason: 'STALE_FENCING_TOKEN',
        expectedToken: this.fencingToken,
        receivedToken: fencingToken,
      };
    }

    this.lastHeartbeatAt = metadata.timestamp !== undefined ? metadata.timestamp : null;
    return {
      success: true,
      channelId: this.channelId,
      holder: this.currentHolder,
      fencingToken: this.fencingToken,
    };
  }

  /**
   * Holder heartbeat expiry transition (D9).
   * Claimed messages are discarded; queued messages are preserved; holder is reset.
   *
   * @returns {object} Expiry transition result
   */
  expireHolder() {
    if (!this.currentHolder) {
      return {
        success: false,
        reason: 'NO_ACTIVE_HOLDER',
      };
    }

    const expiredHolder = this.currentHolder;
    const discardedMessages = [];

    for (const msg of this.messages) {
      if (msg.status === MESSAGE_STATUS.CLAIMED) {
        msg.status = MESSAGE_STATUS.DISCARDED;
        msg.discardReason = 'HEARTBEAT_EXPIRY';
        msg.discardedByHolder = expiredHolder;
        msg.discardedAtToken = this.fencingToken;
        discardedMessages.push({
          id: msg.id,
          receivingAccountId: msg.receivingAccountId,
          status: msg.status,
          discardReason: msg.discardReason,
        });
      }
    }

    this.currentHolder = null;
    this.lastHeartbeatAt = null;

    return {
      success: true,
      expiredHolder,
      discardedMessages,
      backlogCount: this.getBacklogCount(),
    };
  }

  /**
   * Enqueue incoming message into channel domain state (D10).
   * Works when there is no holder, or when a holder is active.
   *
   * @param {object} messageData - Must contain id and receivingAccountId
   * @returns {object} Enqueue result
   */
  enqueueMessage(messageData) {
    if (!messageData || typeof messageData !== 'object') {
      throw new TypeError('messageData must be an object');
    }
    const { id, receivingAccountId } = messageData;
    if (!id || (typeof id !== 'string' && typeof id !== 'number')) {
      throw new TypeError('message id must be a non-empty string or number');
    }
    if (!receivingAccountId || typeof receivingAccountId !== 'string' || !receivingAccountId.trim()) {
      throw new TypeError('receivingAccountId must be a non-empty string');
    }

    const messageId = String(id).trim();
    if (this.messages.some((m) => m.id === messageId)) {
      throw new Error(`Message with id '${messageId}' already exists`);
    }

    const message = {
      id: messageId,
      receivingAccountId: receivingAccountId.trim(),
      status: MESSAGE_STATUS.QUEUED,
      claimedBy: null,
      claimedAtToken: null,
      discardReason: null,
      metadata: messageData.metadata || {},
    };

    this.messages.push(message);

    return {
      success: true,
      messageId: message.id,
      status: message.status,
      backlogCount: this.getBacklogCount(),
    };
  }

  /**
   * Count queued messages awaiting claim.
   * @returns {number}
   */
  getBacklogCount() {
    return this.messages.filter((m) => m.status === MESSAGE_STATUS.QUEUED).length;
  }

  /**
   * Poll and claim queued messages (D6).
   * Cannot acquire control when there is no holder.
   *
   * @param {string} holderId
   * @param {number} fencingToken
   * @param {number} [limit]
   * @returns {object} Poll result
   */
  pollMessages(holderId, fencingToken, limit = Infinity) {
    if (!this.currentHolder || this.currentHolder !== holderId) {
      return {
        success: false,
        reason: 'NOT_CURRENT_HOLDER',
        claimedMessages: [],
      };
    }
    if (fencingToken !== this.fencingToken) {
      return {
        success: false,
        reason: 'STALE_FENCING_TOKEN',
        claimedMessages: [],
      };
    }

    const claimed = [];
    for (const msg of this.messages) {
      if (msg.status === MESSAGE_STATUS.QUEUED) {
        msg.status = MESSAGE_STATUS.CLAIMED;
        msg.claimedBy = holderId;
        msg.claimedAtToken = fencingToken;
        claimed.push({
          id: msg.id,
          receivingAccountId: msg.receivingAccountId,
          status: msg.status,
          claimedBy: msg.claimedBy,
          claimedAtToken: msg.claimedAtToken,
        });
        if (claimed.length >= limit) {
          break;
        }
      }
    }

    return {
      success: true,
      claimedMessages: claimed,
      remainingBacklogCount: this.getBacklogCount(),
    };
  }

  /**
   * Validate and authorize a reply (D8, D26).
   * Stale holder / stale fencing token / account mismatch must be rejected.
   *
   * @param {string} holderId
   * @param {number} fencingToken
   * @param {string|number} messageId
   * @param {string} replyingAccountId - Account identity attempting to reply
   * @returns {object} Authorization result
   */
  authorizeReply(holderId, fencingToken, messageId, replyingAccountId) {
    if (!this.currentHolder || this.currentHolder !== holderId) {
      return {
        authorized: false,
        reason: 'NOT_CURRENT_HOLDER',
      };
    }
    if (fencingToken !== this.fencingToken) {
      return {
        authorized: false,
        reason: 'STALE_FENCING_TOKEN',
      };
    }

    const strId = String(messageId).trim();
    const msg = this.messages.find((m) => m.id === strId);
    if (!msg) {
      return {
        authorized: false,
        reason: 'MESSAGE_NOT_FOUND',
      };
    }

    if (msg.status !== MESSAGE_STATUS.CLAIMED) {
      return {
        authorized: false,
        reason: 'MESSAGE_NOT_CLAIMED',
        status: msg.status,
      };
    }

    if (msg.claimedBy !== holderId || msg.claimedAtToken !== fencingToken) {
      return {
        authorized: false,
        reason: 'CLAIM_MISMATCH',
      };
    }

    if (!replyingAccountId || typeof replyingAccountId !== 'string' || !replyingAccountId.trim()) {
      return {
        authorized: false,
        reason: 'ACCOUNT_MISMATCH',
      };
    }

    const cleanReplyingAccountId = replyingAccountId.trim();
    if (msg.receivingAccountId !== cleanReplyingAccountId) {
      return {
        authorized: false,
        reason: 'ACCOUNT_MISMATCH',
      };
    }

    msg.status = MESSAGE_STATUS.REPLIED;

    return {
      authorized: true,
      messageId: msg.id,
      channelId: this.channelId,
      receivingAccountId: msg.receivingAccountId,
      replyingAccountId: cleanReplyingAccountId,
    };
  }
}

module.exports = {
  ChannelControl,
  MESSAGE_STATUS,
};
