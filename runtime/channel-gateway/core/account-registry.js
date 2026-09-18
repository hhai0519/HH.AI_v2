/**
 * runtime/channel-gateway/core/account-registry.js
 *
 * ADR-0022 D3 / D26: Non-Secret Account Metadata Domain Model.
 *
 * Invariants:
 * - Pure in-memory domain model for non-secret account metadata.
 * - NOT a credential store, NOT a LINE quota API, NOT a bot adapter.
 * - Strict allowlist schema: ONLY non-secret metadata fields are permitted.
 * - Secret fields (token, botToken, accessToken, channelSecret, secret, password, apiKey, etc.)
 *   and arbitrary unknown keys are strictly rejected, never saved.
 * - Multiple accounts may be registered per channel/platform.
 * - Exactly zero or one active account at any time.
 * - Disabled accounts cannot become active.
 * - Test Bot is an ordinary registered account (no special architecture type or branch).
 * - Output contains strictly non-secret metadata.
 */

'use strict';

const ALLOWED_METADATA_FIELDS = new Set([
  'id',
  'label',
  'description',
  'enabled',
  'channel',
]);

const CONTROL_CHAR_REGEX = /[\x00-\x1F\x7F]/;

const FORBIDDEN_SECRET_NAMES = new Set([
  'token',
  'bottoken',
  'accesstoken',
  'channelsecret',
  'secret',
  'password',
  'apikey',
  'api_key',
  'private_key',
  'credential',
]);

class AccountRegistry {
  /**
   * @param {string} [channel] - Channel/platform identifier (e.g. 'telegram', 'line'). Defaults to 'default'.
   */
  constructor(channel = 'default') {
    if (!channel || typeof channel !== 'string' || !channel.trim()) {
      throw new TypeError('channel must be a non-empty string');
    }
    this.channel = channel.trim();
    this.accounts = new Map();
    this.activeAccountId = null;
  }

  /**
   * Validate account data against strict allowlist.
   * Rejects any secret-like or unknown fields.
   *
   * @param {object} accountData
   * @returns {object} Cleaned account metadata
   */
  static validateMetadata(accountData) {
    if (!accountData || typeof accountData !== 'object' || Array.isArray(accountData)) {
      throw new TypeError('Account metadata must be a non-null object');
    }

    const keys = Object.keys(accountData);

    for (const key of keys) {
      const lowerKey = key.toLowerCase();
      if (FORBIDDEN_SECRET_NAMES.has(lowerKey)) {
        throw new Error(`Security rejection: Field '${key}' is forbidden in non-secret account registry`);
      }
      if (!ALLOWED_METADATA_FIELDS.has(key)) {
        throw new Error(`Schema rejection: Unknown field '${key}' is not allowed in account metadata`);
      }
    }

    const { id, label, description, enabled, channel } = accountData;

    if (typeof id !== 'string') {
      throw new TypeError('id must be a non-empty string');
    }
    if (CONTROL_CHAR_REGEX.test(id)) {
      throw new Error('id contains forbidden control characters');
    }
    const cleanId = id.trim();
    if (!cleanId) {
      throw new TypeError('id must be a non-empty string');
    }
    if (!label || typeof label !== 'string' || !label.trim()) {
      throw new TypeError('label must be a non-empty string');
    }
    if (description !== undefined && typeof description !== 'string') {
      throw new TypeError('description must be a string');
    }
    if (enabled !== undefined && typeof enabled !== 'boolean') {
      throw new TypeError('enabled must be a boolean');
    }
    if (channel !== undefined && (typeof channel !== 'string' || !channel.trim())) {
      throw new TypeError('channel must be a non-empty string if provided');
    }

    return {
      id: id.trim(),
      label: label.trim(),
      description: description !== undefined ? description.trim() : '',
      enabled: enabled !== undefined ? enabled : true,
      channel: channel !== undefined ? channel.trim() : undefined,
    };
  }

  /**
   * Register a new account with non-secret metadata.
   * Enforces registry channel boundary (ADR-0022 D26).
   *
   * @param {object} accountData
   * @returns {object} Registered non-secret account metadata
   */
  register(accountData) {
    const validated = AccountRegistry.validateMetadata(accountData);

    if (validated.channel !== undefined && validated.channel !== this.channel) {
      throw new Error(`CHANNEL_MISMATCH: Account channel '${validated.channel}' does not match registry channel '${this.channel}'`);
    }

    if (this.accounts.has(validated.id)) {
      throw new Error(`Account with id '${validated.id}' is already registered`);
    }

    const record = {
      id: validated.id,
      label: validated.label,
      description: validated.description,
      enabled: validated.enabled,
      channel: this.channel,
    };

    this.accounts.set(record.id, record);

    return this.get(record.id);
  }

  /**
   * Set active account (D3).
   * At most one active account at any time.
   * Switching active account automatically clears previous active state.
   * Disabled account cannot become active.
   *
   * @param {string} id
   * @returns {object} Activated account metadata
   */
  setActive(id) {
    if (typeof id !== 'string') {
      throw new TypeError('id must be a non-empty string');
    }
    if (CONTROL_CHAR_REGEX.test(id)) {
      throw new Error('id contains forbidden control characters');
    }
    const cleanId = id.trim();
    if (!cleanId) {
      throw new TypeError('id must be a non-empty string');
    }
    const account = this.accounts.get(cleanId);
    if (!account) {
      throw new Error(`Account '${cleanId}' not found`);
    }

    if (!account.enabled) {
      throw new Error(`Cannot activate disabled account '${cleanId}'`);
    }

    this.activeAccountId = cleanId;

    return this.getActive();
  }

  /**
   * Clear active account.
   */
  clearActive() {
    this.activeAccountId = null;
  }

  /**
   * Retrieve current active account metadata (or null if none).
   * @returns {object|null}
   */
  getActive() {
    if (!this.activeAccountId) {
      return null;
    }
    return this.get(this.activeAccountId);
  }

  /**
   * Retrieve non-secret metadata for a specific account.
   *
   * @param {string} id
   * @returns {object|null}
   */
  get(id) {
    const account = this.accounts.get(id);
    if (!account) {
      return null;
    }
    return {
      id: account.id,
      label: account.label,
      description: account.description,
      enabled: account.enabled,
      channel: account.channel,
      isActive: account.id === this.activeAccountId,
    };
  }

  /**
   * Disable an account.
   * If the disabled account was currently active, clears active state.
   *
   * @param {string} id
   */
  disable(id) {
    const account = this.accounts.get(id);
    if (!account) {
      throw new Error(`Account '${id}' not found`);
    }
    account.enabled = false;
    if (this.activeAccountId === id) {
      this.activeAccountId = null;
    }
  }

  /**
   * Enable an account.
   *
   * @param {string} id
   */
  enable(id) {
    const account = this.accounts.get(id);
    if (!account) {
      throw new Error(`Account '${id}' not found`);
    }
    account.enabled = true;
  }

  /**
   * List all registered accounts with strictly non-secret metadata.
   *
   * @returns {Array<object>}
   */
  list() {
    const list = [];
    for (const id of this.accounts.keys()) {
      list.push(this.get(id));
    }
    return list;
  }
}

module.exports = {
  AccountRegistry,
  ALLOWED_METADATA_FIELDS,
  CONTROL_CHAR_REGEX,
};
