/**
 * runtime/channel-gateway/bin/local-api-client.js
 *
 * TG-MVP-11: Local API Client CLI Wrapper.
 *
 * Exit codes:
 * 0: authenticated 2xx business response
 * 1: internal local wrapper failure not otherwise classified
 * 2: locally detected caller/input error (unknown command, malformed JSON, etc.)
 * 3: protocol/authentication verification failure (bad HMAC, socket mismatch, impostor)
 * 4: transport / Gateway unavailable OR authenticated HTTP 503 code = GATEWAY_STOPPING
 * 5: all other completely authenticated non-2xx business responses
 */

'use strict';

const http = require('node:http');
const crypto = require('node:crypto');
const {
  CANONICAL_PORT,
  FRESHNESS_WINDOW_SEC,
  MAX_BODY_BYTES,
  computeSha256,
  buildCanonicalHelloRequest,
  buildCanonicalSessionRequest,
  buildCanonicalResponse,
  computeHmac,
  verifyHmac,
  parseRawSecurityHeaders,
} = require('../core/local-api-codec');
const { SecretRef } = require('../core/secret-provider');

const VALID_COMMANDS = new Set(['status', 'takeover', 'poll', 'heartbeat', 'reply']);

/**
 * Reads all bytes from a readable stream up to maxBytes.
 */
function readStream(stream, maxBytes = MAX_BODY_BYTES) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;

    stream.on('data', (chunk) => {
      total += chunk.length;
      if (total > maxBytes) {
        stream.pause();
        const err = new Error('INPUT_TOO_LARGE');
        err.code = 'INPUT_TOO_LARGE';
        reject(err);
        return;
      }
      chunks.push(chunk);
    });

    stream.on('end', () => {
      resolve(Buffer.concat(chunks));
    });

    stream.on('error', (err) => {
      reject(err);
    });
  });
}

/**
 * Performs a single HTTP request using keepAlive agent and resolves with { statusCode, headers, rawHeaders, body, socket }.
 */
function httpRequest(options, bodyBuffer) {
  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        resolve({
          statusCode: res.statusCode,
          headers: res.headers,
          rawHeaders: res.rawHeaders,
          body: Buffer.concat(chunks),
          socket: res.socket,
        });
      });
    });

    let assignedSocket = null;
    req.on('socket', (sock) => {
      assignedSocket = sock;
    });

    req.on('error', (err) => {
      reject(err);
    });

    if (bodyBuffer && bodyBuffer.length > 0) {
      req.write(bodyBuffer);
    }
    req.end();
  });
}

/**
 * Executes a client command against Local API.
 * Exposes injectable dependencies for deterministic unit testing.
 *
 * @param {string} command 'status' | 'takeover' | 'poll' | 'heartbeat' | 'reply'
 * @param {Buffer|string} stdinData Raw stdin bytes or string
 * @param {object} [deps] Injectable dependencies
 * @param {object} [deps.secretProvider] SecretProvider instance
 * @param {number} [deps.port=3003] Port to connect to
 * @param {() => number} [deps.nowSec] Clock
 * @param {Function} [deps.transport] Injectable request function (options, bodyBuf) => Promise<{ statusCode, headers, rawHeaders, body, socket }>
 * @param {object} [deps.stdout] Writable stdout
 * @param {object} [deps.stderr] Writable stderr
 * @returns {Promise<number>} Exit code
 */
async function runClient(command, stdinData, deps = {}) {
  const stdout = deps.stdout || process.stdout;
  const stderr = deps.stderr || process.stderr;
  const nowSec = deps.nowSec || (() => Math.floor(Date.now() / 1000));
  const port = deps.port !== undefined ? deps.port : CANONICAL_PORT;

  // 1. Input & command validation
  if (!command || !VALID_COMMANDS.has(command)) {
    stderr.write('INVALID_COMMAND\n');
    return 2;
  }

  let parsedInput;
  let bodyBuffer;
  try {
    if (typeof stdinData === 'string') {
      bodyBuffer = Buffer.from(stdinData, 'utf-8');
    } else if (Buffer.isBuffer(stdinData)) {
      bodyBuffer = stdinData;
    } else {
      stderr.write('INVALID_INPUT\n');
      return 2;
    }

    if (bodyBuffer.length > MAX_BODY_BYTES) {
      stderr.write('PAYLOAD_TOO_LARGE\n');
      return 2;
    }

    const text = bodyBuffer.toString('utf-8');
    if (text.trim().length === 0) {
      stderr.write('EMPTY_INPUT\n');
      return 2;
    }
    parsedInput = JSON.parse(text);
    if (typeof parsedInput !== 'object' || parsedInput === null || Array.isArray(parsedInput)) {
      stderr.write('MALFORMED_JSON_OBJECT\n');
      return 2;
    }
  } catch {
    stderr.write('MALFORMED_JSON\n');
    return 2;
  }

  // 2. Secret acquisition
  let secretBuf = null;

  try {
    let provider = deps.secretProvider;
    if (!provider) {
      const { createDefaultSecretProvider } = require('../core/secret-provider');
      provider = createDefaultSecretProvider();
    }
    const ref = SecretRef.localApiHmac();
    secretBuf = await provider.getSecret(ref);

    if (!secretBuf || !Buffer.isBuffer(secretBuf) || secretBuf.length === 0) {
      stderr.write('SECRET_UNAVAILABLE\n');
      return 1;
    }

    // 3. Setup KeepAlive Agent to guarantee same physical TCP socket
    const agent = deps.agent || new http.Agent({ keepAlive: true, maxSockets: 1 });
    const transport = deps.transport || httpRequest;

    // 4. Send HELLO Request
    const helloNonce = crypto.randomBytes(16).toString('hex');
    const helloTs = nowSec();
    const emptySha = computeSha256(Buffer.alloc(0));
    const canonHelloReq = buildCanonicalHelloRequest({
      timestamp: helloTs,
      nonce: helloNonce,
      bodySha256: emptySha,
    });
    const helloSig = computeHmac(secretBuf, canonHelloReq);

    let helloRes;
    try {
      helloRes = await transport(
        {
          hostname: '127.0.0.1',
          port,
          path: '/v1/hello',
          method: 'POST',
          agent,
          headers: {
            Host: `127.0.0.1:${port}`,
            'X-HHAI-Version': '1',
            'X-HHAI-Timestamp': String(helloTs),
            'X-HHAI-Nonce': helloNonce,
            'X-HHAI-Signature': helloSig,
            'Content-Length': '0',
          },
        },
        Buffer.alloc(0)
      );
    } catch {
      stderr.write('GATEWAY_UNAVAILABLE\n');
      return 4;
    }

    if (helloRes.statusCode !== 200) {
      stderr.write('HELLO_FAILED\n');
      return 3;
    }

    // 5. Verify HELLO Response
    const helloRawSec = parseRawSecurityHeaders(helloRes.rawHeaders || []);
    if (!helloRawSec.ok || !helloRawSec.headers) {
      stderr.write('INVALID_HELLO_RESPONSE_HEADERS\n');
      return 3;
    }

    const helloSec = helloRawSec.headers;
    const helloRespTs = parseInt(helloSec.timestamp || '0', 10);
    const sessionId = helloSec.sessionId;
    const helloRespSig = helloSec.signature;

    if (!sessionId || !/^[0-9a-f]{32}$/.test(sessionId)) {
      stderr.write('INVALID_SESSION_ID\n');
      return 3;
    }
    if (Math.abs(nowSec() - helloRespTs) > FRESHNESS_WINDOW_SEC) {
      stderr.write('STALE_HELLO_RESPONSE\n');
      return 3;
    }

    const canonHelloResp = buildCanonicalResponse({
      mode: 'HELLO',
      statusCode: 200,
      requestMethod: 'POST',
      requestPath: '/v1/hello',
      requestNonce: helloNonce,
      responseTimestamp: helloRespTs,
      sessionId,
      bodySha256: computeSha256(Buffer.alloc(0)),
    });

    const isHelloValid = verifyHmac(secretBuf, canonHelloResp, helloRespSig);
    if (!isHelloValid) {
      stderr.write('HELLO_SIGNATURE_MISMATCH\n');
      return 3;
    }

    const helloSocket = helloRes.socket;

    // 6. Send Business SESSION Request on same physical socket
    const sessionNonce = crypto.randomBytes(16).toString('hex');
    const sessionTs = nowSec();
    const endpointPath = `/v1/${command}`;
    const bodySha = computeSha256(bodyBuffer);

    const canonSessionReq = buildCanonicalSessionRequest({
      method: 'POST',
      path: endpointPath,
      timestamp: sessionTs,
      nonce: sessionNonce,
      sessionId,
      bodySha256: bodySha,
    });
    const sessionSig = computeHmac(secretBuf, canonSessionReq);

    let sessionRes;
    try {
      sessionRes = await transport(
        {
          hostname: '127.0.0.1',
          port,
          path: endpointPath,
          method: 'POST',
          agent,
          headers: {
            Host: `127.0.0.1:${port}`,
            'X-HHAI-Version': '1',
            'X-HHAI-Timestamp': String(sessionTs),
            'X-HHAI-Nonce': sessionNonce,
            'X-HHAI-Session-Id': sessionId,
            'X-HHAI-Signature': sessionSig,
            'Content-Type': 'application/json',
            'Content-Length': String(bodyBuffer.length),
          },
        },
        bodyBuffer
      );
    } catch {
      stderr.write('GATEWAY_UNAVAILABLE\n');
      return 4;
    }

    // Physical Socket Identity Verification (Mutation T16)
    if (!sessionRes.socket || sessionRes.socket !== helloSocket) {
      stderr.write('SOCKET_MISMATCH\n');
      return 3;
    }

    // 7. Complete Response Authentication BEFORE Writing to Stdout (Mutation T15)
    const sessionRawSec = parseRawSecurityHeaders(sessionRes.rawHeaders || []);
    if (!sessionRawSec.ok || !sessionRawSec.headers) {
      stderr.write('INVALID_RESPONSE_HEADERS\n');
      return 3;
    }

    const sessionSec = sessionRawSec.headers;
    const sessionRespTs = parseInt(sessionSec.timestamp || '0', 10);
    const respSessionId = sessionSec.sessionId;
    const respSig = sessionSec.signature;

    if (respSessionId !== sessionId) {
      stderr.write('SESSION_CORRELATION_MISMATCH\n');
      return 3;
    }
    if (Math.abs(nowSec() - sessionRespTs) > FRESHNESS_WINDOW_SEC) {
      stderr.write('STALE_RESPONSE_TIMESTAMP\n');
      return 3;
    }

    const respBodySha = computeSha256(sessionRes.body);
    const canonSessionResp = buildCanonicalResponse({
      mode: 'SESSION',
      statusCode: sessionRes.statusCode,
      requestMethod: 'POST',
      requestPath: endpointPath,
      requestNonce: sessionNonce,
      responseTimestamp: sessionRespTs,
      sessionId,
      bodySha256: respBodySha,
    });

    const isSessionValid = verifyHmac(secretBuf, canonSessionResp, respSig);
    if (!isSessionValid) {
      stderr.write('RESPONSE_SIGNATURE_MISMATCH\n');
      return 3;
    }

    // Only AFTER complete verification, process response
    const statusCode = sessionRes.statusCode;
    const rawResponseBody = sessionRes.body ? sessionRes.body.toString('utf-8') : '';

    if (statusCode >= 200 && statusCode < 300) {
      stdout.write(rawResponseBody + (rawResponseBody.endsWith('\n') ? '' : '\n'));
      return 0;
    }

    let parsedResp = null;
    try {
      parsedResp = JSON.parse(rawResponseBody);
    } catch {}

    if (statusCode === 503 && parsedResp && parsedResp.code === 'GATEWAY_STOPPING') {
      stdout.write(rawResponseBody + (rawResponseBody.endsWith('\n') ? '' : '\n'));
      return 4;
    }

    // All other authenticated non-2xx business responses
    stdout.write(rawResponseBody + (rawResponseBody.endsWith('\n') ? '' : '\n'));
    return 5;
  } catch (err) {
    stderr.write('INTERNAL_ERROR\n');
    return 1;
  } finally {
    // Consumer owns secretBuf and best-effort zeroizes it in finally
    if (secretBuf && Buffer.isBuffer(secretBuf)) {
      try {
        secretBuf.fill(0);
      } catch {}
    }
  }
}

// CLI entry point
if (require.main === module) {
  (async () => {
    const args = process.argv.slice(2);
    if (args.length !== 1) {
      process.stderr.write('Usage: node local-api-client.js <status|takeover|poll|heartbeat|reply>\n');
      process.exit(2);
    }

    const command = args[0];
    let stdinBytes;
    try {
      stdinBytes = await readStream(process.stdin, MAX_BODY_BYTES);
    } catch {
      process.stderr.write('INPUT_READ_FAILED\n');
      process.exit(2);
    }

    const exitCode = await runClient(command, stdinBytes);
    process.exit(exitCode);
  })();
}

module.exports = {
  runClient,
  readStream,
};
