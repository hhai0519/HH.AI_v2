/**
 * runtime/channel-gateway/core/managed-credential-target.js
 *
 * SEC-02 INC-2: Closed Managed Credential Target Resolver.
 *
 * Invariants:
 * - Deterministic, closed target resolution for managed inventory IDs.
 * - Only 6 approved targets: 4 Channel Gateway targets and 2 MCP Generic targets.
 * - Non-secret reference input; unknown properties, extra fields, caller TargetName overrides rejected fail-closed.
 * - Fixed targets strictly reject accountId; account-scoped targets require non-empty accountId.
 * - Strict character, surrogate, wildcard, and length checks.
 * - Zero machine probing, zero environment enumeration, zero OS API calls.
 * - Stable, fail-closed CredentialManagerError with code INVALID_SECRET_REFERENCE.
 */

'use strict';

const CONTROL_CHAR_REGEX = /[\x00-\x1F\x7F]/;
const MAX_TARGET_LENGTH = 32767;

const VALID_ERROR_CODES = new Set([
  'INVALID_SECRET_REFERENCE',
  'UNSUPPORTED_PLATFORM',
  'PROVIDER_UNAVAILABLE',
  'PROVIDER_PROTOCOL_ERROR',
  'PROVIDER_ACCESS_DENIED',
  'CREDENTIAL_ALREADY_EXISTS',
  'CREDENTIAL_BUSY',
  'SECRET_ENCODING_INVALID',
]);

class CredentialManagerError extends Error {
  /**
   * @param {string} message - Non-secret error message
   * @param {string} code - Stable error code
   */
  constructor(message, code) {
    super(message);
    this.name = 'CredentialManagerError';
    if (!VALID_ERROR_CODES.has(code)) {
      throw new TypeError(`Invalid CredentialManagerError code: '${code}'`);
    }
    this.code = code;
  }
}

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

const { SecretRef, SECRET_PURPOSES } = require('./secret-provider');

const MANAGED_INVENTORY_ITEMS = Object.freeze({
  GATEWAY_TELEGRAM_BOT_TOKEN: 'gateway-telegram-bot-token',
  GATEWAY_LINE_CHANNEL_ACCESS_TOKEN: 'gateway-line-channel-access-token',
  GATEWAY_LINE_CHANNEL_SECRET: 'gateway-line-channel-secret',
  GATEWAY_LOCAL_API_HMAC: 'gateway-local-api-hmac',
  MCP_JULES_API_KEY: 'mcp-jules-api-key',
  MCP_NOTION_API_TOKEN: 'mcp-notion-api-token',
});

const MCP_TARGET_MAP = Object.freeze(
  Object.assign(Object.create(null), {
    [MANAGED_INVENTORY_ITEMS.MCP_JULES_API_KEY]: 'HH.AI_v2/mcp-launcher/v1/jules/api-key',
    [MANAGED_INVENTORY_ITEMS.MCP_NOTION_API_TOKEN]: 'HH.AI_v2/mcp-launcher/v1/notion/api-token',
  })
);

/**
 * Resolves a managed credential reference to its canonical TargetName.
 *
 * @param {object} ref - Non-secret reference object
 * @param {string} ref.inventoryId - Managed inventory identifier
 * @param {string} [ref.accountId] - Optional account identifier for account-scoped secrets
 * @returns {string} Canonical TargetName
 */
function resolveManagedTarget(ref) {
  try {
    if (!ref || typeof ref !== 'object' || Array.isArray(ref)) {
      throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
    }

    const proto = Object.getPrototypeOf(ref);
    if (proto !== Object.prototype && proto !== null) {
      throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
    }

    const keys = Reflect.ownKeys(ref);
    let hasInventoryId = false;
    let hasAccountId = false;

    for (const key of keys) {
      if (typeof key !== 'string') {
        throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
      }
      if (key !== 'inventoryId' && key !== 'accountId') {
        throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
      }

      const desc = Object.getOwnPropertyDescriptor(ref, key);
      if (!desc || 'get' in desc || 'set' in desc || desc.get !== undefined || desc.set !== undefined) {
        throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
      }

      if (key === 'inventoryId') {
        hasInventoryId = true;
      } else if (key === 'accountId') {
        hasAccountId = true;
      }
    }

    if (!hasInventoryId) {
      throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
    }

    const inventoryId = ref.inventoryId;
    if (typeof inventoryId !== 'string' || !inventoryId.trim()) {
      throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
    }

    let targetName;

    if (inventoryId === MANAGED_INVENTORY_ITEMS.GATEWAY_LOCAL_API_HMAC) {
      if (hasAccountId) {
        throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
      }
      const sRef = SecretRef.localApiHmac();
      targetName = typeof sRef.toCredentialTargetName === 'function'
        ? sRef.toCredentialTargetName()
        : (typeof SecretRef.toCredentialTargetName === 'function'
            ? SecretRef.toCredentialTargetName(sRef)
            : SecretRef.deriveCanonicalTarget(sRef));
    } else if (Object.prototype.hasOwnProperty.call(MCP_TARGET_MAP, inventoryId)) {
      if (hasAccountId) {
        throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
      }
      targetName = MCP_TARGET_MAP[inventoryId];
    } else if (
      inventoryId === MANAGED_INVENTORY_ITEMS.GATEWAY_TELEGRAM_BOT_TOKEN ||
      inventoryId === MANAGED_INVENTORY_ITEMS.GATEWAY_LINE_CHANNEL_ACCESS_TOKEN ||
      inventoryId === MANAGED_INVENTORY_ITEMS.GATEWAY_LINE_CHANNEL_SECRET
    ) {
      if (!hasAccountId) {
        throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
      }
      const accountId = ref.accountId;
      if (
        typeof accountId !== 'string' ||
        !accountId.trim() ||
        accountId.includes('*') ||
        accountId.includes('?') ||
        CONTROL_CHAR_REGEX.test(accountId) ||
        !isWellFormedUtf16(accountId)
      ) {
        throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
      }

      let sRef;
      if (inventoryId === MANAGED_INVENTORY_ITEMS.GATEWAY_TELEGRAM_BOT_TOKEN) {
        sRef = SecretRef.telegramBotToken(accountId);
      } else if (inventoryId === MANAGED_INVENTORY_ITEMS.GATEWAY_LINE_CHANNEL_ACCESS_TOKEN) {
        sRef = SecretRef.lineChannelAccessToken(accountId);
      } else {
        sRef = SecretRef.lineChannelSecret(accountId);
      }

      targetName = typeof sRef.toCredentialTargetName === 'function'
        ? sRef.toCredentialTargetName()
        : (typeof SecretRef.toCredentialTargetName === 'function'
            ? SecretRef.toCredentialTargetName(sRef)
            : SecretRef.deriveCanonicalTarget(sRef));
    } else {
      throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
    }

    if (
      typeof targetName !== 'string' ||
      targetName.length > MAX_TARGET_LENGTH ||
      targetName.includes('*') ||
      targetName.includes('?') ||
      CONTROL_CHAR_REGEX.test(targetName)
    ) {
      throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
    }

    return targetName;
  } catch (err) {
    if (err instanceof CredentialManagerError) {
      throw err;
    }
    throw new CredentialManagerError('Invalid managed credential reference', 'INVALID_SECRET_REFERENCE');
  }
}

module.exports = {
  resolveManagedTarget,
  CredentialManagerError,
  MANAGED_INVENTORY_ITEMS,
  VALID_ERROR_CODES,
};
