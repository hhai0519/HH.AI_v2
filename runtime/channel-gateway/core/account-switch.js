/**
 * runtime/channel-gateway/core/account-switch.js
 *
 * ADR-0022 D26: Pure domain orchestration for account switching.
 *
 * Invariants:
 * - Pure domain orchestration between AccountRegistry and ChannelControl.
 * - Zero external dependencies. Zero network, filesystem, timer, or OS side effects.
 * - Coordinator enforces channel boundary between registry and control (CHANNEL_CONTROL_MISMATCH).
 * - Every account selection / switch operation has explicit takeover intent (Switch = Takeover).
 * - Target validation is atomic: invalid/missing/disabled target causes ZERO MUTATION.
 * - Different-account switch (A -> B):
 *     * Performs takeover (increments monotonic fencing token).
 *     * Discards all pending messages for old account A (CLAIMED via takeover + QUEUED via discardQueuedForAccount).
 *     * Preserves QUEUED messages for target account B.
 *     * Sets target B as active account in registry.
 * - Same-account selection (A -> A):
 *     * Performs takeover (fencing token increments).
 *     * accountChanged = false.
 *     * Preserves QUEUED messages for account A (takeover only, not account migration).
 * - No previous active account (null -> B):
 *     * Performs takeover.
 *     * Sets B as active account.
 *     * Preserves QUEUED messages for account B.
 * - Reports discardedOldAccountMessages with non-secret metadata for IDE visibility.
 */

'use strict';

class AccountSwitchCoordinator {
  /**
   * @param {object} registry - AccountRegistry instance
   * @param {object} control - ChannelControl instance
   */
  constructor(registry, control) {
    if (!registry || typeof registry !== 'object') {
      throw new TypeError('registry must be an AccountRegistry instance or compatible object');
    }
    if (!control || typeof control !== 'object') {
      throw new TypeError('control must be a ChannelControl instance or compatible object');
    }

    const registryChannel = typeof registry.channel === 'string' ? registry.channel.trim() : '';
    const controlChannel = typeof control.channelId === 'string' ? control.channelId.trim() : '';

    if (!registryChannel || !controlChannel || registryChannel !== controlChannel) {
      throw new Error(
        `CHANNEL_CONTROL_MISMATCH: Registry channel '${registryChannel}' does not match control channel '${controlChannel}'`
      );
    }

    this.registry = registry;
    this.control = control;
  }

  /**
   * Switch active account with explicit takeover and pending message hygiene (ADR-0022 D26).
   *
   * @param {string} targetAccountId - Target account to activate
   * @param {string} holderId - Agent identity acquiring control
   * @param {object} [metadata={}] - Optional metadata passed to takeover
   * @returns {object} Switch transition result
   */
  switchActiveAccount(targetAccountId, holderId, metadata = {}) {
    // 1. Pre-validation (Fail-fast with ZERO MUTATION)
    if (!targetAccountId || typeof targetAccountId !== 'string' || !targetAccountId.trim()) {
      throw new TypeError('targetAccountId must be a non-empty string');
    }
    if (!holderId || typeof holderId !== 'string' || !holderId.trim()) {
      throw new TypeError('holderId must be a non-empty string');
    }

    const cleanTargetId = targetAccountId.trim();
    const cleanHolderId = holderId.trim();

    // Verify channel alignment at invocation time
    if (this.registry.channel !== this.control.channelId) {
      throw new Error(
        `CHANNEL_CONTROL_MISMATCH: Registry channel '${this.registry.channel}' does not match control channel '${this.control.channelId}'`
      );
    }

    const targetAccount = this.registry.get(cleanTargetId);
    if (!targetAccount) {
      throw new Error(`TARGET_NOT_FOUND: Target account '${cleanTargetId}' not found in registry`);
    }

    if (!targetAccount.enabled) {
      throw new Error(`TARGET_DISABLED: Target account '${cleanTargetId}' is disabled`);
    }

    // 2. Identify previous active account state
    const previousActive = this.registry.getActive();
    const previousActiveAccountId = previousActive ? previousActive.id : null;
    const isSameAccount = previousActiveAccountId === cleanTargetId;
    const accountChanged = !isSameAccount;

    // 3. Explicit takeover (D26: switch = takeover intent)
    const takeoverResult = this.control.takeover(cleanHolderId, metadata);

    let discardedOldAccountMessages = [];

    // 4. Handle account mutation and message discard
    if (accountChanged) {
      // Activate target account in registry
      this.registry.setActive(cleanTargetId);

      // If switching from an existing active account A -> B, discard A's pending messages
      if (previousActiveAccountId) {
        // Old holder claimed messages discarded during takeover (D9)
        const oldClaimedDiscarded = takeoverResult.discardedMessages.filter(
          (m) => m.receivingAccountId === previousActiveAccountId
        );

        // Old account queued messages default discarded on account switch (D26)
        const oldQueuedDiscarded = this.control.discardQueuedForAccount(
          previousActiveAccountId,
          'ACCOUNT_SWITCH'
        );

        discardedOldAccountMessages = [...oldClaimedDiscarded, ...oldQueuedDiscarded];
      }
    } else {
      // Same-account selection (A -> A): takeover only, preserve queued messages
      discardedOldAccountMessages = [];
    }

    // 5. Return domain transition result
    return {
      success: true,
      channelId: this.control.channelId,
      previousActiveAccountId,
      activeAccountId: cleanTargetId,
      accountChanged,
      holder: this.control.currentHolder,
      fencingToken: this.control.fencingToken,
      discardedOldAccountMessages,
      backlogCount: this.control.getBacklogCount(),
      takeoverResult,
    };
  }
}

module.exports = {
  AccountSwitchCoordinator,
};
