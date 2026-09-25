/**
 * runtime/channel-gateway/tests/local-api-server.test.js
 *
 * Tests for LocalApiServer: Framing, Host/Origin bounds, HELLO pipeline, Session socket binding,
 * Replay protection, One-request-per-session, STOPPING gate, Strict Protocol Grammar,
 * Streaming Body Bounding, and HMAC-first Session Replay Ordering.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const { LocalApiServer } = require('../core/local-api-server');
const { LocalApiReplayCache } = require('../core/local-api-replay-cache');
const {
  computeSha256,
  buildCanonicalHelloRequest,
  buildCanonicalSessionRequest,
  computeHmac,
} = require('../core/local-api-codec');

const FAKE_SECRET = Buffer.from('test-fake-secret-32-bytes-long!!!', 'utf-8');

function createTestServer(options = {}) {
  const dispatcher = options.dispatcher || {
    dispatch(path, body) {
      return { status: 200, body: { ok: true, echo: body } };
    },
  };
  const replayCache = options.replayCache || new LocalApiReplayCache();
  const server = new LocalApiServer({
    secret: FAKE_SECRET,
    dispatcher,
    replayCache,
    port: 0,
    allowTestPort: true,
    nowSec: options.nowSec || (() => Math.floor(Date.now() / 1000)),
  });

  return { server, replayCache, dispatcher };
}

// Low-level helper to send raw HTTP and resolve as soon as complete response is received
function sendRawHttp(socket, rawRequest) {
  return new Promise((resolve) => {
    let responseData = '';

    function checkComplete() {
      const headerEnd = responseData.indexOf('\r\n\r\n');
      if (headerEnd !== -1) {
        const headersPart = responseData.slice(0, headerEnd);
        const matchCl = headersPart.match(/content-length:\s*([0-9]+)/i);
        if (matchCl) {
          const cl = parseInt(matchCl[1], 10);
          const bodyPart = responseData.slice(headerEnd + 4);
          if (Buffer.byteLength(bodyPart, 'utf-8') >= cl) {
            socket.removeListener('data', onData);
            resolve(responseData);
          }
        }
      }
    }

    function onData(chunk) {
      responseData += chunk.toString('utf-8');
      checkComplete();
    }

    socket.on('data', onData);
    socket.once('end', () => {
      resolve(responseData);
    });
    socket.once('close', () => {
      resolve(responseData);
    });
    socket.once('error', () => {
      resolve(responseData);
    });
    socket.write(rawRequest);
  });
}

// Helper to perform authenticated HELLO over a socket and return sessionId
async function performHello(socket, port, nonce = '11111111111111111111111111111111') {
  const ts = Math.floor(Date.now() / 1000);
  const emptySha = computeSha256(Buffer.alloc(0));
  const canon = buildCanonicalHelloRequest({ timestamp: ts, nonce, bodySha256: emptySha });
  const sig = computeHmac(FAKE_SECRET, canon);

  const req = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: ${nonce}\r\nX-HHAI-Signature: ${sig}\r\nContent-Length: 0\r\n\r\n`;

  const res = await sendRawHttp(socket, req);
  const match = res.match(/x-hhai-session-id:\s*([a-f0-9]{32})/i);
  if (!match) {
    throw new Error(`HELLO failed: ${res}`);
  }
  return { sessionId: match[1], timestamp: ts };
}

test('server: rejects incorrect Host header, Origin header, and Transfer-Encoding (T3, T4, T5)', { timeout: 5000 }, async () => {
  const { server } = createTestServer();
  const { port } = await server.start();

  try {
    const ts = Math.floor(Date.now() / 1000);
    const emptySha = computeSha256(Buffer.alloc(0));

    // 1. Wrong Host (localhost instead of 127.0.0.1:port) (T3)
    const client1 = net.connect({ port, host: '127.0.0.1' });
    const canon1 = buildCanonicalHelloRequest({ timestamp: ts, nonce: '33333333333333333333333333333333', bodySha256: emptySha });
    const sig1 = computeHmac(FAKE_SECRET, canon1);
    const reqHost = `POST /v1/hello HTTP/1.1\r\nHost: localhost:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: 33333333333333333333333333333333\r\nX-HHAI-Signature: ${sig1}\r\nContent-Length: 0\r\n\r\n`;
    const res1 = await sendRawHttp(client1, reqHost);
    assert.match(res1, /^HTTP\/1\.1 400 Bad Request/);

    // 2. Origin present (T4)
    const client2 = net.connect({ port, host: '127.0.0.1' });
    const canon2 = buildCanonicalHelloRequest({ timestamp: ts, nonce: '44444444444444444444444444444444', bodySha256: emptySha });
    const sig2 = computeHmac(FAKE_SECRET, canon2);
    const reqOrigin = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nOrigin: http://evil.com\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: 44444444444444444444444444444444\r\nX-HHAI-Signature: ${sig2}\r\nContent-Length: 0\r\n\r\n`;
    const res2 = await sendRawHttp(client2, reqOrigin);
    assert.match(res2, /^HTTP\/1\.1 403 Forbidden/);

    // 3. Transfer-Encoding present (T5)
    const client3 = net.connect({ port, host: '127.0.0.1' });
    const canon3 = buildCanonicalHelloRequest({ timestamp: ts, nonce: '55555555555555555555555555555555', bodySha256: emptySha });
    const sig3 = computeHmac(FAKE_SECRET, canon3);
    const reqChunked = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nTransfer-Encoding: chunked\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: 55555555555555555555555555555555\r\nX-HHAI-Signature: ${sig3}\r\n\r\n0\r\n\r\n`;
    const res3 = await sendRawHttp(client3, reqChunked);
    assert.match(res3, /^HTTP\/1\.1 501/);
  } finally {
    await server.stop();
  }
});

test('server: rejects oversize entity body (> 65536 bytes) (T12)', { timeout: 5000 }, async () => {
  const { server } = createTestServer();
  const { port } = await server.start();

  try {
    const socket = net.connect({ port, host: '127.0.0.1' });
    const { sessionId, timestamp } = await performHello(socket, port, '00000000000000000000000000000001');

    // Create body with > 65536 bytes
    const largeObj = { channel_id: 'tg:test', pad: 'a'.repeat(66000) };
    const bodyBuf = Buffer.from(JSON.stringify(largeObj), 'utf-8');
    assert.ok(bodyBuf.length > 65536, 'Body must exceed MAX_BODY_BYTES');

    const canonReq = buildCanonicalSessionRequest({
      method: 'POST',
      path: '/v1/status',
      timestamp,
      nonce: '00000000000000000000000000000002',
      sessionId,
      bodySha256: computeSha256(bodyBuf),
    });
    const sig = computeHmac(FAKE_SECRET, canonReq);

    const reqOversize = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${timestamp}\r\nX-HHAI-Nonce: 00000000000000000000000000000002\r\nX-HHAI-Session-Id: ${sessionId}\r\nX-HHAI-Signature: ${sig}\r\nContent-Type: application/json\r\nContent-Length: ${bodyBuf.length}\r\n\r\n`;

    const fullPayload = Buffer.concat([Buffer.from(reqOversize, 'utf-8'), bodyBuf]);
    const res = await sendRawHttp(socket, fullPayload);
    assert.match(res, /^HTTP\/1\.1 413/);
  } finally {
    await server.stop();
  }
});

test('server: rejects stale or future timestamp beyond 30s freshness window (T6)', { timeout: 5000 }, async () => {
  let currentTime = 1000;
  const { server } = createTestServer({ nowSec: () => currentTime });
  const { port } = await server.start();

  try {
    // Stale timestamp (currentTime - 31)
    const staleTs = 1000 - 31;
    const emptySha = computeSha256(Buffer.alloc(0));
    const canonStale = buildCanonicalHelloRequest({ timestamp: staleTs, nonce: '00000000000000000000000000000003', bodySha256: emptySha });
    const sigStale = computeHmac(FAKE_SECRET, canonStale);

    const client1 = net.connect({ port, host: '127.0.0.1' });
    const reqStale = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${staleTs}\r\nX-HHAI-Nonce: 00000000000000000000000000000003\r\nX-HHAI-Signature: ${sigStale}\r\nContent-Length: 0\r\n\r\n`;
    const res1 = await sendRawHttp(client1, reqStale);
    assert.match(res1, /^HTTP\/1\.1 401 Unauthorized/);

    // Future timestamp (currentTime + 31)
    const futureTs = 1000 + 31;
    const canonFuture = buildCanonicalHelloRequest({ timestamp: futureTs, nonce: '00000000000000000000000000000004', bodySha256: emptySha });
    const sigFuture = computeHmac(FAKE_SECRET, canonFuture);

    const client2 = net.connect({ port, host: '127.0.0.1' });
    const reqFuture = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${futureTs}\r\nX-HHAI-Nonce: 00000000000000000000000000000004\r\nX-HHAI-Signature: ${sigFuture}\r\nContent-Length: 0\r\n\r\n`;
    const res2 = await sendRawHttp(client2, reqFuture);
    assert.match(res2, /^HTTP\/1\.1 401 Unauthorized/);
  } finally {
    await server.stop();
  }
});

test('server: invalid HMAC on HELLO fails 401 and does not poison replay cache (T7)', { timeout: 5000 }, async () => {
  const { server, replayCache } = createTestServer();
  const { port } = await server.start();

  try {
    const ts = Math.floor(Date.now() / 1000);
    const nonce = '00000000000000000000000000000005';
    const badSig = '00'.repeat(32);

    const client1 = net.connect({ port, host: '127.0.0.1' });
    const reqBad = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: ${nonce}\r\nX-HHAI-Signature: ${badSig}\r\nContent-Length: 0\r\n\r\n`;
    const res1 = await sendRawHttp(client1, reqBad);
    assert.match(res1, /^HTTP\/1\.1 401 Unauthorized/);

    // Nonce must NOT be poisoned into replay cache
    assert.equal(replayCache.helloCacheSize, 0);

    // Now send legitimate HELLO with same nonce, must succeed
    const emptySha = computeSha256(Buffer.alloc(0));
    const canonGood = buildCanonicalHelloRequest({ timestamp: ts, nonce, bodySha256: emptySha });
    const goodSig = computeHmac(FAKE_SECRET, canonGood);

    const client2 = net.connect({ port, host: '127.0.0.1' });
    const reqGood = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: ${nonce}\r\nX-HHAI-Signature: ${goodSig}\r\nContent-Length: 0\r\n\r\n`;
    const res2 = await sendRawHttp(client2, reqGood);
    assert.match(res2, /^HTTP\/1\.1 200 OK/);
    assert.equal(replayCache.helloCacheSize, 1);
  } finally {
    await server.stop();
  }
});

test('server: enforces session physical TCP socket binding (T9) and rejects cross-socket reuse', { timeout: 5000 }, async () => {
  const { server } = createTestServer();
  const { port } = await server.start();

  try {
    // Establish session on Socket A
    const socketA = net.connect({ port, host: '127.0.0.1' });
    const { sessionId, timestamp: ts } = await performHello(socketA, port, '00000000000000000000000000000006');

    // Attempt to use Session ID from Socket A on a DIFFERENT Socket B (T9)
    const socketB = net.connect({ port, host: '127.0.0.1' });
    const body = Buffer.from(JSON.stringify({ channel_id: 'tg:test' }), 'utf-8');
    const bodySha = computeSha256(body);
    const nonceSession = '00000000000000000000000000000007';
    const canonSession = buildCanonicalSessionRequest({
      method: 'POST',
      path: '/v1/status',
      timestamp: ts,
      nonce: nonceSession,
      sessionId,
      bodySha256: bodySha,
    });
    const sigSession = computeHmac(FAKE_SECRET, canonSession);

    const reqCrossSocket = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: ${nonceSession}\r\nX-HHAI-Session-Id: ${sessionId}\r\nX-HHAI-Signature: ${sigSession}\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\n\r\n${body.toString('utf-8')}`;

    const resB = await sendRawHttp(socketB, reqCrossSocket);
    assert.match(resB, /^HTTP\/1\.1 401 Unauthorized/, 'Cross-socket session reuse MUST be rejected');

    socketA.destroy();
    socketB.destroy();
  } finally {
    await server.stop();
  }
});

test('server: enforces exactly one business request per session (T10)', { timeout: 5000 }, async () => {
  const { server } = createTestServer();
  const { port } = await server.start();

  try {
    const socket = net.connect({ port, host: '127.0.0.1' });
    const { sessionId, timestamp: ts } = await performHello(socket, port, '00000000000000000000000000000008');

    // First business request on this socket
    const body1 = Buffer.from(JSON.stringify({ channel_id: 'tg:test' }), 'utf-8');
    const canonReq1 = buildCanonicalSessionRequest({
      method: 'POST',
      path: '/v1/status',
      timestamp: ts,
      nonce: '00000000000000000000000000000009',
      sessionId,
      bodySha256: computeSha256(body1),
    });
    const sigReq1 = computeHmac(FAKE_SECRET, canonReq1);

    const httpReq1 = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: 00000000000000000000000000000009\r\nX-HHAI-Session-Id: ${sessionId}\r\nX-HHAI-Signature: ${sigReq1}\r\nContent-Type: application/json\r\nContent-Length: ${body1.length}\r\n\r\n${body1.toString('utf-8')}`;

    const bizRes1 = await sendRawHttp(socket, httpReq1);
    assert.match(bizRes1, /^HTTP\/1\.1 200 OK/);

    // Second business request on same session (T10)
    const body2 = Buffer.from(JSON.stringify({ channel_id: 'tg:test' }), 'utf-8');
    const canonReq2 = buildCanonicalSessionRequest({
      method: 'POST',
      path: '/v1/status',
      timestamp: ts,
      nonce: '0000000000000000000000000000000a',
      sessionId,
      bodySha256: computeSha256(body2),
    });
    const sigReq2 = computeHmac(FAKE_SECRET, canonReq2);

    const httpReq2 = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: 0000000000000000000000000000000a\r\nX-HHAI-Session-Id: ${sessionId}\r\nX-HHAI-Signature: ${sigReq2}\r\nContent-Type: application/json\r\nContent-Length: ${body2.length}\r\n\r\n${body2.toString('utf-8')}`;

    const bizRes2 = await sendRawHttp(socket, httpReq2);
    assert.match(bizRes2, /^HTTP\/1\.1 403/, 'Second business request on same session MUST be rejected');

    socket.destroy();
  } finally {
    await server.stop();
  }
});

test('server: STOPPING gate returns 503 GATEWAY_STOPPING without executing dispatcher (T18)', { timeout: 5000 }, async () => {
  let dispatcherCalled = false;
  const { server } = createTestServer({
    dispatcher: {
      dispatch() {
        dispatcherCalled = true;
        return { status: 200, body: { ok: true } };
      },
    },
  });
  const { port } = await server.start();

  try {
    const socket = net.connect({ port, host: '127.0.0.1' });
    const { sessionId, timestamp: ts } = await performHello(socket, port, '0000000000000000000000000000000b');

    // Trigger STOPPING state
    server.isStopping = true;

    // Send business request
    const body = Buffer.from(JSON.stringify({ channel_id: 'tg:test' }), 'utf-8');
    const canonReq = buildCanonicalSessionRequest({
      method: 'POST',
      path: '/v1/status',
      timestamp: ts,
      nonce: '0000000000000000000000000000000c',
      sessionId,
      bodySha256: computeSha256(body),
    });
    const sigReq = computeHmac(FAKE_SECRET, canonReq);

    const httpReq = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: 0000000000000000000000000000000c\r\nX-HHAI-Session-Id: ${sessionId}\r\nX-HHAI-Signature: ${sigReq}\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\n\r\n${body.toString('utf-8')}`;

    const res = await sendRawHttp(socket, httpReq);
    assert.match(res, /^HTTP\/1\.1 503/);
    assert.match(res, /GATEWAY_STOPPING/);
    assert.equal(dispatcherCalled, false, 'Dispatcher MUST NOT be executed when server is in STOPPING state');

    socket.destroy();
  } finally {
    await server.stop();
  }
});

// =========================================================================
// R1 REPAIR TESTS: F3, F4, F5, F7
// =========================================================================

test('server: strict protocol grammar validation for nonce, signature, session ID (R1-F4)', { timeout: 5000 }, async () => {
  const { server } = createTestServer();
  const { port } = await server.start();

  try {
    const ts = Math.floor(Date.now() / 1000);
    const validNonce = '11111111111111111111111111111111';
    const validSig = 'aa'.repeat(32);

    // 1. Short nonce (< 32 chars) -> 400
    const client1 = net.connect({ port, host: '127.0.0.1' });
    const reqShortNonce = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: 12345\r\nX-HHAI-Signature: ${validSig}\r\nContent-Length: 0\r\n\r\n`;
    const res1 = await sendRawHttp(client1, reqShortNonce);
    assert.match(res1, /^HTTP\/1\.1 400/);

    // 2. Non-hex nonce (32 chars with invalid hex characters) -> 400
    const client2 = net.connect({ port, host: '127.0.0.1' });
    const reqNonHexNonce = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz\r\nX-HHAI-Signature: ${validSig}\r\nContent-Length: 0\r\n\r\n`;
    const res2 = await sendRawHttp(client2, reqNonHexNonce);
    assert.match(res2, /^HTTP\/1\.1 400/);

    // 3. Uppercase nonce (32 uppercase hex characters) -> 400
    const client3 = net.connect({ port, host: '127.0.0.1' });
    const reqUpperNonce = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\r\nX-HHAI-Signature: ${validSig}\r\nContent-Length: 0\r\n\r\n`;
    const res3 = await sendRawHttp(client3, reqUpperNonce);
    assert.match(res3, /^HTTP\/1\.1 400/);

    // 4. Uppercase signature (64 uppercase hex characters) -> 401
    const client4 = net.connect({ port, host: '127.0.0.1' });
    const reqUpperSig = `POST /v1/hello HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: ${validNonce}\r\nX-HHAI-Signature: ${'AA'.repeat(32)}\r\nContent-Length: 0\r\n\r\n`;
    const res4 = await sendRawHttp(client4, reqUpperSig);
    assert.match(res4, /^HTTP\/1\.1 401/);

    // 5. Malformed session ID on session endpoint (non-hex or wrong length) -> 400
    const client5 = net.connect({ port, host: '127.0.0.1' });
    const reqBadSession = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: ${validNonce}\r\nX-HHAI-Session-Id: not-a-valid-32-hex-session-id!\r\nX-HHAI-Signature: ${validSig}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}`;
    const res5 = await sendRawHttp(client5, reqBadSession);
    assert.match(res5, /^HTTP\/1\.1 400/);
  } finally {
    await server.stop();
  }
});

test('server: Content-Type validation rejects application/jsonevil and non-json types (R1-F7)', { timeout: 5000 }, async () => {
  const { server } = createTestServer();
  const { port } = await server.start();

  try {
    const socket = net.connect({ port, host: '127.0.0.1' });
    const { sessionId, timestamp: ts } = await performHello(socket, port, '11111111111111111111111111111112');

    const body = Buffer.from(JSON.stringify({ test: true }), 'utf-8');
    const canonReq = buildCanonicalSessionRequest({
      method: 'POST',
      path: '/v1/status',
      timestamp: ts,
      nonce: '22222222222222222222222222222221',
      sessionId,
      bodySha256: computeSha256(body),
    });
    const sig = computeHmac(FAKE_SECRET, canonReq);

    // 1. application/jsonevil MUST fail closed with 415
    const reqEvil = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: 22222222222222222222222222222221\r\nX-HHAI-Session-Id: ${sessionId}\r\nX-HHAI-Signature: ${sig}\r\nContent-Type: application/jsonevil\r\nContent-Length: ${body.length}\r\n\r\n${body.toString('utf-8')}`;

    const resEvil = await sendRawHttp(socket, reqEvil);
    assert.match(resEvil, /^HTTP\/1\.1 415/);

    socket.destroy();
  } finally {
    await server.stop();
  }
});

test('server: early and streaming MAX_BODY_BYTES enforcement (R1-F3)', { timeout: 5000 }, async () => {
  let dispatcherCalled = false;
  const { server } = createTestServer({
    dispatcher: {
      dispatch() {
        dispatcherCalled = true;
        return { status: 200, body: { ok: true } };
      },
    },
  });
  const { port } = await server.start();

  try {
    // 1. Declared Content-Length > 65536 fails before accumulating full body
    const socket1 = net.connect({ port, host: '127.0.0.1' });
    const { sessionId: sId1, timestamp: ts1 } = await performHello(socket1, port, '33333333333333333333333333333331');

    const headersEarly = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts1}\r\nX-HHAI-Nonce: 33333333333333333333333333333332\r\nX-HHAI-Session-Id: ${sId1}\r\nX-HHAI-Signature: ${'bb'.repeat(32)}\r\nContent-Type: application/json\r\nContent-Length: 70000\r\n\r\n`;

    // Send only headers, no body bytes yet
    const resEarly = await sendRawHttp(socket1, headersEarly);
    assert.match(resEarly, /^HTTP\/1\.1 413/, 'Declared Content-Length > 65536 must fail 413 immediately');
    assert.equal(dispatcherCalled, false, 'Dispatcher must NOT be called on early oversize rejection');
    socket1.destroy();

    // 2. Stream crossing 65536 fails closed immediately
    let failCode = null;
    const { EventEmitter } = require('node:events');
    const mockReq = new EventEmitter();
    mockReq.method = 'POST';
    mockReq.url = '/v1/status';
    mockReq.headers = {
      host: `127.0.0.1:${port}`,
      'x-hhai-version': '1',
      'x-hhai-timestamp': String(ts1),
      'x-hhai-nonce': '33333333333333333333333333333334',
      'x-hhai-session-id': sId1,
      'x-hhai-signature': 'bb'.repeat(32),
      'content-type': 'application/json',
      'content-length': '65536',
    };
    mockReq.rawHeaders = [
      'Host', `127.0.0.1:${port}`,
      'X-HHAI-Version', '1',
      'X-HHAI-Timestamp', String(ts1),
      'X-HHAI-Nonce', '33333333333333333333333333333334',
      'X-HHAI-Session-Id', sId1,
      'X-HHAI-Signature', 'bb'.repeat(32),
      'Content-Type', 'application/json',
      'Content-Length', '65536',
    ];
    mockReq.pause = () => {};
    const mockRes = {
      writeHead(code) { failCode = code; },
      end() {},
    };

    server._handleRequest(mockReq, mockRes);
    mockReq.emit('data', Buffer.alloc(40000));
    assert.equal(failCode, null, 'Must not fail before crossing 65536');
    mockReq.emit('data', Buffer.alloc(30000));
    assert.equal(failCode, 413, 'Stream crossing 65536 must fail closed with 413');
    assert.equal(dispatcherCalled, false);

    // 3. Exactly 65536 bytes remains within size boundary
    const socket3 = net.connect({ port, host: '127.0.0.1' });
    const { sessionId: sId3, timestamp: ts3 } = await performHello(socket3, port, '33333333333333333333333333333335');

    // Create a valid JSON body with total length exactly 65536 bytes
    const prefix = '{"pad":"';
    const suffix = '"}';
    const padLen = 65536 - prefix.length - suffix.length;
    const exactBody = Buffer.from(prefix + 'b'.repeat(padLen) + suffix, 'utf-8');
    assert.equal(exactBody.length, 65536);

    const nonceExact = '33333333333333333333333333333336';
    const canonExact = buildCanonicalSessionRequest({
      method: 'POST',
      path: '/v1/status',
      timestamp: ts3,
      nonce: nonceExact,
      sessionId: sId3,
      bodySha256: computeSha256(exactBody),
    });
    const sigExact = computeHmac(FAKE_SECRET, canonExact);

    const reqExact = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts3}\r\nX-HHAI-Nonce: ${nonceExact}\r\nX-HHAI-Session-Id: ${sId3}\r\nX-HHAI-Signature: ${sigExact}\r\nContent-Type: application/json\r\nContent-Length: 65536\r\n\r\n`;

    const resExact = await sendRawHttp(socket3, Buffer.concat([Buffer.from(reqExact, 'utf-8'), exactBody]));
    assert.match(resExact, /^HTTP\/1\.1 200/, 'Exact 65536 bytes body must be accepted');
    assert.equal(dispatcherCalled, true);

    socket3.destroy();
  } finally {
    await server.stop();
  }
});

test('server: invalid HMAC on SESSION request does NOT record nonce or poison replay cache (R1-F5)', { timeout: 5000 }, async () => {
  let dispatchCount = 0;
  const { server } = createTestServer({
    dispatcher: {
      dispatch() {
        dispatchCount++;
        return { status: 200, body: { ok: true } };
      },
    },
  });
  const { port } = await server.start();

  try {
    const socket = net.connect({ port, host: '127.0.0.1' });
    const { sessionId, timestamp: ts } = await performHello(socket, port, '44444444444444444444444444444441');

    const body = Buffer.from(JSON.stringify({ query: 'health' }), 'utf-8');
    const nonceN = '44444444444444444444444444444442';

    // 1. Send SESSION request with invalid HMAC
    const badSig = '00'.repeat(32);
    const reqBadSig = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: ${nonceN}\r\nX-HHAI-Session-Id: ${sessionId}\r\nX-HHAI-Signature: ${badSig}\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\n\r\n${body.toString('utf-8')}`;

    const resBad = await sendRawHttp(socket, reqBadSig);
    assert.match(resBad, /^HTTP\/1\.1 401/, 'Bad HMAC must return 401');
    assert.equal(dispatchCount, 0, 'No business dispatch on bad HMAC');

    // 2. Send valid authenticated SESSION request on same socket with SAME nonce N
    const canonGood = buildCanonicalSessionRequest({
      method: 'POST',
      path: '/v1/status',
      timestamp: ts,
      nonce: nonceN,
      sessionId,
      bodySha256: computeSha256(body),
    });
    const goodSig = computeHmac(FAKE_SECRET, canonGood);

    const reqGoodSig = `POST /v1/status HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nX-HHAI-Version: 1\r\nX-HHAI-Timestamp: ${ts}\r\nX-HHAI-Nonce: ${nonceN}\r\nX-HHAI-Session-Id: ${sessionId}\r\nX-HHAI-Signature: ${goodSig}\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\n\r\n${body.toString('utf-8')}`;

    const resGood = await sendRawHttp(socket, reqGoodSig);
    assert.match(resGood, /^HTTP\/1\.1 200/, 'Valid request using same nonce must succeed because invalid HMAC did not poison nonce');
    assert.equal(dispatchCount, 1, 'Dispatcher called exactly once for valid request');

    socket.destroy();
  } finally {
    await server.stop();
  }
});
