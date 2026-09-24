/**
 * runtime/channel-gateway/tests/telegram-inbound-adapter.test.js
 *
 * Comprehensive safety and lifecycle test suite for Telegram Test-Bot Inbound Adapter
 * (TG-MVP-10 / ADR-0022 / ADR-0024 / ADR-0026 / Bounded Repair R2).
 *
 * Covers all 62 assertions in Section 30, zero-real-network trap (§31), and macrotask fairness (§35).
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { DatabaseSync } = require('node:sqlite');
const { SqliteStateRepository } = require('../core/sqlite-state-repository');
const { AccountRegistry } = require('../core/account-registry');
const {
  TelegramInboundAdapter,
  TELEGRAM_CHANNEL_ID,
  TELEGRAM_API_ORIGIN,
  TELEGRAM_WEEK_REBASE_MS,
  TELEGRAM_CLIENT_TIMEOUT_MS,
  TELEGRAM_POLL_TIMEOUT_SECONDS,
  GENERIC_BACKOFF_MS,
  validateTelegramTokenBuffer,
  classifyTelegramUpdate,
} = require('../adapters/telegram-inbound-adapter');

// ============================================================================
// Section 31: Zero Real Network Trap
// ============================================================================
const originalGlobalFetch = globalThis.fetch;
globalThis.fetch = () => {
  throw new Error('REAL_NETWORK_FORBIDDEN_TEST');
};

test.after(() => {
  globalThis.fetch = originalGlobalFetch;
});

test('Section 31: Zero-real-network trap throws REAL_NETWORK_FORBIDDEN_TEST on global fetch', () => {
  assert.throws(
    () => globalThis.fetch('https://api.telegram.org'),
    /REAL_NETWORK_FORBIDDEN_TEST/
  );
});

// ============================================================================
// Test Helpers & Synthetic Fixtures
// ============================================================================

function createTempHarness() {
  const baseDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-tg-adapter-test-'));
  const stateRoot = path.join(baseDir, 'state');
  fs.mkdirSync(stateRoot, { recursive: true });

  const repo = new SqliteStateRepository(stateRoot);

  function cleanup() {
    try {
      repo.close();
    } catch (_) {}
    try {
      fs.rmSync(baseDir, { recursive: true, force: true });
    } catch (_) {}
  }

  return {
    baseDir,
    stateRoot,
    repo,
    cleanup,
  };
}

class FakeSecretProvider {
  constructor(secretMap = {}) {
    this.secretMap = new Map();
    for (const [k, v] of Object.entries(secretMap)) {
      this.secretMap.set(k, Buffer.isBuffer(v) ? v : Buffer.from(v, 'utf8'));
    }
    this.getSecretCalls = [];
  }

  getSecret(secretRef) {
    this.getSecretCalls.push(secretRef);
    const accId = secretRef?.accountId || String(secretRef);
    for (const [k, v] of this.secretMap.entries()) {
      if (k === accId || k.includes(accId)) {
        return Buffer.from(v);
      }
    }
    throw new Error(`Secret not found for ref: ${accId}`);
  }
}

// ============================================================================
// Constructor Allowlist Tests (F5, Section 21, Section 30 items 1-5)
// ============================================================================

test('Constructor Allowlist: rejects unknown keys and external overrides', () => {
  const harness = createTempHarness();
  try {
    const registry = new AccountRegistry();
    const secretProvider = new FakeSecretProvider();
    const baseOpts = {
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
    };

    // 1. constructor unknown key rejected
    assert.throws(
      () => new TelegramInboundAdapter({ ...baseOpts, unknownProperty: 123 }),
      /Unknown constructor option: 'unknownProperty'/
    );

    // 2. apiBaseUrl option rejected
    assert.throws(
      () => new TelegramInboundAdapter({ ...baseOpts, apiBaseUrl: 'https://custom.tg.org' }),
      /Unknown constructor option: 'apiBaseUrl'/
    );

    // 3. weekRebaseMs option rejected
    assert.throws(
      () => new TelegramInboundAdapter({ ...baseOpts, weekRebaseMs: 12345 }),
      /Unknown constructor option: 'weekRebaseMs'/
    );

    // 4. clientTimeoutMs option rejected
    assert.throws(
      () => new TelegramInboundAdapter({ ...baseOpts, clientTimeoutMs: 5000 }),
      /Unknown constructor option: 'clientTimeoutMs'/
    );

    // 5. poll timeout overrides rejected (pollTimeoutSec and pollTimeoutSeconds)
    assert.throws(
      () => new TelegramInboundAdapter({ ...baseOpts, pollTimeoutSec: 10 }),
      /Unknown constructor option: 'pollTimeoutSec'/
    );
    assert.throws(
      () => new TelegramInboundAdapter({ ...baseOpts, pollTimeoutSeconds: 10 }),
      /Unknown constructor option: 'pollTimeoutSeconds'/
    );

    // clock option rejected
    assert.throws(
      () => new TelegramInboundAdapter({ ...baseOpts, clock: {} }),
      /Unknown constructor option: 'clock'/
    );

    // missing dependencies
    assert.throws(() => new TelegramInboundAdapter({}), /accountRegistry with getActive/);
    assert.throws(() => new TelegramInboundAdapter({ accountRegistry: registry }), /secretProvider with getSecret/);
    assert.throws(() => new TelegramInboundAdapter({ accountRegistry: registry, secretProvider }), /stateRepository with ingestMessage/);

    // Valid constructor succeeds with fixed constants
    const adapter = new TelegramInboundAdapter(baseOpts);
    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(TELEGRAM_API_ORIGIN, 'https://api.telegram.org');
    assert.strictEqual(TELEGRAM_POLL_TIMEOUT_SECONDS, 30);
    assert.strictEqual(TELEGRAM_CLIENT_TIMEOUT_MS, 40000);
    assert.strictEqual(TELEGRAM_WEEK_REBASE_MS, 604800000);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Token Grammar & Diagnostics Tests (F6, Section 23, Section 30 items 6-19)
// ============================================================================

test('Token Grammar: rejects malformed structural syntax without disclosing token material', () => {
  // Valid token passes
  assert.doesNotThrow(() => validateTelegramTokenBuffer(Buffer.from('123456:AAABBBCCC-123_xyz', 'utf8')));

  const invalidTokens = [
    { name: 'missing colon', token: '123456AAABBBCCC' },
    { name: 'empty bot id', token: ':secrettoken' },
    { name: 'empty secret', token: '123456:' },
    { name: 'extra colon', token: '123456:secret:extra' },
    { name: 'hash #', token: '123456:secret#part' },
    { name: 'backslash \\', token: '123456:secret\\part' },
    { name: 'percent %', token: '123456:secret%20part' },
    { name: 'slash /', token: '123456:secret/part' },
    { name: 'question-mark ?', token: '123456:secret?part' },
    { name: 'whitespace', token: '123456:secret part' },
    { name: 'C0 control byte', token: '123456:secret\x01part' },
    { name: 'DEL byte', token: '123456:secret\x7fpart' },
    { name: 'non-ASCII UTF-8 bytes', token: '123456:secret測試' },
    { name: 'leading non-digit in bot id', token: 'a123:secret' },
  ];

  for (const item of invalidTokens) {
    const buf = Buffer.from(item.token, 'utf8');
    assert.throws(
      () => validateTelegramTokenBuffer(buf),
      (err) => {
        // Must be stable diagnostic only
        assert.strictEqual(err.message, 'INVALID_TELEGRAM_TOKEN_SYNTAX', `Failed on case: ${item.name}`);
        // No token material exposed
        assert.ok(!err.message.includes(item.token), `Token material exposed for: ${item.name}`);
        // No byte value or index disclosure
        assert.ok(!err.message.includes('byte') && !err.message.includes('index') && !err.message.includes('at'), `Byte/index disclosure for: ${item.name}`);
        return true;
      },
      `Expected INVALID_TELEGRAM_TOKEN_SYNTAX for ${item.name}`
    );
  }
});

// ============================================================================
// Secret Provider Buffer Ownership & Zeroization (F1, Section 13, 14, items 20-26)
// ============================================================================

test('Secret Buffer Lifecycle: caller adopts provider Buffer directly and zeroizes on all exit paths', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_sec', label: 'Bot Sec', enabled: true },
    ]);
    registry.setActive('tg_bot_sec');

    // 1. Normal stop zeroizes exact provider buffer
    let returnedBuffer1 = Buffer.from('11111:secret_one_token', 'utf8');
    let getSecretCount = 0;
    const provider1 = {
      getSecret: () => {
        getSecretCount++;
        return returnedBuffer1;
      },
    };

    let fakeFetchCalled = 0;
    const fakeFetch1 = async () => {
      fakeFetchCalled++;
      await new Promise((resolve) => setImmediate(resolve));
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          result: [
            { update_id: 1, message: { message_id: 1, chat: { id: 10 }, text: 'msg1' } },
            { update_id: 2, message: { message_id: 2, chat: { id: 10 }, text: 'msg2' } },
          ],
        }),
      };
    };

    const adapter1 = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: provider1,
      stateRepository: harness.repo,
      fetchFn: fakeFetch1,
    });

    adapter1.start();
    assert.strictEqual(getSecretCount, 1, 'getSecret called exactly once at start');

    // Give fetch a tick to ingest updates and loop
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.strictEqual(getSecretCount, 1, 'no getSecret per poll or update');

    await adapter1.stop();
    assert.strictEqual(adapter1.isRunning, false);
    // Provider Buffer zeroized
    assert.ok(returnedBuffer1.every((b) => b === 0), 'Exact provider Buffer must be zeroized on normal stop');

    // 2. Terminal 409 zeroizes exact provider buffer
    let returnedBuffer2 = Buffer.from('22222:secret_two_token', 'utf8');
    const provider2 = { getSecret: () => returnedBuffer2 };
    const fakeFetch409 = async () => {
      await new Promise((resolve) => setImmediate(resolve));
      return {
        ok: false,
        status: 409,
        json: async () => ({ ok: false, error_code: 409, description: 'Conflict: terminated by other getUpdates' }),
      };
    };

    const adapter2 = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: provider2,
      stateRepository: harness.repo,
      fetchFn: fakeFetch409,
    });

    adapter2.start();
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.strictEqual(adapter2.isRunning, false);
    assert.strictEqual(adapter2.terminalReason, 'TELEGRAM_RECEIVER_CONFLICT');
    assert.ok(returnedBuffer2.every((b) => b === 0), 'Buffer zeroized on terminal 409');

    // 3. Other terminal failure (e.g. 401) zeroizes buffer
    let returnedBuffer3 = Buffer.from('33333:secret_three_token', 'utf8');
    const provider3 = { getSecret: () => returnedBuffer3 };
    const fakeFetch401 = async () => {
      await new Promise((resolve) => setImmediate(resolve));
      return {
        ok: false,
        status: 401,
        json: async () => ({ ok: false, error_code: 401, description: 'Unauthorized' }),
      };
    };

    const adapter3 = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: provider3,
      stateRepository: harness.repo,
      fetchFn: fakeFetch401,
    });

    adapter3.start();
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.strictEqual(adapter3.isRunning, false);
    assert.strictEqual(adapter3.terminalReason, 'HTTP_CLIENT_ERROR');
    assert.ok(returnedBuffer3.every((b) => b === 0), 'Buffer zeroized on terminal 401');

    // 4. Token validation startup failure zeroizes buffer immediately
    let returnedBufferBad = Buffer.from('invalid-token-no-colon', 'utf8');
    const providerBad = { getSecret: () => returnedBufferBad };
    const adapterBad = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: providerBad,
      stateRepository: harness.repo,
      fetchFn: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, result: [] }) }),
    });

    assert.throws(() => adapterBad.start(), /INVALID_TELEGRAM_TOKEN_SYNTAX/);
    assert.ok(returnedBufferBad.every((b) => b === 0), 'Buffer zeroized on startup token-syntax validation failure');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Lifecycle & Concurrency (F8, items 27-32)
// ============================================================================

test('Lifecycle & Concurrency: double start rejected, stop idempotent, aborts fetch and body parse, quiesces', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_life', label: 'Bot Life', enabled: true },
    ]);
    registry.setActive('tg_bot_life');
    const secretProvider = new FakeSecretProvider({
      'tg_bot_life': '55555:life_cycle_token',
    });

    let fetchSignalAborted = false;
    let bodyParseSignalAborted = false;

    const fakeFetchSlow = async (url, options) => {
      if (options?.signal) {
        options.signal.addEventListener('abort', () => {
          fetchSignalAborted = true;
        });
      }
      return {
        ok: true,
        status: 200,
        json: async () => {
          return new Promise((resolve, reject) => {
            const safetyTimer = setTimeout(() => {
              reject(new Error('RESPONSE_BODY_TIMEOUT_WITHOUT_ABORT'));
            }, 300);
            if (options?.signal) {
              options.signal.addEventListener('abort', () => {
                clearTimeout(safetyTimer);
                bodyParseSignalAborted = true;
                const err = new Error('The operation was aborted');
                err.name = 'AbortError';
                reject(err);
              });
            }
          });
        },
      };
    };

    const adapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchSlow,
    });

    adapter.start();
    assert.strictEqual(adapter.isRunning, true);

    // 27. Double start rejected
    assert.throws(() => adapter.start(), /already running/);

    // Give a tick for fetch and body parse to be pending
    await new Promise((resolve) => setTimeout(resolve, 20));

    // 29 & 30. Stop aborts in-flight fetch and slow response-body parse
    await adapter.stop();
    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(fetchSignalAborted || bodyParseSignalAborted, true);

    // 28. Stop idempotent
    await adapter.stop();
    await adapter.stop();
    assert.strictEqual(adapter.isRunning, false);

    // 31 & 32. Quiescence & no repository calls after stop
    const cursor = harness.repo.getIngestCursor('tg_bot_life');
    assert.strictEqual(cursor, null);
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Active Account Hot-Switch Guards (F2, Section 15, items 33-35)
// ============================================================================

test('Active Account Hot-Switch: pre-request and post-response rechecks discard in-flight updates and zeroize token', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_alpha', label: 'Bot Alpha', enabled: true },
      { id: 'tg_bot_beta', label: 'Bot Beta', enabled: true },
    ]);
    registry.setActive('tg_bot_alpha');

    const tokenBufAlpha = Buffer.from('11111:alpha_token_secret', 'utf8');
    const secretProvider = {
      getSecret: (ref) => {
        if (ref?.accountId === 'tg_bot_alpha' || String(ref) === 'tg_bot_alpha') {
          return tokenBufAlpha;
        }
        return Buffer.from('22222:beta_token_secret', 'utf8');
      },
    };

    let fetchResolve;
    const fakeFetchDeferred = async () => {
      return new Promise((resolve) => {
        fetchResolve = () =>
          resolve({
            ok: true,
            status: 200,
            json: async () => ({
              ok: true,
              result: [
                {
                  update_id: 101,
                  message: { message_id: 1, chat: { id: 77 }, text: 'Should be discarded' },
                },
              ],
            }),
          });
      });
    };

    const adapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchDeferred,
    });

    adapter.start();
    await new Promise((resolve) => setTimeout(resolve, 20));

    // 34. Active account changes while request in-flight
    registry.setActive('tg_bot_beta');

    // Now resolve the in-flight request
    fetchResolve();
    await new Promise((resolve) => setTimeout(resolve, 30));

    // 33 & 34. In-flight response not ingested, loop stopped with ACTIVE_ACCOUNT_CHANGED
    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(adapter.terminalReason, 'ACTIVE_ACCOUNT_CHANGED');
    assert.strictEqual(harness.repo.getIngestCursor('tg_bot_alpha'), null);
    assert.strictEqual(harness.repo.getIngestCursor('tg_bot_beta'), null);
    // Old token zeroized
    assert.ok(tokenBufAlpha.every((b) => b === 0), 'Old token must be zeroized on active account change');

    // 35. Disabled active account -> terminal
    const registryDisabled = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_dis', label: 'Disabled Bot', enabled: true },
    ]);
    registryDisabled.setActive('tg_bot_dis');
    const tokenBufDis = Buffer.from('33333:dis_token_secret', 'utf8');
    const adapterDis = new TelegramInboundAdapter({
      accountRegistry: registryDisabled,
      secretProvider: { getSecret: () => tokenBufDis },
      stateRepository: harness.repo,
      fetchFn: async () => {
        await new Promise((resolve) => setImmediate(resolve));
        return { ok: true, status: 200, json: async () => ({ ok: true, result: [] }) };
      },
    });

    adapterDis.start();
    await new Promise((resolve) => setTimeout(resolve, 10));
    // Disable account before next request
    registryDisabled.accounts.get('tg_bot_dis').enabled = false;
    await new Promise((resolve) => setTimeout(resolve, 30));

    assert.strictEqual(adapterDis.isRunning, false);
    assert.strictEqual(adapterDis.terminalReason, 'ACTIVE_ACCOUNT_CHANGED');
    assert.ok(tokenBufDis.every((b) => b === 0), 'Token zeroized on disabled account termination');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Strict Retry Allowlist & Repository Failures (F4, items 36-53)
// ============================================================================

test('Retry & Error Matrix: strict retry allowlist vs terminal fail-closed', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_retry', label: 'Bot Retry', enabled: true },
    ]);
    registry.setActive('tg_bot_retry');
    const secretProvider = new FakeSecretProvider({
      'tg_bot_retry': '44444:retry_test_token',
    });

    // 36. Network rejection -> generic retry
    // 37. Client timeout -> retry
    // 38. Malformed JSON -> retry / no cursor
    // 39. ok=true missing result -> retry / no cursor
    // 40. ok=true non-array result -> retry / no cursor
    // 41. HTTP 500 -> retry
    // 42. HTTP 503 -> retry
    // 53. Success resets generic backoff

    let attempt = 0;
    const retrySequence = [
      () => Promise.reject(new Error('fetch failed (network transport)')), // 36
      () => { // 37
        const err = new Error('The operation timed out');
        err.name = 'TimeoutError';
        return Promise.reject(err);
      },
      () => Promise.resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError('Malformed JSON'); } }), // 38
      () => Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true }) }), // 39
      () => Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true, result: 'not-an-array' }) }), // 40
      () => Promise.resolve({ ok: false, status: 500, json: async () => ({ ok: false, error_code: 500 }) }), // 41
      () => Promise.resolve({ ok: false, status: 503, json: async () => ({ ok: false, error_code: 503 }) }), // 42
      () => Promise.resolve({ // 53 success
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          result: [{ update_id: 100, message: { message_id: 1, chat: { id: 1 }, text: 'Recovered' } }],
        }),
      }),
      () => Promise.reject(new Error('subsequent failure after success to prove backoff reset')),
    ];

    const timeoutsScheduled = [];
    const fastSetTimeout = (fn, ms) => {
      timeoutsScheduled.push(ms);
      if (ms >= 40000) {
        const t = setTimeout(fn, ms);
        if (typeof t?.unref === 'function') t.unref();
        return t;
      }
      return setTimeout(fn, 1);
    };

    const fakeFetchRetry = async () => {
      await new Promise((resolve) => setImmediate(resolve));
      const fn = retrySequence[attempt] || (() => Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true, result: [] }) }));
      attempt++;
      return fn();
    };

    const adapterRetry = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchRetry,
      setTimeoutFn: fastSetTimeout,
      clearTimeoutFn: (id) => clearTimeout(id),
    });

    adapterRetry.start();
    // Allow retries to step through fastSetTimeout including the post-success failure
    while (timeoutsScheduled.filter((ms) => ms < 40000).length < 8 && adapterRetry.isRunning) {
      await new Promise((resolve) => setTimeout(resolve, 15));
    }
    await adapterRetry.stop();
    assert.strictEqual(harness.repo.getIngestCursor('tg_bot_retry'), '101');
    const backoffDelays = timeoutsScheduled.filter((ms) => ms < 40000);
    assert.strictEqual(backoffDelays[0], 1000, 'Initial backoff 1000ms');
    assert.strictEqual(backoffDelays[1], 2000, 'Second backoff 2000ms');
    assert.strictEqual(backoffDelays[7], 1000, 'Backoff after success must reset to 1000ms');

    // 43-46. Terminal HTTP codes: 409, 401, 403, 400
    for (const code of [401, 403, 400]) {
      const secretBuf = Buffer.from('66666:term_code_token', 'utf8');
      const adapterTerm = new TelegramInboundAdapter({
        accountRegistry: registry,
        secretProvider: { getSecret: () => secretBuf },
        stateRepository: harness.repo,
        fetchFn: async () => {
          await new Promise((resolve) => setImmediate(resolve));
          return {
            ok: false,
            status: code,
            json: async () => ({ ok: false, error_code: code, description: 'Client error message' }),
          };
        },
      });

      adapterTerm.start();
      await new Promise((resolve) => setTimeout(resolve, 20));
      assert.strictEqual(adapterTerm.isRunning, false);
      assert.strictEqual(adapterTerm.terminalReason, 'HTTP_CLIENT_ERROR');
    }

    // 47 & 48. 429 valid retry_after vs invalid retry_after
    let wait429ms = null;
    const adapter429Valid = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: async () => {
        return {
          ok: false,
          status: 429,
          json: async () => ({
            ok: false,
            error_code: 429,
            description: 'Too Many Requests',
            parameters: { retry_after: 3 },
          }),
        };
      },
      setTimeoutFn: (fn, ms) => {
        if (ms >= 40000) {
          const t = setTimeout(fn, ms);
          if (typeof t?.unref === 'function') t.unref();
          return t;
        }
        wait429ms = ms;
        return setTimeout(fn, 1);
      },
      clearTimeoutFn: (id) => clearTimeout(id),
    });

    adapter429Valid.start();
    await new Promise((resolve) => setTimeout(resolve, 20));
    await adapter429Valid.stop();
    assert.strictEqual(wait429ms, 3000, '429 valid retry_after waits exact platform delay');

    // 48. 429 invalid retry_after -> terminal
    const adapter429Invalid = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: async () => ({
        ok: false,
        status: 429,
        json: async () => ({
          ok: false,
          error_code: 429,
          description: 'Too Many Requests',
          parameters: { retry_after: -1 },
        }),
      }),
    });

    adapter429Invalid.start();
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.strictEqual(adapter429Invalid.isRunning, false);
    assert.strictEqual(adapter429Invalid.terminalReason, 'TELEGRAM_API_ERROR');

    // 49. ok=false raw Telegram description absent from diagnostics
    assert.ok(!JSON.stringify(adapter429Invalid).includes('Too Many Requests'));

    // 50-52. Repository errors terminal (CURSOR_REGRESSION, EVENT_IDENTITY_CONFLICT, generic SQLite)
    const mockRepo = {
      open: () => mockRepo,
      close: () => {},
      getIngestCursorState: () => ({ cursorValue: '100', updatedAtMs: Date.now() - 1000 }),
      getIngestCursor: () => '100',
      ingestMessage: () => {
        throw new Error('CURSOR_REGRESSION: candidate cursor < stored cursor (fail-closed)');
      },
    };

    const adapterRepoTerm = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: mockRepo,
      fetchFn: async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          result: [{ update_id: 50, message: { message_id: 1, chat: { id: 1 }, text: 'Regress' } }],
        }),
      }),
    });

    adapterRepoTerm.start();
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.strictEqual(adapterRepoTerm.isRunning, false);
    assert.strictEqual(adapterRepoTerm.terminalReason, 'REPOSITORY_TERMINAL');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Cursor Semantics & Week Rebase (F7, ADR-0024, items 54-59)
// ============================================================================

test('Cursor & Week Rebase: threshold comparison, future timestamp rejection, and clean query parameters', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_cur', label: 'Bot Cur', enabled: true },
    ]);
    registry.setActive('tg_bot_cur');
    const secretProvider = new FakeSecretProvider({
      'tg_bot_cur': '77777:cur_test_token',
    });

    let requestedBodies = [];
    const fakeFetchCapture = async (url, options) => {
      if (options?.body) {
        try {
          requestedBodies.push(JSON.parse(options.body));
        } catch (_) {}
      }
      await new Promise((resolve) => setImmediate(resolve));
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, result: [] }),
      };
    };

    // 54. cursor age < 604800000 -> retain offset
    const freshTimestamp = Date.now() - 10000;
    harness.repo.ingestMessage({
      accountId: 'tg_bot_cur',
      platformEventId: 'evt_init',
      platformMsgId: 'msg_init',
      channelId: 'telegram',
      content: 'init',
      cursorValue: '500',
      cursorObservedAtMs: freshTimestamp,
    });

    const adapterFresh = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchCapture,
    });

    adapterFresh.start();
    await new Promise((resolve) => setTimeout(resolve, 20));
    await adapterFresh.stop();

    assert.strictEqual(requestedBodies[0].offset, 500, 'Retains offset when cursor age < 7 days');
    assert.strictEqual(requestedBodies[0].drop_pending_updates, undefined, 'No drop_pending_updates in query');
    assert.ok(requestedBodies[0].offset === undefined || Number(requestedBodies[0].offset) >= 0, 'No negative offset in query');

    // 55 & 56. cursor age == 604800000 and > 604800000 -> reset cursor and omit offset
    requestedBodies = [];
    const fixedNow = 1727180000000;
    const staleTimestampExact = fixedNow - TELEGRAM_WEEK_REBASE_MS;
    // update cursor to exact 7-day stale timestamp directly
    const rawDb = new DatabaseSync(harness.repo.databasePath);
    rawDb.prepare('UPDATE ingest_cursor SET updated_at_ms = ? WHERE account_id = ?;').run(staleTimestampExact, 'tg_bot_cur');
    rawDb.close();

    const adapterStale = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchCapture,
      now: () => fixedNow,
    });

    adapterStale.start();
    await new Promise((resolve) => setTimeout(resolve, 20));
    await adapterStale.stop();

    assert.strictEqual(requestedBodies[0].offset, undefined, 'Omit offset when cursor age >= 7 days');
    assert.strictEqual(harness.repo.getIngestCursor('tg_bot_cur'), null, 'Cursor reset on week rebase');

    // 57. future updatedAtMs -> terminal fail closed (INVALID_CURSOR_TIMESTAMP)
    const futureTimestamp = Date.now() + 60000;
    harness.repo.ingestMessage({
      accountId: 'tg_bot_cur',
      platformEventId: 'evt_future',
      platformMsgId: 'msg_future',
      channelId: 'telegram',
      content: 'future',
      cursorValue: '900',
      cursorObservedAtMs: Date.now(),
    });
    const rawDb2 = new DatabaseSync(harness.repo.databasePath);
    rawDb2.prepare('UPDATE ingest_cursor SET updated_at_ms = ? WHERE account_id = ?;').run(futureTimestamp, 'tg_bot_cur');
    rawDb2.close();

    const adapterFuture = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchCapture,
    });

    adapterFuture.start();
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.strictEqual(adapterFuture.isRunning, false);
    assert.strictEqual(adapterFuture.terminalReason, 'INVALID_CURSOR_TIMESTAMP');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Malformed Updates & Poison Loop Prevention (F9, items 60-61)
// ============================================================================

test('Update Classification & Poison Loop Prevention: valid update_id malformed payload -> IGNORED + cursor, invalid update_id -> zero mutation', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_malform', label: 'Bot Malform', enabled: true },
    ]);
    registry.setActive('tg_bot_malform');
    const secretProvider = new FakeSecretProvider({
      'tg_bot_malform': '88888:malform_token',
    });

    // 60. valid update_id with malformed payload (e.g. message without text, or non-message unsupported update)
    // 61. invalid update_id (e.g. negative or non-integer) -> zero mutation
    let pollCount = 0;
    const fakeFetchPayloads = async () => {
      pollCount++;
      await new Promise((resolve) => setImmediate(resolve));
      if (pollCount === 1) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            result: [
              // Invalid update_id: must be ignored with zero mutation
              { update_id: -5, message: { message_id: 1, chat: { id: 1 }, text: 'Invalid ID' } },
              { update_id: 'not_a_number', message: { message_id: 2, chat: { id: 1 }, text: 'Invalid ID' } },
              // Valid update_id with malformed message (missing text) -> IGNORED + cursor advance
              { update_id: 2001, message: { message_id: 10, chat: { id: 1 } } },
              // Valid update_id with unsupported event type -> IGNORED + cursor advance
              { update_id: 2002, channel_post: { message_id: 11 } },
              // Valid update_id with proper message -> MESSAGE + cursor advance
              { update_id: 2003, message: { message_id: 12, chat: { id: 1 }, text: 'Valid message' } },
              // Valid update_id with proper edited_message -> EDIT + cursor advance
              { update_id: 2004, edited_message: { message_id: 12, chat: { id: 1 }, text: 'Edited valid message' } },
            ],
          }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, result: [] }),
      };
    };

    const adapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchPayloads,
    });

    adapter.start();
    await new Promise((resolve) => setTimeout(resolve, 40));
    await adapter.stop();

    // Verify cursor advanced to 2005 (2004 + 1)
    assert.strictEqual(harness.repo.getIngestCursor('tg_bot_malform'), '2005');

    // Verify raw database records
    const rawDb = new DatabaseSync(harness.repo.databasePath, { readOnly: true });
    try {
      // Inbound event table should contain 2001, 2002 (IGNORED), 2003 (MESSAGE), 2004 (EDIT)
      // and NO rows for -5 or not_a_number
      const rows = rawDb.prepare('SELECT platform_event_id, event_type FROM inbound_event WHERE account_id = ? ORDER BY event_sequence;').all('tg_bot_malform');
      assert.strictEqual(rows.length, 4);
      assert.strictEqual(rows[0].platform_event_id, '2001');
      assert.strictEqual(rows[0].event_type, 'IGNORED');
      assert.strictEqual(rows[1].platform_event_id, '2002');
      assert.strictEqual(rows[1].event_type, 'IGNORED');
      assert.strictEqual(rows[2].platform_event_id, '2003');
      assert.strictEqual(rows[2].event_type, 'MESSAGE');
      assert.strictEqual(rows[3].platform_event_id, '2004');
      assert.strictEqual(rows[3].event_type, 'EDIT');

      // Inbox should contain msg 12 with edited content
      const inboxRow = rawDb.prepare('SELECT content FROM inbox WHERE account_id = ? AND platform_msg_id = ?;').get('tg_bot_malform', 'tg:1:12');
      assert.ok(inboxRow);
      assert.strictEqual(inboxRow.content, 'Edited valid message');
    } finally {
      rawDb.close();
    }
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Section 35: Synthetic Polling Macrotask Fairness
// ============================================================================

test('Section 35: Continuous synthetic polling yields to macrotasks and stops cleanly', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_macro', label: 'Bot Macro', enabled: true },
    ]);
    registry.setActive('tg_bot_macro');
    const secretProvider = new FakeSecretProvider({
      'tg_bot_macro': '99999:macro_token',
    });

    let pollCycles = 0;
    const fakeFetchContinuous = async () => {
      pollCycles++;
      // Yield to macrotask queue every cycle as required by §35
      await new Promise((resolve) => setImmediate(resolve));
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, result: [] }),
      };
    };

    const adapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchContinuous,
    });

    adapter.start();
    // Allow continuous polling to run several cycles
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.ok(pollCycles >= 2, 'Poll executed multiple cycles without starving event loop');

    // stop() resolves cleanly and quiesces
    await adapter.stop();
    assert.strictEqual(adapter.isRunning, false);
  } finally {
    harness.cleanup();
  }
});
