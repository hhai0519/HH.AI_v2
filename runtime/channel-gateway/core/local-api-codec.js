/**
 * runtime/channel-gateway/core/local-api-codec.js
 *
 * TG-MVP-11: Local API Protocol Codec, Constants, Canonical Formats & Security Headers Parser.
 */

'use strict';

const crypto = require('node:crypto');

// Protocol Domains
const PROTOCOL_DOMAIN = 'HHAI-LOCAL-API-V1';
const REQ_DOMAIN = 'HHAI-REQ-V1';
const RESP_DOMAIN = 'HHAI-RESP-V1';

// Frozen Protocol and Security Constants
const FRESHNESS_WINDOW_SEC = 30;
const NONCE_RETENTION_SEC = 60;
const MAX_BODY_BYTES = 65536;
const MAX_HEADER_BYTES = 8192;
const HEADERS_TIMEOUT_MS = 5000;
const REQUEST_TIMEOUT_MS = 10000;
const CONNECTIONS_CHECKING_INTERVAL_MS = 1000;
const KEEP_ALIVE_TIMEOUT_MS = 5000;
const SOCKET_IDLE_TIMEOUT_MS = 15000;
const MAX_CONNECTIONS = 32;
const MAX_REQUESTS_PER_SOCKET = 2;
const HELLO_CACHE_MAX = 4096;
const POLL_LIMIT_MIN = 1;
const POLL_LIMIT_MAX = 50;
const CLAIMED_READ_MAX = 50;
const REPLY_TEXT_MAX_UTF16 = 4096;
const SHUTDOWN_DRAIN_MS = 2000;
const CANONICAL_PORT = 3003;

// Canonical Security Header Names
const HEADER_VERSION = 'x-hhai-version';
const HEADER_TIMESTAMP = 'x-hhai-timestamp';
const HEADER_NONCE = 'x-hhai-nonce';
const HEADER_SESSION_ID = 'x-hhai-session-id';
const HEADER_SIGNATURE = 'x-hhai-signature';

/**
 * Computes SHA-256 hex digest of given Buffer or string.
 *
 * @param {Buffer|string} data
 * @returns {string} Lowercase hex SHA-256 digest
 */
function computeSha256(data) {
  if (data === undefined || data === null) {
    data = Buffer.alloc(0);
  } else if (typeof data === 'string') {
    data = Buffer.from(data, 'utf-8');
  } else if (!Buffer.isBuffer(data)) {
    throw new TypeError('Data must be a Buffer or string');
  }
  return crypto.createHash('sha256').update(data).digest('hex');
}

/**
 * Builds canonical string for a HELLO request.
 *
 * Format:
 * HHAI-REQ-V1
 * HELLO
 * POST
 * /v1/hello
 * <TIMESTAMP>
 * <NONCE>
 * <BODY_SHA256>
 */
function buildCanonicalHelloRequest({ timestamp, nonce, bodySha256 }) {
  if (timestamp === undefined || timestamp === null) throw new Error('Missing timestamp');
  if (!nonce) throw new Error('Missing nonce');
  if (!bodySha256) throw new Error('Missing bodySha256');

  return [
    REQ_DOMAIN,
    'HELLO',
    'POST',
    '/v1/hello',
    String(timestamp),
    String(nonce),
    String(bodySha256),
  ].join('\n');
}

/**
 * Builds canonical string for a SESSION request.
 *
 * Format:
 * HHAI-REQ-V1
 * SESSION
 * <METHOD>
 * <PATH>
 * <TIMESTAMP>
 * <NONCE>
 * <SESSION_ID>
 * <BODY_SHA256>
 */
function buildCanonicalSessionRequest({ method, path, timestamp, nonce, sessionId, bodySha256 }) {
  if (!method) throw new Error('Missing method');
  if (!path) throw new Error('Missing path');
  if (timestamp === undefined || timestamp === null) throw new Error('Missing timestamp');
  if (!nonce) throw new Error('Missing nonce');
  if (!sessionId) throw new Error('Missing sessionId');
  if (!bodySha256) throw new Error('Missing bodySha256');

  return [
    REQ_DOMAIN,
    'SESSION',
    String(method).toUpperCase(),
    String(path),
    String(timestamp),
    String(nonce),
    String(sessionId),
    String(bodySha256),
  ].join('\n');
}

/**
 * Builds canonical string for a response (HELLO or SESSION).
 *
 * Format:
 * HHAI-RESP-V1
 * <MODE>
 * <STATUS_CODE>
 * <REQUEST_METHOD>
 * <REQUEST_PATH>
 * <REQUEST_NONCE>
 * <RESPONSE_TIMESTAMP>
 * <SESSION_ID>
 * <BODY_SHA256>
 */
function buildCanonicalResponse({
  mode,
  statusCode,
  requestMethod,
  requestPath,
  requestNonce,
  responseTimestamp,
  sessionId,
  bodySha256,
}) {
  if (!mode || (mode !== 'HELLO' && mode !== 'SESSION')) throw new Error('Invalid or missing mode');
  if (statusCode === undefined || statusCode === null) throw new Error('Missing statusCode');
  if (!requestMethod) throw new Error('Missing requestMethod');
  if (!requestPath) throw new Error('Missing requestPath');
  if (!requestNonce) throw new Error('Missing requestNonce');
  if (responseTimestamp === undefined || responseTimestamp === null) throw new Error('Missing responseTimestamp');
  if (!sessionId) throw new Error('Missing sessionId');
  if (!bodySha256) throw new Error('Missing bodySha256');

  return [
    RESP_DOMAIN,
    String(mode),
    String(statusCode),
    String(requestMethod).toUpperCase(),
    String(requestPath),
    String(requestNonce),
    String(responseTimestamp),
    String(sessionId),
    String(bodySha256),
  ].join('\n');
}

/**
 * Computes HMAC-SHA256 digest of canonical string using secret Buffer or string.
 *
 * @param {Buffer|string} secret
 * @param {string} canonicalString
 * @returns {string} Lowercase hex HMAC digest
 */
function computeHmac(secret, canonicalString) {
  if (!secret) throw new Error('Missing secret for HMAC computation');
  if (typeof canonicalString !== 'string') throw new Error('canonicalString must be a string');
  return crypto.createHmac('sha256', secret).update(Buffer.from(canonicalString, 'utf-8')).digest('hex');
}

/**
 * Verifies HMAC signature using constant-time comparison via crypto.timingSafeEqual.
 *
 * @param {Buffer|string} secret
 * @param {string} canonicalString
 * @param {string} providedSignatureHex
 * @returns {boolean} True if signature is valid, false otherwise
 */
function verifyHmac(secret, canonicalString, providedSignatureHex) {
  if (!secret || !canonicalString || !providedSignatureHex) {
    return false;
  }
  if (typeof providedSignatureHex !== 'string' || providedSignatureHex.length !== 64) {
    return false;
  }
  // Validate hex characters
  if (!/^[0-9a-fA-F]{64}$/.test(providedSignatureHex)) {
    return false;
  }

  const expectedHmacHex = computeHmac(secret, canonicalString);
  const expectedBuf = Buffer.from(expectedHmacHex, 'hex');
  const providedBuf = Buffer.from(providedSignatureHex, 'hex');

  if (expectedBuf.length !== providedBuf.length || expectedBuf.length !== 32) {
    return false;
  }

  // Verification MUST use crypto.timingSafeEqual through the Node crypto namespace/module object
  return crypto.timingSafeEqual(expectedBuf, providedBuf);
}

/**
 * Parses raw HTTP headers array (from req.rawHeaders) to extract and validate security headers.
 * Detects duplicates among X-HHAI-* headers case-insensitively.
 *
 * @param {Array<string>} rawHeaders Array of alternating key and value strings
 * @returns {{
 *   ok: boolean,
 *   code?: string,
 *   error?: string,
 *   headers?: {
 *     version?: string,
 *     timestamp?: string,
 *     nonce?: string,
 *     sessionId?: string,
 *     signature?: string,
 *     allSecurityHeaders: Object
 *   }
 * }}
 */
function parseRawSecurityHeaders(rawHeaders) {
  if (!Array.isArray(rawHeaders)) {
    return { ok: false, code: 'INVALID_HEADER_ARRAY', error: 'rawHeaders must be an array' };
  }

  const seenSecurityHeaders = new Set();
  const securityHeaders = {};

  for (let i = 0; i < rawHeaders.length; i += 2) {
    const rawKey = rawHeaders[i];
    const rawVal = rawHeaders[i + 1] !== undefined ? rawHeaders[i + 1] : '';
    if (typeof rawKey !== 'string') continue;

    const lowerKey = rawKey.toLowerCase();
    if (lowerKey.startsWith('x-hhai-')) {
      if (seenSecurityHeaders.has(lowerKey)) {
        return {
          ok: false,
          code: 'DUPLICATE_SECURITY_HEADER',
          error: `Duplicate security header encountered: ${rawKey}`,
        };
      }
      seenSecurityHeaders.add(lowerKey);
      securityHeaders[lowerKey] = rawVal;
    }
  }

  return {
    ok: true,
    headers: {
      version: securityHeaders[HEADER_VERSION],
      timestamp: securityHeaders[HEADER_TIMESTAMP],
      nonce: securityHeaders[HEADER_NONCE],
      sessionId: securityHeaders[HEADER_SESSION_ID],
      signature: securityHeaders[HEADER_SIGNATURE],
      allSecurityHeaders: securityHeaders,
    },
  };
}

module.exports = {
  PROTOCOL_DOMAIN,
  REQ_DOMAIN,
  RESP_DOMAIN,
  FRESHNESS_WINDOW_SEC,
  NONCE_RETENTION_SEC,
  MAX_BODY_BYTES,
  MAX_HEADER_BYTES,
  HEADERS_TIMEOUT_MS,
  REQUEST_TIMEOUT_MS,
  CONNECTIONS_CHECKING_INTERVAL_MS,
  KEEP_ALIVE_TIMEOUT_MS,
  SOCKET_IDLE_TIMEOUT_MS,
  MAX_CONNECTIONS,
  MAX_REQUESTS_PER_SOCKET,
  HELLO_CACHE_MAX,
  POLL_LIMIT_MIN,
  POLL_LIMIT_MAX,
  CLAIMED_READ_MAX,
  REPLY_TEXT_MAX_UTF16,
  SHUTDOWN_DRAIN_MS,
  CANONICAL_PORT,
  HEADER_VERSION,
  HEADER_TIMESTAMP,
  HEADER_NONCE,
  HEADER_SESSION_ID,
  HEADER_SIGNATURE,
  computeSha256,
  buildCanonicalHelloRequest,
  buildCanonicalSessionRequest,
  buildCanonicalResponse,
  computeHmac,
  verifyHmac,
  parseRawSecurityHeaders,
};
