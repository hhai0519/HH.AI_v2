/**
 * runtime/channel-gateway/tests/local-api-codec.test.js
 *
 * Tests for Local API Codec, Canonical Formats, TimingSafeEqual Contract & Raw Security Headers Parser.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {
  PROTOCOL_DOMAIN,
  REQ_DOMAIN,
  RESP_DOMAIN,
  computeSha256,
  buildCanonicalHelloRequest,
  buildCanonicalSessionRequest,
  buildCanonicalResponse,
  computeHmac,
  verifyHmac,
  parseRawSecurityHeaders,
} = require('../core/local-api-codec');

// Deterministic Fake Secret for Tests ONLY
const FAKE_SECRET = Buffer.from('test-fake-secret-do-not-use-in-prod-32b', 'utf-8');

// Four Hard-coded Deterministic Test Vectors
const VECTOR_1 = {
  description: 'HELLO request',
  canonical:
    'HHAI-REQ-V1\nHELLO\nPOST\n/v1/hello\n1727265600\ntest-nonce-hello-01\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  expectedHmac: '73216eb048352aa08b61e63ba3361fadad75a0c7b6e2f259a0826f1173299e5d',
};

const VECTOR_2 = {
  description: 'SESSION request',
  canonical:
    'HHAI-REQ-V1\nSESSION\nPOST\n/v1/poll\n1727265601\ntest-nonce-session-02\n0123456789abcdef0123456789abcdef\n1dabede6156e0ca45687d19c596e96ebaf22d16a200be19b1532c0da4f327668',
  expectedHmac: 'db43dfe26984f4eadfa6d344c3f17d876e438afa5fb9311cac3ee178efa08e3c',
};

const VECTOR_3 = {
  description: 'HELLO response',
  canonical:
    'HHAI-RESP-V1\nHELLO\n200\nPOST\n/v1/hello\ntest-nonce-hello-01\n1727265602\n0123456789abcdef0123456789abcdef\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  expectedHmac: '11c6ea62e06eab5777919b2ea0e59ee81d42bc54d54812cb5364a425e3663c12',
};

const VECTOR_4 = {
  description: 'SESSION response',
  canonical:
    'HHAI-RESP-V1\nSESSION\n200\nPOST\n/v1/poll\ntest-nonce-session-02\n1727265603\n0123456789abcdef0123456789abcdef\n6653c5ae1651735565e703ff31dd4659b42b816e4fc6937532d68d391e1e4ad0',
  expectedHmac: '045677b032d3ab046864390cecfea002c813b6806b650c8d54144ffaebca91d6',
};

test('codec: four deterministic fake-secret HMAC test vectors match exact digests', { timeout: 5000 }, () => {
  // Vector 1: HELLO Request
  const canon1 = buildCanonicalHelloRequest({
    timestamp: 1727265600,
    nonce: 'test-nonce-hello-01',
    bodySha256: computeSha256(''),
  });
  assert.equal(canon1, VECTOR_1.canonical);
  assert.equal(computeHmac(FAKE_SECRET, canon1), VECTOR_1.expectedHmac);
  assert.equal(verifyHmac(FAKE_SECRET, canon1, VECTOR_1.expectedHmac), true);

  // Vector 2: SESSION Request
  const body2 = Buffer.from(
    JSON.stringify({
      channel_id: 'tg:general',
      holder_id: 'agent-01',
      fencing_token: 1,
      limit: 10,
    })
  );
  const canon2 = buildCanonicalSessionRequest({
    method: 'POST',
    path: '/v1/poll',
    timestamp: 1727265601,
    nonce: 'test-nonce-session-02',
    sessionId: '0123456789abcdef0123456789abcdef',
    bodySha256: computeSha256(body2),
  });
  assert.equal(canon2, VECTOR_2.canonical);
  assert.equal(computeHmac(FAKE_SECRET, canon2), VECTOR_2.expectedHmac);
  assert.equal(verifyHmac(FAKE_SECRET, canon2, VECTOR_2.expectedHmac), true);

  // Vector 3: HELLO Response
  const canon3 = buildCanonicalResponse({
    mode: 'HELLO',
    statusCode: 200,
    requestMethod: 'POST',
    requestPath: '/v1/hello',
    requestNonce: 'test-nonce-hello-01',
    responseTimestamp: 1727265602,
    sessionId: '0123456789abcdef0123456789abcdef',
    bodySha256: computeSha256(''),
  });
  assert.equal(canon3, VECTOR_3.canonical);
  assert.equal(computeHmac(FAKE_SECRET, canon3), VECTOR_3.expectedHmac);
  assert.equal(verifyHmac(FAKE_SECRET, canon3, VECTOR_3.expectedHmac), true);

  // Vector 4: SESSION Response
  const body4 = Buffer.from(JSON.stringify({ ok: true, code: 'OK', messages: [] }));
  const canon4 = buildCanonicalResponse({
    mode: 'SESSION',
    statusCode: 200,
    requestMethod: 'POST',
    requestPath: '/v1/poll',
    requestNonce: 'test-nonce-session-02',
    responseTimestamp: 1727265603,
    sessionId: '0123456789abcdef0123456789abcdef',
    bodySha256: computeSha256(body4),
  });
  assert.equal(canon4, VECTOR_4.canonical);
  assert.equal(computeHmac(FAKE_SECRET, canon4), VECTOR_4.expectedHmac);
  assert.equal(verifyHmac(FAKE_SECRET, canon4, VECTOR_4.expectedHmac), true);
});

test('codec: verification invokes crypto.timingSafeEqual through namespace (T1 spy)', { timeout: 5000 }, (t) => {
  let timingSafeEqualCalled = false;
  const original = crypto.timingSafeEqual;

  t.mock.method(crypto, 'timingSafeEqual', (a, b) => {
    timingSafeEqualCalled = true;
    return original.call(crypto, a, b);
  });

  try {
    const valid = verifyHmac(FAKE_SECRET, VECTOR_1.canonical, VECTOR_1.expectedHmac);
    assert.equal(valid, true);
    assert.equal(timingSafeEqualCalled, true, 'crypto.timingSafeEqual MUST be invoked through namespace');
  } finally {
    t.mock.restoreAll();
  }
});

test('codec: CRLF line separator produces invalid signature', { timeout: 5000 }, () => {
  const crlfCanon = VECTOR_1.canonical.replace(/\n/g, '\r\n');
  assert.notEqual(crlfCanon, VECTOR_1.canonical);
  assert.equal(verifyHmac(FAKE_SECRET, crlfCanon, VECTOR_1.expectedHmac), false);
});

test('codec: tampered canonical fields fail HMAC verification', { timeout: 5000 }, () => {
  // Tamper method
  const tamperedMethod = VECTOR_2.canonical.replace('POST', 'GET');
  assert.equal(verifyHmac(FAKE_SECRET, tamperedMethod, VECTOR_2.expectedHmac), false);

  // Tamper timestamp
  const tamperedTs = VECTOR_2.canonical.replace('1727265601', '1727265699');
  assert.equal(verifyHmac(FAKE_SECRET, tamperedTs, VECTOR_2.expectedHmac), false);

  // Tamper nonce
  const tamperedNonce = VECTOR_2.canonical.replace('test-nonce-session-02', 'evil-nonce');
  assert.equal(verifyHmac(FAKE_SECRET, tamperedNonce, VECTOR_2.expectedHmac), false);

  // Tamper session id
  const tamperedSession = VECTOR_2.canonical.replace(
    '0123456789abcdef0123456789abcdef',
    'ffffffffffffffffffffffffffffffff'
  );
  assert.equal(verifyHmac(FAKE_SECRET, tamperedSession, VECTOR_2.expectedHmac), false);

  // Malformed signature hex
  assert.equal(verifyHmac(FAKE_SECRET, VECTOR_2.canonical, 'not-a-hex-signature'), false);
  assert.equal(verifyHmac(FAKE_SECRET, VECTOR_2.canonical, '00'.repeat(16)), false); // 16 bytes != 32 bytes
});

test('codec: raw security headers parser extracts valid headers case-insensitively', { timeout: 5000 }, () => {
  const rawHeaders = [
    'Host', '127.0.0.1:3003',
    'X-HHAI-Version', '1',
    'x-hhai-timestamp', '1727265600',
    'X-Hhai-Nonce', 'nonce-abc',
    'X-HHAI-Session-Id', 'sess-123',
    'x-hhai-signature', 'sig-hex-456',
    'Content-Type', 'application/json',
  ];

  const res = parseRawSecurityHeaders(rawHeaders);
  assert.equal(res.ok, true);
  assert.equal(res.headers.version, '1');
  assert.equal(res.headers.timestamp, '1727265600');
  assert.equal(res.headers.nonce, 'nonce-abc');
  assert.equal(res.headers.sessionId, 'sess-123');
  assert.equal(res.headers.signature, 'sig-hex-456');
});

test('codec: raw security headers parser detects duplicate X-HHAI-* headers (T11)', { timeout: 5000 }, () => {
  const rawWithDuplicate = [
    'X-HHAI-Nonce', 'nonce-first',
    'Content-Type', 'application/json',
    'x-hhai-nonce', 'nonce-second',
  ];

  const res = parseRawSecurityHeaders(rawWithDuplicate);
  assert.equal(res.ok, false);
  assert.equal(res.code, 'DUPLICATE_SECURITY_HEADER');
});
