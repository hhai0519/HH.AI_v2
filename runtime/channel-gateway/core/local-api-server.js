/**
 * runtime/channel-gateway/core/local-api-server.js
 *
 * TG-MVP-11: Local API HTTP Server with Loopback Binding, Header/Framing Bounds & Dual-Phase HMAC Security Pipeline.
 */

'use strict';

const http = require('node:http');
const crypto = require('node:crypto');
const {
  CANONICAL_PORT,
  FRESHNESS_WINDOW_SEC,
  MAX_BODY_BYTES,
  MAX_HEADER_BYTES,
  HEADERS_TIMEOUT_MS,
  REQUEST_TIMEOUT_MS,
  CONNECTIONS_CHECKING_INTERVAL_MS,
  KEEP_ALIVE_TIMEOUT_MS,
  SOCKET_IDLE_TIMEOUT_MS,
  MAX_CONNECTIONS,
  MAX_REQUESTS_PER_SOCKET,
  SHUTDOWN_DRAIN_MS,
  computeSha256,
  buildCanonicalHelloRequest,
  buildCanonicalSessionRequest,
  buildCanonicalResponse,
  computeHmac,
  verifyHmac,
  parseRawSecurityHeaders,
  NONCE_REGEX,
  SIGNATURE_REGEX,
  SESSION_ID_REGEX,
  isValidNonce,
  isValidSignature,
  isValidSessionId,
} = require('./local-api-codec');
const { LocalApiReplayCache } = require('./local-api-replay-cache');

class LocalApiServer {
  /**
   * @param {object} options
   * @param {Buffer} options.secret Dedicated Local API HMAC secret buffer
   * @param {object} options.dispatcher LocalApiDispatcher instance
   * @param {LocalApiReplayCache} [options.replayCache] Replay cache instance
   * @param {number} [options.port=3003] Port to bind (3003 in production; 0 in explicit test mode)
   * @param {boolean} [options.allowTestPort=false] Whether non-canonical port (e.g. 0) is allowed
   * @param {() => number} [options.nowSec] Injectable clock function
   */
  constructor(options) {
    if (!options || !options.secret || !Buffer.isBuffer(options.secret)) {
      throw new Error('LocalApiServer requires a dedicated secret Buffer');
    }
    if (!options.dispatcher) {
      throw new Error('LocalApiServer requires a dispatcher');
    }

    const requestedPort = options.port !== undefined ? options.port : CANONICAL_PORT;
    if (requestedPort !== CANONICAL_PORT && !options.allowTestPort) {
      throw new Error(`Production port must be ${CANONICAL_PORT}; fallback port forbidden`);
    }

    this.secret = options.secret;
    this.dispatcher = options.dispatcher;
    this.replayCache = options.replayCache || new LocalApiReplayCache();
    this.targetPort = requestedPort;
    this.allowTestPort = Boolean(options.allowTestPort);
    this.nowSec = options.nowSec || (() => Math.floor(Date.now() / 1000));

    this.effectivePort = null;
    this.isStopping = false;
    this.server = null;
    this.trackedSockets = new Set();
  }

  /**
   * Starts HTTP listener bound strictly to 127.0.0.1.
   *
   * @returns {Promise<{ port: number }>}
   */
  start() {
    return new Promise((resolve, reject) => {
      this.server = http.createServer({
        maxHeaderSize: MAX_HEADER_BYTES,
        requireHostHeader: true,
        insecureHTTPParser: false,
        headersTimeout: HEADERS_TIMEOUT_MS,
        requestTimeout: REQUEST_TIMEOUT_MS,
        connectionsCheckingInterval: CONNECTIONS_CHECKING_INTERVAL_MS,
        keepAliveTimeout: KEEP_ALIVE_TIMEOUT_MS,
        maxRequestsPerSocket: MAX_REQUESTS_PER_SOCKET,
      });

      this.server.maxConnections = MAX_CONNECTIONS;

      this.server.on('connection', (socket) => {
        socket.setTimeout(SOCKET_IDLE_TIMEOUT_MS);
        socket.on('timeout', () => {
          socket.destroy();
        });

        this.trackedSockets.add(socket);
        socket.on('close', () => {
          if (socket._hhaiSessionId) {
            this.replayCache.clearSession(socket._hhaiSessionId);
          }
          this.trackedSockets.delete(socket);
        });
      });

      this.server.on('request', (req, res) => {
        this._handleRequest(req, res);
      });

      this.server.on('error', (err) => {
        reject(err);
      });

      // Bind strictly to loopback IPv4 127.0.0.1
      this.server.listen(this.targetPort, '127.0.0.1', () => {
        const addr = this.server.address();
        this.effectivePort = typeof addr === 'object' && addr !== null ? addr.port : this.targetPort;
        resolve({ port: this.effectivePort });
      });
    });
  }

  _failClosed(req, res, statusCode, closeConnection = true) {
    try {
      const headers = { 'Content-Length': '0' };
      if (closeConnection) {
        headers.Connection = 'close';
      }
      res.writeHead(statusCode, headers);
      res.end();
    } catch {
      if (req && req.socket) {
        try { req.socket.destroy(); } catch {}
      }
    }
  }

  /**
   * Main request handler implementing the complete security and authentication pipeline.
   */
  _handleRequest(req, res) {
    // 1. Method check: only POST is supported
    if (req.method !== 'POST') {
      return this._failClosed(req, res, 405);
    }

    // 2. Reject Transfer-Encoding (Framing safety)
    if (req.headers['transfer-encoding'] !== undefined) {
      return this._failClosed(req, res, 501);
    }

    // 3. Reject Origin (No CORS, no browser cross-origin requests)
    if (req.headers['origin'] !== undefined) {
      return this._failClosed(req, res, 403);
    }

    // 4. Exact Host header validation: 127.0.0.1:<effective-port>
    const expectedHost = `127.0.0.1:${this.effectivePort}`;
    if (req.headers['host'] !== expectedHost) {
      return this._failClosed(req, res, 400);
    }

    // 5. Path validation: origin-form path, no query string, no scheme
    const url = req.url || '';
    if (url.includes('?') || url.includes('#')) {
      return this._failClosed(req, res, 400);
    }

    const ALLOWED_PATHS = new Set([
      '/v1/hello',
      '/v1/status',
      '/v1/takeover',
      '/v1/poll',
      '/v1/heartbeat',
      '/v1/reply',
    ]);
    if (!ALLOWED_PATHS.has(url)) {
      return this._failClosed(req, res, 404);
    }

    // 6. Security headers duplicate validation from rawHeaders
    const parsedHeadersResult = parseRawSecurityHeaders(req.rawHeaders || []);
    if (!parsedHeadersResult.ok) {
      return this._failClosed(req, res, 400);
    }

    const secHeaders = parsedHeadersResult.headers;

    // 7. Protocol Version verification
    if (secHeaders.version !== '1') {
      return this._failClosed(req, res, 400);
    }

    // 8. Timestamp syntax & freshness verification
    const tsStr = secHeaders.timestamp;
    if (!tsStr || !/^[0-9]+$/.test(tsStr)) {
      return this._failClosed(req, res, 400);
    }
    const reqTs = parseInt(tsStr, 10);
    const now = this.nowSec();
    if (Math.abs(now - reqTs) > FRESHNESS_WINDOW_SEC) {
      return this._failClosed(req, res, 401);
    }

    // 9. Nonce syntax: exactly 32 lowercase hex ASCII characters
    const nonce = secHeaders.nonce;
    if (!nonce || !isValidNonce(nonce)) {
      return this._failClosed(req, res, 400);
    }

    // 10. Signature syntax: exactly 64 lowercase hex ASCII characters
    const signature = secHeaders.signature;
    if (!signature || !isValidSignature(signature)) {
      return this._failClosed(req, res, 401);
    }

    // 11. Session ID syntax check for non-hello endpoints
    const sessionId = secHeaders.sessionId;
    if (url !== '/v1/hello') {
      if (!sessionId || !isValidSessionId(sessionId)) {
        return this._failClosed(req, res, 400);
      }
    }

    // Framing and Content-Length check
    const clHeader = req.headers['content-length'];
    let expectedBytes = 0;
    if (url === '/v1/hello') {
      if (clHeader !== '0') {
        return this._failClosed(req, res, 400);
      }
    } else {
      if (clHeader === undefined || !/^[0-9]+$/.test(clHeader)) {
        return this._failClosed(req, res, 400);
      }
      expectedBytes = parseInt(clHeader, 10);
      if (expectedBytes > MAX_BODY_BYTES) {
        return this._failClosed(req, res, 413);
      }
      const ct = (req.headers['content-type'] || '').trim().toLowerCase();
      if (ct !== 'application/json') {
        return this._failClosed(req, res, 415);
      }
    }

    // Read and buffer body with running byte count bound (R1-F3)
    let receivedBytes = 0;
    const chunks = [];
    let aborted = false;

    req.on('data', (chunk) => {
      if (aborted) return;
      receivedBytes += chunk.length;
      if (receivedBytes > MAX_BODY_BYTES) {
        aborted = true;
        try { req.pause(); } catch {}
        this._failClosed(req, res, 413, true);
        return;
      }
      chunks.push(chunk);
    });

    req.on('end', () => {
      if (aborted) return;
      const rawBody = Buffer.concat(chunks);

      if (url === '/v1/hello' && rawBody.length !== 0) {
        return this._failClosed(req, res, 400);
      }
      if (url !== '/v1/hello' && rawBody.length !== expectedBytes) {
        return this._failClosed(req, res, 400);
      }

      if (url === '/v1/hello') {
        this._processHello(req, res, { nonce, timestamp: reqTs, signature });
      } else {
        this._processSession(req, res, {
          path: url,
          nonce,
          timestamp: reqTs,
          sessionId,
          signature,
          rawBody,
        });
      }
    });
  }

  /**
   * Processes POST /v1/hello.
   */
  _processHello(req, res, { nonce, timestamp, signature }) {
    // 1. HELLO request MUST NOT carry X-HHAI-Session-Id
    const parseRes = parseRawSecurityHeaders(req.rawHeaders || []);
    if (parseRes.headers && parseRes.headers.sessionId !== undefined) {
      return this._failClosed(req, res, 400);
    }

    // 2. Admission check for HELLO replay cache
    const admission = this.replayCache.checkHelloAdmission(nonce);
    if (!admission.allowed) {
      if (admission.reason === 'REPLAY_CACHE_FULL') {
        return this._failClosed(req, res, 503);
      }
      return this._failClosed(req, res, 401);
    }

    // 3. Verify HMAC signature
    const emptySha = computeSha256(Buffer.alloc(0));
    const canonicalReq = buildCanonicalHelloRequest({
      timestamp,
      nonce,
      bodySha256: emptySha,
    });

    const validSig = verifyHmac(this.secret, canonicalReq, signature);
    if (!validSig) {
      // HMAC-invalid HELLO MUST NOT poison/add nonce to replay cache
      return this._failClosed(req, res, 401);
    }

    // 4. Record HELLO nonce only after HMAC passes
    this.replayCache.recordHelloNonce(nonce);

    // 5. Generate cryptographically random 128-bit session id (32 lowercase hex chars)
    const sessionId = crypto.randomBytes(16).toString('hex').toLowerCase();

    // 6. Bind session to the exact server-side TCP socket object
    req.socket._hhaiSessionId = sessionId;
    req.socket._hhaiBusinessRequestCount = 0;

    // 7. Form signed HELLO response
    const respTs = this.nowSec();
    const canonicalResp = buildCanonicalResponse({
      mode: 'HELLO',
      statusCode: 200,
      requestMethod: 'POST',
      requestPath: '/v1/hello',
      requestNonce: nonce,
      responseTimestamp: respTs,
      sessionId,
      bodySha256: emptySha,
    });
    const respSignature = computeHmac(this.secret, canonicalResp);

    res.writeHead(200, {
      'Content-Length': '0',
      'X-HHAI-Version': '1',
      'X-HHAI-Timestamp': String(respTs),
      'X-HHAI-Session-Id': sessionId,
      'X-HHAI-Signature': respSignature,
      Connection: 'keep-alive',
    });
    res.end();
  }

  /**
   * Processes authenticated SESSION requests.
   */
  _processSession(req, res, { path, nonce, timestamp, sessionId, signature, rawBody }) {
    // 1. Physical socket identity enforcement (Mutation T9)
    if (!req.socket || !req.socket._hhaiSessionId || req.socket._hhaiSessionId !== sessionId) {
      return this._failClosed(req, res, 401);
    }

    // 2. Exactly one business request per session (Mutation T10)
    if (req.socket._hhaiBusinessRequestCount >= 1) {
      return this._failClosed(req, res, 403);
    }

    // 3. Body hash & Canonical request
    const bodySha = computeSha256(rawBody);
    const canonicalReq = buildCanonicalSessionRequest({
      method: 'POST',
      path,
      timestamp,
      nonce,
      sessionId,
      bodySha256: bodySha,
    });

    // 4. Verify HMAC signature (MUST happen BEFORE recording replay nonce - R1-F5)
    const validSig = verifyHmac(this.secret, canonicalReq, signature);
    if (!validSig) {
      return this._failClosed(req, res, 401, false);
    }

    // 5. Replay key check: (session_id, nonce) ONLY AFTER HMAC succeeds
    const replayCheck = this.replayCache.checkAndRecordSessionNonce(sessionId, nonce);
    if (!replayCheck.allowed) {
      return this._failClosed(req, res, 401);
    }

    // Mark session request count consumed
    req.socket._hhaiBusinessRequestCount++;

    // 5. MAX_BODY_BYTES enforcement before JSON parse (Mutation T12)
    if (rawBody.length > MAX_BODY_BYTES) {
      return this._failClosed(req, res, 413);
    }

    // 6. Parse JSON body
    let parsedBody;
    try {
      parsedBody = JSON.parse(rawBody.toString('utf-8'));
    } catch {
      this._sendSignedResponse(res, {
        status: 400,
        body: { ok: false, code: 'INVALID_REQUEST' },
        requestNonce: nonce,
        requestPath: path,
        sessionId,
      });
      return;
    }

    // 7. STOPPING gate: authenticated request reaching STOPPING gets bounded 503 GATEWAY_STOPPING (Mutation T18)
    if (this.isStopping) {
      this._sendSignedResponse(res, {
        status: 503,
        body: { ok: false, code: 'GATEWAY_STOPPING' },
        requestNonce: nonce,
        requestPath: path,
        sessionId,
      });
      return;
    }

    // 8. Dispatch to business dispatcher
    const result = this.dispatcher.dispatch(path, parsedBody);
    this._sendSignedResponse(res, {
      status: result.status,
      body: result.body,
      requestNonce: nonce,
      requestPath: path,
      sessionId,
    });
  }

  /**
   * Helper to write a signed authenticated HTTP response.
   */
  _sendSignedResponse(res, { status, body, requestNonce, requestPath, sessionId }) {
    const respBodyBuf = Buffer.from(JSON.stringify(body), 'utf-8');
    const respSha = computeSha256(respBodyBuf);
    const respTs = this.nowSec();

    const canonicalResp = buildCanonicalResponse({
      mode: 'SESSION',
      statusCode: status,
      requestMethod: 'POST',
      requestPath,
      requestNonce,
      responseTimestamp: respTs,
      sessionId,
      bodySha256: respSha,
    });
    const respSignature = computeHmac(this.secret, canonicalResp);

    res.writeHead(status, {
      'Content-Type': 'application/json',
      'Content-Length': String(respBodyBuf.length),
      'X-HHAI-Version': '1',
      'X-HHAI-Timestamp': String(respTs),
      'X-HHAI-Session-Id': sessionId,
      'X-HHAI-Signature': respSignature,
      Connection: 'keep-alive',
    });
    res.end(respBodyBuf);
  }

  /**
   * Closes all active connections.
   */
  closeAllConnections() {
    for (const socket of this.trackedSockets) {
      try {
        socket.destroy();
      } catch {}
    }
    this.trackedSockets.clear();
  }

  /**
   * Graceful stop: stops accepting new connections, drains existing connections with timeout.
   *
   * @returns {Promise<void>}
   */
  async stop() {
    this.isStopping = true;
    if (!this.server) {
      return;
    }

    return new Promise((resolve) => {
      this.server.close(() => {
        resolve();
      });

      // Drain connections up to SHUTDOWN_DRAIN_MS
      const timer = setTimeout(() => {
        this.closeAllConnections();
        resolve();
      }, SHUTDOWN_DRAIN_MS);

      if (timer.unref) {
        timer.unref();
      }
    });
  }
}

module.exports = {
  LocalApiServer,
};
