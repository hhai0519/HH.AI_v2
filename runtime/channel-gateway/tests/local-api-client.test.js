/**
 * runtime/channel-gateway/tests/local-api-client.test.js
 *
 * Tests for Local API Client CLI Wrapper:
 * - Exit code mapping (0, 2, 3, 4, 5)
 * - Response verification before stdout
 * - Physical socket matching (T16)
 * - HMAC verification (T15)
 * - SecretProvider contract & consumer secret zeroization
 * - Order independence across invocations
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { runClient } = require('../bin/local-api-client');
const {
  computeSha256,
  buildCanonicalResponse,
  computeHmac,
} = require('../core/local-api-codec');

const FAKE_SECRET_SOURCE = Buffer.from(
  '00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff',
  'hex'
);
assert.equal(FAKE_SECRET_SOURCE.length, 32);

function createFakeSecretProvider() {
  const provider = {
    lastReturnedBuffer: null,
    callCount: 0,
    async getSecret(_ref) {
      provider.callCount += 1;
      const fresh = Buffer.from(FAKE_SECRET_SOURCE);
      provider.lastReturnedBuffer = fresh;
      return fresh;
    },
  };
  return provider;
}

function createMockStream() {
  let content = '';
  return {
    write(chunk) {
      content += chunk;
    },
    get content() {
      return content;
    },
    clear() {
      content = '';
    },
  };
}

test('client: input validation errors return exit code 2 (unknown command, malformed JSON)', { timeout: 5000 }, async () => {
  const stdout = createMockStream();
  const stderr = createMockStream();
  const secretProvider = createFakeSecretProvider();

  // Unknown command
  const code1 = await runClient('invalid-cmd', '{}', { stdout, stderr, secretProvider });
  assert.equal(code1, 2);
  assert.equal(stdout.content, '');

  // Malformed JSON
  const code2 = await runClient('status', '{bad json}', { stdout, stderr, secretProvider });
  assert.equal(code2, 2);
  assert.equal(stdout.content, '');

  // Non-object JSON (array)
  const code3 = await runClient('status', '[]', { stdout, stderr, secretProvider });
  assert.equal(code3, 2);
  assert.equal(stdout.content, '');

  // Input validation returns before secret acquisition
  assert.equal(secretProvider.callCount, 0);
  assert.equal(FAKE_SECRET_SOURCE.length, 32);
});

test('client: returns exit 0 on authenticated 2xx response with verified output in stdout', { timeout: 5000 }, async () => {
  const stdout = createMockStream();
  const stderr = createMockStream();
  const secretProvider = createFakeSecretProvider();
  const sharedSocket = { id: 'sock-1' };
  const sessionId = '0123456789abcdef0123456789abcdef';
  let now = 1000;

  const mockTransport = async (options, bodyBuf) => {
    // Independent mock server signing buffer
    const serverSecret = Buffer.from(FAKE_SECRET_SOURCE);
    if (options.path === '/v1/hello') {
      const canonHello = buildCanonicalResponse({
        mode: 'HELLO',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: '/v1/hello',
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(Buffer.alloc(0)),
      });
      const sig = computeHmac(serverSecret, canonHello);
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', sig,
          'Content-Length', '0',
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      };
    } else {
      const respObj = { ok: true, code: 'OK', channel_id: 'tg:test' };
      const respBuf = Buffer.from(JSON.stringify(respObj), 'utf-8');
      const canonSession = buildCanonicalResponse({
        mode: 'SESSION',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: options.path,
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(respBuf),
      });
      const sig = computeHmac(serverSecret, canonSession);
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', sig,
          'Content-Type', 'application/json',
          'Content-Length', String(respBuf.length),
        ],
        body: respBuf,
        socket: sharedSocket,
      };
    }
  };

  const code = await runClient('status', JSON.stringify({ channel_id: 'tg:test' }), {
    secretProvider,
    transport: mockTransport,
    stdout,
    stderr,
    nowSec: () => now,
  });

  assert.equal(code, 0);
  assert.match(stdout.content, /"ok":true/);

  // Verify consumer zeroization of returned buffer
  assert.ok(secretProvider.lastReturnedBuffer !== null);
  assert.ok(
    secretProvider.lastReturnedBuffer.every((b) => b === 0),
    'consumer-owned secret buffer must be zeroized in finally'
  );
  assert.ok(!FAKE_SECRET_SOURCE.every((b) => b === 0), 'FAKE_SECRET_SOURCE must remain immutable');
});

test('client: invalid response HMAC fails closed with exit 3 and stdout stays completely empty (T15)', { timeout: 5000 }, async () => {
  const stdout = createMockStream();
  const stderr = createMockStream();
  const secretProvider = createFakeSecretProvider();
  const sharedSocket = { id: 'sock-1' };
  const sessionId = '0123456789abcdef0123456789abcdef';
  let now = 1000;

  const mockTransport = async (options) => {
    const serverSecret = Buffer.from(FAKE_SECRET_SOURCE);
    if (options.path === '/v1/hello') {
      const canonHello = buildCanonicalResponse({
        mode: 'HELLO',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: '/v1/hello',
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(Buffer.alloc(0)),
      });
      const sig = computeHmac(serverSecret, canonHello);
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', sig,
          'Content-Length', '0',
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      };
    } else {
      // Impostor server with bad response HMAC
      const respObj = { ok: true, secret_leaked: 'bad' };
      const respBuf = Buffer.from(JSON.stringify(respObj), 'utf-8');
      const badSig = '00'.repeat(32);
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', badSig,
          'Content-Type', 'application/json',
          'Content-Length', String(respBuf.length),
        ],
        body: respBuf,
        socket: sharedSocket,
      };
    }
  };

  const code = await runClient('status', JSON.stringify({ channel_id: 'tg:test' }), {
    secretProvider,
    transport: mockTransport,
    stdout,
    stderr,
    nowSec: () => now,
  });

  assert.equal(code, 3);
  assert.equal(stdout.content, '', 'stdout MUST stay completely empty on verification failure (T15)');
  assert.ok(secretProvider.lastReturnedBuffer.every((b) => b === 0));
});

test('client: forced physical socket switch fails closed with exit 3 and empty stdout (T16)', { timeout: 5000 }, async () => {
  const stdout = createMockStream();
  const stderr = createMockStream();
  const secretProvider = createFakeSecretProvider();
  const socketA = { id: 'sock-A' };
  const socketB = { id: 'sock-B' };
  const sessionId = '0123456789abcdef0123456789abcdef';
  let now = 1000;

  const mockTransport = async (options) => {
    const serverSecret = Buffer.from(FAKE_SECRET_SOURCE);
    if (options.path === '/v1/hello') {
      const canonHello = buildCanonicalResponse({
        mode: 'HELLO',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: '/v1/hello',
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(Buffer.alloc(0)),
      });
      const sig = computeHmac(serverSecret, canonHello);
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', sig,
          'Content-Length', '0',
        ],
        body: Buffer.alloc(0),
        socket: socketA, // HELLO on Socket A
      };
    } else {
      const respObj = { ok: true };
      const respBuf = Buffer.from(JSON.stringify(respObj), 'utf-8');
      const canonSession = buildCanonicalResponse({
        mode: 'SESSION',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: options.path,
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(respBuf),
      });
      const sig = computeHmac(serverSecret, canonSession);
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', sig,
          'Content-Type', 'application/json',
          'Content-Length', String(respBuf.length),
        ],
        body: respBuf,
        socket: socketB, // FORCED SWITCH to Socket B (T16)
      };
    }
  };

  const code = await runClient('status', JSON.stringify({ channel_id: 'tg:test' }), {
    secretProvider,
    transport: mockTransport,
    stdout,
    stderr,
    nowSec: () => now,
  });

  assert.equal(code, 3);
  assert.equal(stdout.content, '', 'stdout MUST stay completely empty on socket mismatch');
  assert.ok(secretProvider.lastReturnedBuffer.every((b) => b === 0));
});

test('client: returns exit 4 on transport unavailable or 503 GATEWAY_STOPPING', { timeout: 5000 }, async () => {
  const stdout = createMockStream();
  const stderr = createMockStream();
  const secretProvider = createFakeSecretProvider();

  // Transport unavailable (e.g. ECONNREFUSED)
  const codeUnavail = await runClient('status', JSON.stringify({ channel_id: 'tg:test' }), {
    secretProvider,
    transport: async () => {
      throw new Error('ECONNREFUSED');
    },
    stdout,
    stderr,
  });
  assert.equal(codeUnavail, 4);
  assert.ok(secretProvider.lastReturnedBuffer.every((b) => b === 0));

  // Authenticated 503 GATEWAY_STOPPING
  const secretProviderStopping = createFakeSecretProvider();
  const sharedSocket = { id: 'sock-1' };
  const sessionId = '0123456789abcdef0123456789abcdef';
  let now = 1000;

  const mockTransportStopping = async (options) => {
    const serverSecret = Buffer.from(FAKE_SECRET_SOURCE);
    if (options.path === '/v1/hello') {
      const canonHello = buildCanonicalResponse({
        mode: 'HELLO',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: '/v1/hello',
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(Buffer.alloc(0)),
      });
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', computeHmac(serverSecret, canonHello),
          'Content-Length', '0',
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      };
    } else {
      const respObj = { ok: false, code: 'GATEWAY_STOPPING' };
      const respBuf = Buffer.from(JSON.stringify(respObj), 'utf-8');
      const canonSession = buildCanonicalResponse({
        mode: 'SESSION',
        statusCode: 503,
        requestMethod: 'POST',
        requestPath: options.path,
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(respBuf),
      });
      return {
        statusCode: 503,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', computeHmac(serverSecret, canonSession),
          'Content-Type', 'application/json',
          'Content-Length', String(respBuf.length),
        ],
        body: respBuf,
        socket: sharedSocket,
      };
    }
  };

  const codeStopping = await runClient('status', JSON.stringify({ channel_id: 'tg:test' }), {
    secretProvider: secretProviderStopping,
    transport: mockTransportStopping,
    stdout,
    stderr,
    nowSec: () => now,
  });
  assert.equal(codeStopping, 4);
  assert.ok(secretProviderStopping.lastReturnedBuffer.every((b) => b === 0));
});

test('client: returns exit 5 on authenticated non-2xx business response', { timeout: 5000 }, async () => {
  const stdout = createMockStream();
  const stderr = createMockStream();
  const secretProvider = createFakeSecretProvider();
  const sharedSocket = { id: 'sock-1' };
  const sessionId = '0123456789abcdef0123456789abcdef';
  let now = 1000;

  const mockTransport404 = async (options) => {
    const serverSecret = Buffer.from(FAKE_SECRET_SOURCE);
    if (options.path === '/v1/hello') {
      const canonHello = buildCanonicalResponse({
        mode: 'HELLO',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: '/v1/hello',
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(Buffer.alloc(0)),
      });
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', computeHmac(serverSecret, canonHello),
          'Content-Length', '0',
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      };
    } else {
      const respObj = { ok: false, code: 'CHANNEL_NOT_FOUND' };
      const respBuf = Buffer.from(JSON.stringify(respObj), 'utf-8');
      const canonSession = buildCanonicalResponse({
        mode: 'SESSION',
        statusCode: 404,
        requestMethod: 'POST',
        requestPath: options.path,
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(respBuf),
      });
      return {
        statusCode: 404,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', computeHmac(serverSecret, canonSession),
          'Content-Type', 'application/json',
          'Content-Length', String(respBuf.length),
        ],
        body: respBuf,
        socket: sharedSocket,
      };
    }
  };

  const code = await runClient('status', JSON.stringify({ channel_id: 'tg:test' }), {
    secretProvider,
    transport: mockTransport404,
    stdout,
    stderr,
    nowSec: () => now,
  });
  assert.equal(code, 5);
  assert.match(stdout.content, /"code":"CHANNEL_NOT_FOUND"/);
  assert.ok(secretProvider.lastReturnedBuffer.every((b) => b === 0));
});

test('client: order independence and provider secret isolation across sequential calls', { timeout: 5000 }, async () => {
  const secretProvider = createFakeSecretProvider();
  const sharedSocket = { id: 'sock-1' };
  const sessionId = '0123456789abcdef0123456789abcdef';
  let now = 1000;

  const mockTransport = async (options) => {
    const serverSecret = Buffer.from(FAKE_SECRET_SOURCE);
    if (options.path === '/v1/hello') {
      const canonHello = buildCanonicalResponse({
        mode: 'HELLO',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: '/v1/hello',
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(Buffer.alloc(0)),
      });
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', computeHmac(serverSecret, canonHello),
          'Content-Length', '0',
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      };
    } else {
      const respObj = { ok: true, code: 'OK' };
      const respBuf = Buffer.from(JSON.stringify(respObj), 'utf-8');
      const canonSession = buildCanonicalResponse({
        mode: 'SESSION',
        statusCode: 200,
        requestMethod: 'POST',
        requestPath: options.path,
        requestNonce: options.headers['X-HHAI-Nonce'],
        responseTimestamp: now,
        sessionId,
        bodySha256: computeSha256(respBuf),
      });
      return {
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', sessionId,
          'X-HHAI-Signature', computeHmac(serverSecret, canonSession),
          'Content-Type', 'application/json',
          'Content-Length', String(respBuf.length),
        ],
        body: respBuf,
        socket: sharedSocket,
      };
    }
  };

  // Call 1
  const out1 = createMockStream();
  const err1 = createMockStream();
  const c1 = await runClient('status', JSON.stringify({ channel_id: 'tg:1' }), {
    secretProvider,
    transport: mockTransport,
    stdout: out1,
    stderr: err1,
    nowSec: () => now,
  });
  assert.equal(c1, 0);
  const buf1 = secretProvider.lastReturnedBuffer;
  assert.ok(buf1.every((b) => b === 0));

  // Call 2: next call receives fresh buffer, call 1 zeroization did not affect call 2 or source
  const out2 = createMockStream();
  const err2 = createMockStream();
  const c2 = await runClient('status', JSON.stringify({ channel_id: 'tg:2' }), {
    secretProvider,
    transport: mockTransport,
    stdout: out2,
    stderr: err2,
    nowSec: () => now,
  });
  assert.equal(c2, 0);
  const buf2 = secretProvider.lastReturnedBuffer;
  assert.ok(buf2.every((b) => b === 0));
  assert.notEqual(buf1, buf2, 'Each provider invocation must return an independent Buffer instance');
  assert.equal(FAKE_SECRET_SOURCE.length, 32);
  assert.ok(!FAKE_SECRET_SOURCE.every((b) => b === 0), 'FAKE_SECRET_SOURCE remains immutable');
});

test('client: default provider path references concrete WindowsCredentialManagerSecretProvider contract (R1-F2)', () => {
  const { WindowsCredentialManagerSecretProvider: ExportedProvider } = require('../bin/local-api-client');
  const { WindowsCredentialManagerSecretProvider: ActualProvider } = require('../core/windows-credential-manager-provider');
  const { SecretProvider } = require('../core/secret-provider');

  assert.strictEqual(ExportedProvider, ActualProvider);
  assert.strictEqual(ActualProvider.prototype instanceof SecretProvider, true);

  // Default provider instantiated when deps.secretProvider is not supplied
  let instantiated = false;
  class SpyProvider extends SecretProvider {
    constructor() {
      super();
      instantiated = true;
    }
    async getSecret() {
      return Buffer.from(FAKE_SECRET_SOURCE);
    }
  }

  const stdout = createMockStream();
  const stderr = createMockStream();
  runClient('status', '{}', {
    SecretProviderClass: SpyProvider,
    stdout,
    stderr,
    transport: async () => ({ statusCode: 400 }),
  });
  assert.strictEqual(instantiated, true);
});

test('client: validates HELLO and SESSION response protocol headers and rejects invalid formats with exit 3 (R1-F6)', async () => {
  const secretProvider = createFakeSecretProvider();
  const sharedSocket = { id: 'sock-proto' };
  const validSessionId = '0123456789abcdef0123456789abcdef';
  const now = 1000;

  // 1. HELLO response with invalid version
  {
    const stdout = createMockStream();
    const stderr = createMockStream();
    const code = await runClient('status', '{}', {
      secretProvider,
      stdout,
      stderr,
      nowSec: () => now,
      transport: async () => ({
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '2',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', validSessionId,
          'X-HHAI-Signature', 'aa'.repeat(32),
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      }),
    });
    assert.strictEqual(code, 3);
    assert.strictEqual(stdout.content, '');
    assert.match(stderr.content, /INVALID_HELLO_VERSION/);
  }

  // 2. HELLO response with invalid timestamp syntax
  {
    const stdout = createMockStream();
    const stderr = createMockStream();
    const code = await runClient('status', '{}', {
      secretProvider,
      stdout,
      stderr,
      nowSec: () => now,
      transport: async () => ({
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', 'not-a-number',
          'X-HHAI-Session-Id', validSessionId,
          'X-HHAI-Signature', 'aa'.repeat(32),
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      }),
    });
    assert.strictEqual(code, 3);
    assert.strictEqual(stdout.content, '');
    assert.match(stderr.content, /INVALID_HELLO_TIMESTAMP/);
  }

  // 3. HELLO response with invalid session ID format (not 32 hex)
  {
    const stdout = createMockStream();
    const stderr = createMockStream();
    const code = await runClient('status', '{}', {
      secretProvider,
      stdout,
      stderr,
      nowSec: () => now,
      transport: async () => ({
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', 'not-valid-session-id',
          'X-HHAI-Signature', 'aa'.repeat(32),
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      }),
    });
    assert.strictEqual(code, 3);
    assert.strictEqual(stdout.content, '');
    assert.match(stderr.content, /INVALID_SESSION_ID/);
  }

  // 4. HELLO response with uppercase signature (not 64 lowercase hex)
  {
    const stdout = createMockStream();
    const stderr = createMockStream();
    const code = await runClient('status', '{}', {
      secretProvider,
      stdout,
      stderr,
      nowSec: () => now,
      transport: async () => ({
        statusCode: 200,
        rawHeaders: [
          'X-HHAI-Version', '1',
          'X-HHAI-Timestamp', String(now),
          'X-HHAI-Session-Id', validSessionId,
          'X-HHAI-Signature', 'AA'.repeat(32),
        ],
        body: Buffer.alloc(0),
        socket: sharedSocket,
      }),
    });
    assert.strictEqual(code, 3);
    assert.strictEqual(stdout.content, '');
    assert.match(stderr.content, /INVALID_HELLO_SIGNATURE/);
  }

  // 5. SESSION response with invalid version
  {
    const serverSecret = Buffer.from(FAKE_SECRET_SOURCE);
    const stdout = createMockStream();
    const stderr = createMockStream();
    const code = await runClient('status', '{}', {
      secretProvider,
      stdout,
      stderr,
      nowSec: () => now,
      transport: async (options) => {
        if (options.path === '/v1/hello') {
          const canonHello = buildCanonicalResponse({
            mode: 'HELLO',
            statusCode: 200,
            requestMethod: 'POST',
            requestPath: '/v1/hello',
            requestNonce: options.headers['X-HHAI-Nonce'],
            responseTimestamp: now,
            sessionId: validSessionId,
            bodySha256: computeSha256(Buffer.alloc(0)),
          });
          return {
            statusCode: 200,
            rawHeaders: [
              'X-HHAI-Version', '1',
              'X-HHAI-Timestamp', String(now),
              'X-HHAI-Session-Id', validSessionId,
              'X-HHAI-Signature', computeHmac(serverSecret, canonHello),
            ],
            body: Buffer.alloc(0),
            socket: sharedSocket,
          };
        } else {
          return {
            statusCode: 200,
            rawHeaders: [
              'X-HHAI-Version', '2',
              'X-HHAI-Timestamp', String(now),
              'X-HHAI-Session-Id', validSessionId,
              'X-HHAI-Signature', 'aa'.repeat(32),
            ],
            body: Buffer.from('{"ok":true}'),
            socket: sharedSocket,
          };
        }
      },
    });
    assert.strictEqual(code, 3);
    assert.strictEqual(stdout.content, '');
    assert.match(stderr.content, /INVALID_RESPONSE_VERSION/);
  }

  // 6. SESSION response with uppercase signature
  {
    const serverSecret = Buffer.from(FAKE_SECRET_SOURCE);
    const stdout = createMockStream();
    const stderr = createMockStream();
    const code = await runClient('status', '{}', {
      secretProvider,
      stdout,
      stderr,
      nowSec: () => now,
      transport: async (options) => {
        if (options.path === '/v1/hello') {
          const canonHello = buildCanonicalResponse({
            mode: 'HELLO',
            statusCode: 200,
            requestMethod: 'POST',
            requestPath: '/v1/hello',
            requestNonce: options.headers['X-HHAI-Nonce'],
            responseTimestamp: now,
            sessionId: validSessionId,
            bodySha256: computeSha256(Buffer.alloc(0)),
          });
          return {
            statusCode: 200,
            rawHeaders: [
              'X-HHAI-Version', '1',
              'X-HHAI-Timestamp', String(now),
              'X-HHAI-Session-Id', validSessionId,
              'X-HHAI-Signature', computeHmac(serverSecret, canonHello),
            ],
            body: Buffer.alloc(0),
            socket: sharedSocket,
          };
        } else {
          return {
            statusCode: 200,
            rawHeaders: [
              'X-HHAI-Version', '1',
              'X-HHAI-Timestamp', String(now),
              'X-HHAI-Session-Id', validSessionId,
              'X-HHAI-Signature', 'AA'.repeat(32),
            ],
            body: Buffer.from('{"ok":true}'),
            socket: sharedSocket,
          };
        }
      },
    });
    assert.strictEqual(code, 3);
    assert.strictEqual(stdout.content, '');
    assert.match(stderr.content, /INVALID_RESPONSE_SIGNATURE/);
  }
});
