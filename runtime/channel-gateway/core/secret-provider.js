/**
 * runtime/channel-gateway/core/secret-provider.js
 *
 * ADR-0026: Gateway Secret Provider & Runtime Secret Consumption Boundary.
 *
 * Invariants:
 * - Provider-neutral core contracts and non-secret reference domain model.
 * - Zero OS API calls, zero filesystem calls, zero environment-secret lookup.
 * - Zero Credential Manager enumeration.
 * - Zero third-party dependencies (Node.js built-ins only).
 * - Canonical credential target namespace: HH.AI_v2/channel-gateway/v1
 * - Deterministic, non-secret TargetName generation prevents separator/control-character injection.
 * - Stable, fail-closed error semantics for secret retrieval.
 */

'use strict';

const TARGET_NAMESPACE_PREFIX = 'HH.AI_v2/channel-gateway/v1';

const SECRET_PURPOSES = Object.freeze({
  TELEGRAM_BOT_TOKEN: 'telegram-bot-token',
  LINE_CHANNEL_ACCESS_TOKEN: 'line-channel-access-token',
  LINE_CHANNEL_SECRET: 'line-channel-secret',
  LOCAL_API_HMAC: 'local-api-hmac',
});

const VALID_ERROR_CODES = new Set([
  'INVALID_SECRET_REFERENCE',
  'UNSUPPORTED_PLATFORM',
  'PROVIDER_UNAVAILABLE',
  'SECRET_NOT_FOUND',
  'PROVIDER_ACCESS_DENIED',
  'SECRET_EMPTY',
  'PROVIDER_PROTOCOL_ERROR',
]);

const CONTROL_CHAR_REGEX = /[\x00-\x1F\x7F]/;

/**
 * Validates that a string contains only well-formed UTF-16 code units (Unicode scalar sequence).
 * Rejects unpaired high/low surrogates without altering or silently replacing characters.
 *
 * @param {string} str
 * @returns {boolean}
 */
function isWellFormedUtf16(str) {
  if (typeof str !== 'string') {
    return false;
  }
  const len = str.length;
  for (let i = 0; i < len; i++) {
    const code = str.charCodeAt(i);
    if (code >= 0xD800 && code <= 0xDBFF) {
      if (i + 1 >= len) {
        return false;
      }
      const nextCode = str.charCodeAt(i + 1);
      if (nextCode < 0xDC00 || nextCode > 0xDFFF) {
        return false;
      }
      i++;
    } else if (code >= 0xDC00 && code <= 0xDFFF) {
      return false;
    }
  }
  return true;
}

const CANONICAL_TARGET_REGEX = Object.freeze(
  /^HH\.AI_v2\/channel-gateway\/v1\/(?:telegram\/(?:[A-Za-z0-9_.~!*()-]|%[0-9A-Fa-f]{2})+\/bot-token|line\/(?:[A-Za-z0-9_.~!*()-]|%[0-9A-Fa-f]{2})+\/(?:channel-access-token|channel-secret)|local-api\/hmac)$/
);

/**
 * Asserts that a targetName matches the canonical HH.AI_v2 Credential Manager grammar.
 * Fails closed with INVALID_SECRET_REFERENCE on mismatch.
 *
 * @param {string} targetName
 */
function assertCanonicalTargetGrammar(targetName) {
  if (typeof targetName !== 'string' || !CANONICAL_TARGET_REGEX.test(targetName)) {
    throw new SecretProviderError(
      'TargetName violates canonical HH.AI_v2 Credential Manager grammar',
      'INVALID_SECRET_REFERENCE'
    );
  }
}

/**
 * Custom error hierarchy for secret provider failures.
 * Never incorporates secret values, raw payloads, or length into message.
 */
class SecretProviderError extends Error {
  /**
   * @param {string} message - Non-secret error message
   * @param {string} code - Stable error code
   */
  constructor(message, code) {
    super(message);
    this.name = 'SecretProviderError';
    if (!VALID_ERROR_CODES.has(code)) {
      throw new TypeError(`Invalid SecretProviderError code: '${code}'`);
    }
    this.code = code;
  }
}

/**
 * Validates and deterministically encodes an account identifier.
 * Prevents separator injection, directory traversal, and control character attacks.
 * Rejects raw ASCII controls/DEL and ill-formed UTF-16 surrogates before trim, then percent-encodes with apostrophe as %27.
 *
 * @param {string} accountId
 * @returns {string} Deterministically encoded account ID
 */
function encodeAccountId(accountId) {
  if (typeof accountId !== 'string') {
    throw new SecretProviderError('accountId must be a string', 'INVALID_SECRET_REFERENCE');
  }
  if (CONTROL_CHAR_REGEX.test(accountId)) {
    throw new SecretProviderError('accountId contains forbidden control characters', 'INVALID_SECRET_REFERENCE');
  }
  if (!isWellFormedUtf16(accountId)) {
    throw new SecretProviderError('accountId contains ill-formed Unicode surrogate code units', 'INVALID_SECRET_REFERENCE');
  }
  const trimmed = accountId.trim();
  if (!trimmed) {
    throw new SecretProviderError('accountId cannot be empty or blank', 'INVALID_SECRET_REFERENCE');
  }
  try {
    return encodeURIComponent(trimmed).replace(/'/g, '%27');
  } catch (err) {
    throw new SecretProviderError('Failed to encode accountId', 'INVALID_SECRET_REFERENCE');
  }
}

/**
 * Non-secret, deterministic credential reference domain model.
 * Closed domain model: instances are deeply frozen and immutable upon construction.
 */
class SecretRef {
  /**
   * @param {object} params
   * @param {string} params.channel - Channel identifier ('telegram', 'line', 'local-api')
   * @param {string} params.purpose - Purpose from SECRET_PURPOSES
   * @param {string|null} [params.accountId=null] - Account ID for account-scoped secrets
   */
  constructor({ channel, purpose, accountId = null }) {
    if (!channel || typeof channel !== 'string' || !channel.trim()) {
      throw new SecretProviderError('channel must be a non-empty string', 'INVALID_SECRET_REFERENCE');
    }
    const cleanChannel = channel.trim();

    if (!purpose || typeof purpose !== 'string' || !purpose.trim()) {
      throw new SecretProviderError('purpose must be a non-empty string', 'INVALID_SECRET_REFERENCE');
    }
    const cleanPurpose = purpose.trim();

    const allowedPurposes = Object.values(SECRET_PURPOSES);
    if (!allowedPurposes.includes(cleanPurpose)) {
      throw new SecretProviderError(`Unsupported secret purpose: '${cleanPurpose}'`, 'INVALID_SECRET_REFERENCE');
    }

    if (cleanPurpose === SECRET_PURPOSES.LOCAL_API_HMAC) {
      if (cleanChannel !== 'local-api') {
        throw new SecretProviderError(`Channel for LOCAL_API_HMAC must be 'local-api', got '${cleanChannel}'`, 'INVALID_SECRET_REFERENCE');
      }
      if (accountId !== null && accountId !== undefined) {
        throw new SecretProviderError('accountId must be null or undefined for global LOCAL_API_HMAC', 'INVALID_SECRET_REFERENCE');
      }
      this.channel = 'local-api';
      this.purpose = cleanPurpose;
      this.accountId = null;
      this.encodedAccountId = null;
    } else {
      // Account-scoped purposes
      if (cleanPurpose === SECRET_PURPOSES.TELEGRAM_BOT_TOKEN && cleanChannel !== 'telegram') {
        throw new SecretProviderError(`Channel for TELEGRAM_BOT_TOKEN must be 'telegram', got '${cleanChannel}'`, 'INVALID_SECRET_REFERENCE');
      }
      if (
        (cleanPurpose === SECRET_PURPOSES.LINE_CHANNEL_ACCESS_TOKEN || cleanPurpose === SECRET_PURPOSES.LINE_CHANNEL_SECRET) &&
        cleanChannel !== 'line'
      ) {
        throw new SecretProviderError(`Channel for '${cleanPurpose}' must be 'line', got '${cleanChannel}'`, 'INVALID_SECRET_REFERENCE');
      }

      const encoded = encodeAccountId(accountId);
      this.channel = cleanChannel;
      this.purpose = cleanPurpose;
      this.accountId = accountId.trim();
      this.encodedAccountId = encoded;
    }

    // Freeze instance to enforce immutability boundary (F1-C)
    Object.freeze(this);
  }

  /**
   * Deterministically derives the canonical Credential Manager TargetName.
   * @returns {string} Non-secret canonical target name
   */
  getTargetName() {
    switch (this.purpose) {
      case SECRET_PURPOSES.TELEGRAM_BOT_TOKEN:
        return `${TARGET_NAMESPACE_PREFIX}/telegram/${this.encodedAccountId}/bot-token`;
      case SECRET_PURPOSES.LINE_CHANNEL_ACCESS_TOKEN:
        return `${TARGET_NAMESPACE_PREFIX}/line/${this.encodedAccountId}/channel-access-token`;
      case SECRET_PURPOSES.LINE_CHANNEL_SECRET:
        return `${TARGET_NAMESPACE_PREFIX}/line/${this.encodedAccountId}/channel-secret`;
      case SECRET_PURPOSES.LOCAL_API_HMAC:
        return `${TARGET_NAMESPACE_PREFIX}/local-api/hmac`;
      default:
        throw new SecretProviderError(`Unsupported secret purpose: '${this.purpose}'`, 'INVALID_SECRET_REFERENCE');
    }
  }

  /**
   * Re-derives the canonical TargetName from validated semantic fields.
   * Caller method overrides are never consulted (F1-C).
   *
   * @param {SecretRef} secretRef
   * @returns {string} Canonical target name
   */
  static deriveCanonicalTarget(secretRef) {
    SecretProvider.validateSecretRef(secretRef);
    const canonical = new SecretRef({
      channel: secretRef.channel,
      purpose: secretRef.purpose,
      accountId: secretRef.accountId,
    });
    const target = SecretRef.prototype.getTargetName.call(canonical);
    assertCanonicalTargetGrammar(target);
    return target;
  }

  // Static Factory Helpers
  static telegramBotToken(accountId) {
    return new SecretRef({
      channel: 'telegram',
      purpose: SECRET_PURPOSES.TELEGRAM_BOT_TOKEN,
      accountId,
    });
  }

  static lineChannelAccessToken(accountId) {
    return new SecretRef({
      channel: 'line',
      purpose: SECRET_PURPOSES.LINE_CHANNEL_ACCESS_TOKEN,
      accountId,
    });
  }

  static lineChannelSecret(accountId) {
    return new SecretRef({
      channel: 'line',
      purpose: SECRET_PURPOSES.LINE_CHANNEL_SECRET,
      accountId,
    });
  }

  static localApiHmac() {
    return new SecretRef({
      channel: 'local-api',
      purpose: SECRET_PURPOSES.LOCAL_API_HMAC,
    });
  }
}

/**
 * Base abstract SecretProvider contract.
 */
class SecretProvider {
  /**
   * Validates a SecretRef object. Rejects null, non-instances, and non-exact prototypes.
   * @param {any} secretRef
   * @returns {SecretRef}
   */
  static validateSecretRef(secretRef) {
    if (!secretRef || !(secretRef instanceof SecretRef)) {
      throw new SecretProviderError('secretRef must be an instance of SecretRef', 'INVALID_SECRET_REFERENCE');
    }
    if (Object.getPrototypeOf(secretRef) !== SecretRef.prototype) {
      throw new SecretProviderError(
        'secretRef must be an exact SecretRef instance; subclasses and prototype overrides are rejected',
        'INVALID_SECRET_REFERENCE'
      );
    }
    return secretRef;
  }

  /**
   * Resolves secret material for a SecretRef.
   * @param {SecretRef} secretRef
   * @returns {Buffer} Raw secret bytes
   */
  getSecret(secretRef) {
    throw new SecretProviderError('Abstract method getSecret must be implemented by subclass', 'PROVIDER_PROTOCOL_ERROR');
  }
}

module.exports = {
  TARGET_NAMESPACE_PREFIX,
  SECRET_PURPOSES,
  VALID_ERROR_CODES,
  CANONICAL_TARGET_REGEX,
  assertCanonicalTargetGrammar,
  SecretProviderError,
  SecretRef,
  SecretProvider,
  encodeAccountId,
  CONTROL_CHAR_REGEX,
  isWellFormedUtf16,
};
