/**
 * runtime/channel-gateway/tests/telegram-inbound-adapter.test.js
 *
 * Comprehensive safety, lifecycle, and negative-control test suite for Telegram Test-Bot Inbound Adapter
 * (TG-MVP-10 / ADR-0022 / ADR-0024 / ADR-0026 / Bounded Repair R3).
 *
 * Requirements (R3 Section 24):
 * - Explicit per-test timeout ({ timeout: 5000 }) on EVERY top-level test.
 * - Module-level resource registries tracking all adapters, harnesses, and test-created timers.
 * - afterEach best-effort cleanup stops adapters, clears timers, closes repos, and cleans harnesses.
 * - after fallback cleanup restores global fetch and drains registries.
 * - Incidental real timers use unref?.().
 * - Normal focused suite runs without --test-force-exit and terminates naturally.
 * - Full negative controls: SM7A pre-request guard, SM14 response arrival, SM15 transport error,
 *   SM12 client-timeout abort, SM13 client-timeout retry, SM11 repository terminal,
 *   and exact week-rebase boundaries (604799999, 604800000, 604800001).
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
// Section 24B: Module-Level Resource Registries & Tracking Helpers
// ============================================================================

const trackedAdapters = new Set();
const trackedHarnesses = new Set();
const trackedTimers = new Set();

function trackAdapter(adapter) {
  if (adapter) {
    trackedAdapters.add(adapter);
  }
  return adapter;
}

function trackHarness(harness) {
  if (harness) {
    trackedHarnesses.add(harness);
  }
  return harness;
}

function trackTimer(timer) {
  if (timer) {
    trackedTimers.add(timer);
  }
  return timer;
}

function untrackTimer(timer) {
  if (timer) {
    trackedTimers.delete(timer);
  }
}

// ============================================================================
// Section 24C & 24D: afterEach & after Cleanup Hooks
// ============================================================================

test.afterEach({ timeout: 5000 }, async () => {
  // 1. Stop every registered adapter and await quiescence
  for (const adapter of Array.from(trackedAdapters)) {
    try {
      await adapter.stop();
    } catch (_) {}
    trackedAdapters.delete(adapter);
  }

  // 2. Clear any remaining registered real timers
  for (const timer of Array.from(trackedTimers)) {
    try {
      clearTimeout(timer);
    } catch (_) {}
    try {
      clearInterval(timer);
    } catch (_) {}
    trackedTimers.delete(timer);
  }

  // 3. Close repositories and cleanup temp harnesses
  for (const harness of Array.from(trackedHarnesses)) {
    try {
      harness.cleanup();
    } catch (_) {}
    trackedHarnesses.delete(harness);
  }
});

const originalGlobalFetch = globalThis.fetch;
globalThis.fetch = () => {
  throw new Error('REAL_NETWORK_FORBIDDEN_TEST');
};

test.after({ timeout: 5000 }, async () => {
  // Final fallback drain
  for (const adapter of Array.from(trackedAdapters)) {
    try {
      await adapter.stop();
    } catch (_) {}
    trackedAdapters.delete(adapter);
  }
  for (const timer of Array.from(trackedTimers)) {
    try {
      clearTimeout(timer);
    } catch (_) {}
    try {
      clearInterval(timer);
    } catch (_) {}
    trackedTimers.delete(timer);
  }
  for (const harness of Array.from(trackedHarnesses)) {
    try {
      harness.cleanup();
    } catch (_) {}
    trackedHarnesses.delete(harness);
  }
  globalThis.fetch = originalGlobalFetch;
});

// ============================================================================
// Section 31: Zero Real Network Trap
// ============================================================================

test('Section 31: Zero-real-network trap throws REAL_NETWORK_FORBIDDEN_TEST on global fetch', { timeout: 5000 }, () => {
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

  let cleaned = false;
  function cleanup() {
    if (cleaned) return;
    cleaned = true;
    try {
      repo.close();
    } catch (_) {}
    try {
      fs.rmSync(baseDir, { recursive: true, force: true });
    } catch (_) {}
  }

  const harness = {
    baseDir,
    stateRoot,
    repo,
    cleanup,
  };
  return trackHarness(harness);
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

test('Constructor Allowlist: rejects unknown keys and external overrides', { timeout: 5000 }, () => {
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
    const adapter = trackAdapter(new TelegramInboundAdapter(baseOpts));
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

test('Token Grammar: rejects malformed structural syntax without disclosing token material', { timeout: 5000 }, () => {
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

test('Secret Buffer Lifecycle: caller adopts provider Buffer directly and zeroizes on all exit paths', { timeout: 5000 }, async () => {
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

    const adapter1 = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: provider1,
      stateRepository: harness.repo,
      fetchFn: fakeFetch1,
    }));

    adapter1.start();
    assert.strictEqual(getSecretCount, 1, 'getSecret called exactly once at start');

    // Give fetch a tick to ingest updates and loop
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });
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

    const adapter2 = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: provider2,
      stateRepository: harness.repo,
      fetchFn: fakeFetch409,
    }));

    adapter2.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });
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

    const adapter3 = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: provider3,
      stateRepository: harness.repo,
      fetchFn: fakeFetch401,
    }));

    adapter3.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });
    assert.strictEqual(adapter3.isRunning, false);
    assert.strictEqual(adapter3.terminalReason, 'HTTP_CLIENT_ERROR');
    assert.ok(returnedBuffer3.every((b) => b === 0), 'Buffer zeroized on terminal 401');

    // 4. Token validation startup failure zeroizes buffer immediately
    let returnedBufferBad = Buffer.from('invalid-token-no-colon', 'utf8');
    const providerBad = { getSecret: () => returnedBufferBad };
    const adapterBad = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: providerBad,
      stateRepository: harness.repo,
      fetchFn: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, result: [] }) }),
    }));

    assert.throws(() => adapterBad.start(), /INVALID_TELEGRAM_TOKEN_SYNTAX/);
    assert.ok(returnedBufferBad.every((b) => b === 0), 'Buffer zeroized on startup token-syntax validation failure');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Lifecycle & Concurrency (F8, items 27-32)
// ============================================================================

test('Lifecycle & Concurrency: double start rejected, stop idempotent, aborts fetch and body parse, quiesces', { timeout: 5000 }, async () => {
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
            safetyTimer.unref?.();
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

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchSlow,
    }));

    adapter.start();
    assert.strictEqual(adapter.isRunning, true);

    // 27. Double start rejected
    assert.throws(() => adapter.start(), /already running/);

    // Give a tick for fetch and body parse to be pending
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 20);
      t.unref?.();
    });

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
// Active Account Hot-Switch Guards (F2, Section 13, 14, 15, 16, 17)
// ============================================================================

test('Active Account Hot-Switch: pre-request and post-response rechecks discard in-flight updates and zeroize token', { timeout: 5000 }, async () => {
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

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchDeferred,
    }));

    adapter.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 20);
      t.unref?.();
    });

    // 34. Active account changes while request in-flight
    registry.setActive('tg_bot_beta');

    // Now resolve the in-flight request
    fetchResolve();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });

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
    const adapterDis = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registryDisabled,
      secretProvider: { getSecret: () => tokenBufDis },
      stateRepository: harness.repo,
      fetchFn: async () => {
        await new Promise((resolve) => setImmediate(resolve));
        return { ok: true, status: 200, json: async () => ({ ok: true, result: [] }) };
      },
    }));

    adapterDis.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 10);
      t.unref?.();
    });
    // Disable account before next request
    registryDisabled.accounts.get('tg_bot_dis').enabled = false;
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });

    assert.strictEqual(adapterDis.isRunning, false);
    assert.strictEqual(adapterDis.terminalReason, 'ACTIVE_ACCOUNT_CHANGED');
    assert.ok(tokenBufDis.every((b) => b === 0), 'Token zeroized on disabled account termination');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// R3 Section 16: Pre-request Guard Negative Control (SM7A Canary)
// ============================================================================

test('Active Account: pre-request guard negative control proves account switch during backoff terminates without second fetch', { timeout: 5000 }, async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'acc_a', label: 'Account A', enabled: true },
      { id: 'acc_b', label: 'Account B', enabled: true },
    ]);
    registry.setActive('acc_a');

    const tokenBufA = Buffer.from('11111:token_account_a', 'utf8');
    const tokenBufB = Buffer.from('22222:token_account_b', 'utf8');
    const secretProvider = {
      getSecret: (ref) => {
        if (ref?.accountId === 'acc_a') return tokenBufA;
        if (ref?.accountId === 'acc_b') return tokenBufB;
        throw new Error('Unknown secret ref');
      },
    };

    let fetchCountA = 0;
    let pendingBackoffCallback = null;

    const fakeFetch = async (url) => {
      if (url.includes('token_account_a')) {
        fetchCountA++;
        // First fetch fails with retryable 503
        return {
          ok: false,
          status: 503,
          json: async () => ({ ok: false, error_code: 503 }),
        };
      }
      throw new Error('Unexpected URL');
    };

    const controlledSetTimeout = (fn, ms) => {
      if (ms >= 40000) {
        // Client timeout timer: unref
        const t = setTimeout(fn, ms);
        t.unref?.();
        return t;
      }
      // Backoff delay timer: capture callback without running immediately
      pendingBackoffCallback = fn;
      return 1001; // mock timer id
    };

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetch,
      setTimeoutFn: controlledSetTimeout,
      clearTimeoutFn: () => {},
    }));

    adapter.start();

    // Wait until first fetch occurs and adapter enters controlled backoff
    while (fetchCountA < 1 || !pendingBackoffCallback) {
      await new Promise((resolve) => setImmediate(resolve));
    }

    assert.strictEqual(fetchCountA, 1, 'First request dispatched');

    // Switch active account to acc_b while adapter is suspended in backoff
    registry.setActive('acc_b');

    // Release the controlled backoff timer callback
    const resume = pendingBackoffCallback;
    pendingBackoffCallback = null;
    resume();

    // Give loop a tick to wake up, reach pre-request guard, and terminate
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });

    // Verify: pre-request guard caught the switch before second fetch
    assert.strictEqual(fetchCountA, 1, 'No second fetch dispatched for acc_a');
    assert.strictEqual(adapter.isRunning, false, 'Adapter must be stopped');
    assert.strictEqual(adapter.terminalReason, 'ACTIVE_ACCOUNT_CHANGED', 'Must terminate with ACTIVE_ACCOUNT_CHANGED');
    assert.ok(tokenBufA.every((b) => b === 0), 'Old token Buffer must be zeroized');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// R3 Section 17: In-Flight Account Switch Canaries (Cases A, B, C, D)
// ============================================================================

test('Active Account: Case A in-flight switch with 429 response terminates without scheduling retry_after', { timeout: 5000 }, async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_429a', label: 'Bot A', enabled: true },
      { id: 'tg_bot_429b', label: 'Bot B', enabled: true },
    ]);
    registry.setActive('tg_bot_429a');

    const tokenBufA = Buffer.from('12345:token_bot_429a', 'utf8');
    const secretProvider = { getSecret: () => tokenBufA };

    let fetchResolve;
    let scheduledRetryDelays = [];

    const fakeFetchInFlight = async () => {
      return new Promise((resolve) => {
        fetchResolve = () =>
          resolve({
            ok: false,
            status: 429,
            json: async () => ({
              ok: false,
              error_code: 429,
              parameters: { retry_after: 3600 },
            }),
          });
      });
    };

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchInFlight,
      setTimeoutFn: (fn, ms) => {
        if (ms >= 40000) {
          const t = setTimeout(fn, ms);
          t.unref?.();
          return t;
        }
        scheduledRetryDelays.push(ms);
        return 2001;
      },
      clearTimeoutFn: () => {},
    }));

    adapter.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 20);
      t.unref?.();
    });

    // Request is in-flight: switch active account
    registry.setActive('tg_bot_429b');

    // Deliver 429 response
    fetchResolve();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });

    assert.strictEqual(adapter.isRunning, false, 'Adapter stopped on in-flight account switch');
    assert.strictEqual(adapter.terminalReason, 'ACTIVE_ACCOUNT_CHANGED');
    assert.strictEqual(scheduledRetryDelays.length, 0, 'Zero retry_after timers scheduled on switched account');
    assert.ok(tokenBufA.every((b) => b === 0), 'Old token Buffer must be zeroized');
  } finally {
    harness.cleanup();
  }
});

test('Active Account: Case B in-flight switch with 503 response terminates without scheduling backoff', { timeout: 5000 }, async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_503a', label: 'Bot A', enabled: true },
      { id: 'tg_bot_503b', label: 'Bot B', enabled: true },
    ]);
    registry.setActive('tg_bot_503a');

    const tokenBufA = Buffer.from('12345:token_bot_503a', 'utf8');
    const secretProvider = { getSecret: () => tokenBufA };

    let fetchResolve;
    let scheduledRetryDelays = [];

    const fakeFetchInFlight = async () => {
      return new Promise((resolve) => {
        fetchResolve = () =>
          resolve({
            ok: false,
            status: 503,
            json: async () => ({ ok: false, error_code: 503 }),
          });
      });
    };

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchInFlight,
      setTimeoutFn: (fn, ms) => {
        if (ms >= 40000) {
          const t = setTimeout(fn, ms);
          t.unref?.();
          return t;
        }
        scheduledRetryDelays.push(ms);
        return 3001;
      },
      clearTimeoutFn: () => {},
    }));

    adapter.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 20);
      t.unref?.();
    });

    registry.setActive('tg_bot_503b');
    fetchResolve();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });

    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(adapter.terminalReason, 'ACTIVE_ACCOUNT_CHANGED');
    assert.strictEqual(scheduledRetryDelays.length, 0, 'Zero generic backoff timers scheduled');
    assert.ok(tokenBufA.every((b) => b === 0), 'Old token Buffer must be zeroized');
  } finally {
    harness.cleanup();
  }
});

test('Active Account: Case C in-flight switch with transport rejection terminates without scheduling retry', { timeout: 5000 }, async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_trana', label: 'Bot A', enabled: true },
      { id: 'tg_bot_tranb', label: 'Bot B', enabled: true },
    ]);
    registry.setActive('tg_bot_trana');

    const tokenBufA = Buffer.from('12345:token_bot_trana', 'utf8');
    const secretProvider = { getSecret: () => tokenBufA };

    let fetchReject;
    let scheduledRetryDelays = [];

    const fakeFetchInFlight = async () => {
      return new Promise((_, reject) => {
        fetchReject = () => reject(new TypeError('fetch failed (network down)'));
      });
    };

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchInFlight,
      setTimeoutFn: (fn, ms) => {
        if (ms >= 40000) {
          const t = setTimeout(fn, ms);
          t.unref?.();
          return t;
        }
        scheduledRetryDelays.push(ms);
        return 4001;
      },
      clearTimeoutFn: () => {},
    }));

    adapter.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 20);
      t.unref?.();
    });

    registry.setActive('tg_bot_tranb');
    fetchReject();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });

    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(adapter.terminalReason, 'ACTIVE_ACCOUNT_CHANGED');
    assert.strictEqual(scheduledRetryDelays.length, 0, 'Zero retry timers scheduled on transport rejection');
    assert.ok(tokenBufA.every((b) => b === 0), 'Old token Buffer must be zeroized');
  } finally {
    harness.cleanup();
  }
});

test('Active Account: Case D switch during response body parse terminates before ingest without DB mutation', { timeout: 5000 }, async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_bodya', label: 'Bot A', enabled: true },
      { id: 'tg_bot_bodyb', label: 'Bot B', enabled: true },
    ]);
    registry.setActive('tg_bot_bodya');

    const tokenBufA = Buffer.from('12345:token_bot_bodya', 'utf8');
    const secretProvider = { getSecret: () => tokenBufA };

    let bodyResolve;
    const fakeFetch = async () => {
      return {
        ok: true,
        status: 200,
        json: async () => {
          return new Promise((resolve) => {
            bodyResolve = () =>
              resolve({
                ok: true,
                result: [
                  {
                    update_id: 888,
                    message: { message_id: 1, chat: { id: 10 }, text: 'Late body message' },
                  },
                ],
              });
          });
        },
      };
    };

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetch,
    }));

    adapter.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 20);
      t.unref?.();
    });

    // Headers arrived, response.json() is now pending: switch active account
    registry.setActive('tg_bot_bodyb');

    // Deliver body
    bodyResolve();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });

    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(adapter.terminalReason, 'ACTIVE_ACCOUNT_CHANGED');
    assert.strictEqual(harness.repo.getIngestCursor('tg_bot_bodya'), null, 'No DB mutation from late body');
    assert.ok(tokenBufA.every((b) => b === 0), 'Old token Buffer must be zeroized');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// R3 Section 18 & 19: Real Client-Timeout Path & Mutations (SM12 & SM13 Canaries)
// ============================================================================

test('Client Timeout: mechanical execution of 40000ms timer callback proves abort signal and retry classification without wall-clock wait', { timeout: 5000 }, async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_ctime', label: 'Bot CTime', enabled: true },
    ]);
    registry.setActive('tg_bot_ctime');

    const tokenBuf = Buffer.from('99999:client_timeout_token', 'utf8');
    const secretProvider = { getSecret: () => tokenBuf };

    let capturedClientTimeoutCallback = null;
    let scheduledRetryDelays = [];
    let capturedSignal = null;
    let fetchPromiseReject = null;

    const fakeFetchTimeout = async (url, options) => {
      capturedSignal = options.signal;
      return new Promise((resolve, reject) => {
        fetchPromiseReject = reject;
        if (options.signal) {
          options.signal.addEventListener('abort', () => {
            const err = new Error('The operation was aborted');
            err.name = 'AbortError';
            reject(err);
          });
        }
      });
    };

    const fakeSetTimeout = (fn, ms) => {
      if (ms === TELEGRAM_CLIENT_TIMEOUT_MS) {
        capturedClientTimeoutCallback = fn;
        return 40000;
      }
      scheduledRetryDelays.push(ms);
      return 50001;
    };

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchTimeout,
      setTimeoutFn: fakeSetTimeout,
      clearTimeoutFn: () => {},
    }));

    adapter.start();

    // Wait until fetch is in flight and client timeout callback is registered
    while (!capturedClientTimeoutCallback || !capturedSignal) {
      await new Promise((resolve) => setImmediate(resolve));
    }

    assert.strictEqual(capturedSignal.aborted, false, 'Signal not yet aborted before timeout');

    // Mechanically trigger the 40,000ms timer callback
    capturedClientTimeoutCallback();

    // SM12 Negative Control: timer callback must call ac.abort()
    assert.strictEqual(capturedSignal.aborted, true, 'timer callback must abort AbortController signal');

    // Wait a tick for the abort rejection to be processed by adapter catch block
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });

    // SM13 Negative Control: client timeout must be classified retryable (terminalReason remains null)
    assert.strictEqual(adapter.terminalReason, null, 'Client timeout must remain retryable, not terminal');
    assert.strictEqual(adapter.isRunning, true, 'Adapter remains running during retry');
    assert.ok(scheduledRetryDelays.includes(1000), 'Must schedule generic backoff retry (1000ms)');
    assert.strictEqual(tokenBuf.every((b) => b === 0), false, 'Token must NOT be zeroized during legitimate retry');

    // Normal stop quiesces cleanly
    await adapter.stop();
    assert.strictEqual(adapter.isRunning, false);
    assert.ok(tokenBuf.every((b) => b === 0), 'Token zeroized on stop');
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Strict Retry Allowlist & Repository Failures (F4, items 36-53)
// ============================================================================

test('Retry & Error Matrix: strict retry allowlist vs terminal fail-closed', { timeout: 5000 }, async () => {
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
        t.unref?.();
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

    const adapterRetry = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchRetry,
      setTimeoutFn: fastSetTimeout,
      clearTimeoutFn: (id) => clearTimeout(id),
    }));

    adapterRetry.start();
    // Allow retries to step through fastSetTimeout including the post-success failure
    while (timeoutsScheduled.filter((ms) => ms < 40000).length < 8 && adapterRetry.isRunning) {
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 15);
        t.unref?.();
      });
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
      const adapterTerm = trackAdapter(new TelegramInboundAdapter({
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
      }));

      adapterTerm.start();
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 20);
        t.unref?.();
      });
      assert.strictEqual(adapterTerm.isRunning, false);
      assert.strictEqual(adapterTerm.terminalReason, 'HTTP_CLIENT_ERROR');
    }

    // 47 & 48. 429 valid retry_after vs invalid retry_after
    let wait429ms = null;
    const adapter429Valid = trackAdapter(new TelegramInboundAdapter({
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
          t.unref?.();
          return t;
        }
        wait429ms = ms;
        return setTimeout(fn, 1);
      },
      clearTimeoutFn: (id) => clearTimeout(id),
    }));

    adapter429Valid.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 20);
      t.unref?.();
    });
    await adapter429Valid.stop();
    assert.strictEqual(wait429ms, 3000, '429 valid retry_after waits exact platform delay');

    // 48. 429 invalid retry_after -> terminal
    const adapter429Invalid = trackAdapter(new TelegramInboundAdapter({
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
    }));

    adapter429Invalid.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 20);
      t.unref?.();
    });
    assert.strictEqual(adapter429Invalid.isRunning, false);
    assert.strictEqual(adapter429Invalid.terminalReason, 'TELEGRAM_API_ERROR');

    // 49. ok=false raw Telegram description absent from diagnostics
    assert.ok(!JSON.stringify(adapter429Invalid).includes('Too Many Requests'));
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// R3 Section 20 & 21: Repository Terminal Matrix & SM11 Canary
// ============================================================================

test('Repository Terminal Matrix: proves bounded requests, zero retry scheduling, and clean termination for CURSOR_REGRESSION, EVENT_IDENTITY_CONFLICT, and generic SQLite errors', { timeout: 5000 }, async () => {
  const cases = [
    {
      name: 'CURSOR_REGRESSION',
      error: new Error('CURSOR_REGRESSION: candidate cursor < stored cursor (fail-closed)'),
    },
    {
      name: 'EVENT_IDENTITY_CONFLICT',
      error: new Error('EVENT_IDENTITY_CONFLICT: unique constraint failed on inbound_event'),
    },
    {
      name: 'Generic SQLite exception',
      error: new Error('SqliteError: disk I/O error on database file'),
    },
  ];

  for (const c of cases) {
    const harness = createTempHarness();
    try {
      const registry = AccountRegistry.fromMetadata('telegram', [
        { id: `tg_repo_${c.name.toLowerCase().replace(/[^a-z0-9]/g, '_')}`, label: 'Bot Repo', enabled: true },
      ]);
      registry.setActive(registry.accounts.keys().next().value);

      const secretBuf = Buffer.from('55555:repo_terminal_token', 'utf8');
      const secretProvider = { getSecret: () => secretBuf };

      let requestsCount = 0;
      let scheduledDelays = [];

      const mockRepo = {
        open: () => mockRepo,
        close: () => {},
        getIngestCursorState: () => ({ cursorValue: '100', updatedAtMs: Date.now() - 1000 }),
        getIngestCursor: () => '100',
        ingestMessage: () => {
          throw c.error;
        },
      };

      const adapter = trackAdapter(new TelegramInboundAdapter({
        accountRegistry: registry,
        secretProvider,
        stateRepository: mockRepo,
        fetchFn: async () => {
          requestsCount++;
          await new Promise((resolve) => setImmediate(resolve));
          return {
            ok: true,
            status: 200,
            json: async () => ({
              ok: true,
              result: [{ update_id: 50, message: { message_id: 1, chat: { id: 1 }, text: 'Trigger repo error' } }],
            }),
          };
        },
        setTimeoutFn: (fn, ms) => {
          if (ms >= 40000) {
            const t = setTimeout(fn, ms);
            t.unref?.();
            return t;
          }
          scheduledDelays.push(ms);
          // Return synthetic timer handle without automatically firing
          return 6001;
        },
        clearTimeoutFn: () => {},
      }));

      adapter.start();

      // Give a tick for fetch and ingest to execute
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 30);
        t.unref?.();
      });

      // Proof requirements (§20):
      // 1. Bounded request count (exactly 1)
      assert.strictEqual(requestsCount, 1, `${c.name}: exactly 1 request made`);
      // 2. Adapter terminates
      assert.strictEqual(adapter.isRunning, false, `${c.name}: adapter terminated`);
      // 3. terminalReason = REPOSITORY_TERMINAL
      assert.strictEqual(adapter.terminalReason, 'REPOSITORY_TERMINAL', `${c.name}: terminalReason is REPOSITORY_TERMINAL`);
      // 4. Zero retry timers (SM11 Canary: retry mutation causes scheduledDelays > 0)
      assert.strictEqual(scheduledDelays.length, 0, `${c.name}: zero retry timers scheduled`);
      // 5. Token zeroized
      assert.ok(secretBuf.every((b) => b === 0), `${c.name}: token zeroized`);
      // 6. No raw repository error message exposed on adapter instance
      assert.ok(!JSON.stringify(adapter).includes(c.error.message), `${c.name}: raw error message not exposed`);
    } finally {
      harness.cleanup();
    }
  }
});

// ============================================================================
// Cursor Semantics & Week Rebase Matrix (R3 Section 22, F7, ADR-0024)
// ============================================================================

test('Week Rebase Exact Matrix: independent canaries for 604799999ms, 604800000ms, and 604800001ms', { timeout: 5000 }, async () => {
  const harness = createTempHarness();
  try {
    const fixedNow = 1727180000000;

    // 1. Boundary 604799999ms (7 days - 1 ms) -> retain cursor, send offset
    {
      const registry1 = AccountRegistry.fromMetadata('telegram', [
        { id: 'tg_bot_604799999', label: 'Bot 604799999', enabled: true },
      ]);
      registry1.setActive('tg_bot_604799999');
      const secretProvider1 = new FakeSecretProvider({
        'tg_bot_604799999': '77777:token_604799999',
      });

      harness.repo.ingestMessage({
        accountId: 'tg_bot_604799999',
        platformEventId: 'evt_604799999',
        platformMsgId: 'msg_604799999',
        channelId: 'telegram',
        content: 'content_604799999',
        cursorValue: '500',
        cursorObservedAtMs: fixedNow - 604799999,
      });

      let capturedBody1 = null;
      const fakeFetch1 = async (url, options) => {
        if (options?.body) capturedBody1 = JSON.parse(options.body);
        await new Promise((resolve) => setImmediate(resolve));
        return { ok: true, status: 200, json: async () => ({ ok: true, result: [] }) };
      };

      const adapter1 = trackAdapter(new TelegramInboundAdapter({
        accountRegistry: registry1,
        secretProvider: secretProvider1,
        stateRepository: harness.repo,
        fetchFn: fakeFetch1,
        now: () => fixedNow,
      }));

      adapter1.start();
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 20);
        t.unref?.();
      });
      await adapter1.stop();

      assert.strictEqual(capturedBody1.offset, 500, '604799999ms must retain offset 500');
      assert.strictEqual(harness.repo.getIngestCursor('tg_bot_604799999'), '500', 'Cursor retained in DB');
    }

    // 2. Boundary 604800000ms (exact 7 days) -> exact reset, omit offset
    {
      const registry2 = AccountRegistry.fromMetadata('telegram', [
        { id: 'tg_bot_604800000', label: 'Bot 604800000', enabled: true },
      ]);
      registry2.setActive('tg_bot_604800000');
      const secretProvider2 = new FakeSecretProvider({
        'tg_bot_604800000': '77777:token_604800000',
      });

      harness.repo.ingestMessage({
        accountId: 'tg_bot_604800000',
        platformEventId: 'evt_604800000',
        platformMsgId: 'msg_604800000',
        channelId: 'telegram',
        content: 'content_604800000',
        cursorValue: '600',
        cursorObservedAtMs: fixedNow - 1000,
      });

      // Update cursor updatedAtMs to exact 604800000ms stale timestamp directly in DB
      const rawDb = new DatabaseSync(harness.repo.databasePath);
      rawDb.prepare('UPDATE ingest_cursor SET updated_at_ms = ? WHERE account_id = ?;').run(fixedNow - 604800000, 'tg_bot_604800000');
      rawDb.close();

      let capturedBody2 = null;
      const fakeFetch2 = async (url, options) => {
        if (options?.body) capturedBody2 = JSON.parse(options.body);
        await new Promise((resolve) => setImmediate(resolve));
        return { ok: true, status: 200, json: async () => ({ ok: true, result: [] }) };
      };

      const adapter2 = trackAdapter(new TelegramInboundAdapter({
        accountRegistry: registry2,
        secretProvider: secretProvider2,
        stateRepository: harness.repo,
        fetchFn: fakeFetch2,
        now: () => fixedNow,
      }));

      adapter2.start();
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 20);
        t.unref?.();
      });
      await adapter2.stop();

      assert.strictEqual(capturedBody2.offset, undefined, '604800000ms must omit offset (undefined)');
      assert.strictEqual(harness.repo.getIngestCursor('tg_bot_604800000'), null, 'Cursor reset in DB');
    }

    // 3. Boundary 604800001ms (7 days + 1 ms) -> exact reset, omit offset
    {
      const registry3 = AccountRegistry.fromMetadata('telegram', [
        { id: 'tg_bot_604800001', label: 'Bot 604800001', enabled: true },
      ]);
      registry3.setActive('tg_bot_604800001');
      const secretProvider3 = new FakeSecretProvider({
        'tg_bot_604800001': '77777:token_604800001',
      });

      harness.repo.ingestMessage({
        accountId: 'tg_bot_604800001',
        platformEventId: 'evt_604800001',
        platformMsgId: 'msg_604800001',
        channelId: 'telegram',
        content: 'content_604800001',
        cursorValue: '700',
        cursorObservedAtMs: fixedNow - 1000,
      });

      const rawDb = new DatabaseSync(harness.repo.databasePath);
      rawDb.prepare('UPDATE ingest_cursor SET updated_at_ms = ? WHERE account_id = ?;').run(fixedNow - 604800001, 'tg_bot_604800001');
      rawDb.close();

      let capturedBody3 = null;
      const fakeFetch3 = async (url, options) => {
        if (options?.body) capturedBody3 = JSON.parse(options.body);
        await new Promise((resolve) => setImmediate(resolve));
        return { ok: true, status: 200, json: async () => ({ ok: true, result: [] }) };
      };

      const adapter3 = trackAdapter(new TelegramInboundAdapter({
        accountRegistry: registry3,
        secretProvider: secretProvider3,
        stateRepository: harness.repo,
        fetchFn: fakeFetch3,
        now: () => fixedNow,
      }));

      adapter3.start();
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 20);
        t.unref?.();
      });
      await adapter3.stop();

      assert.strictEqual(capturedBody3.offset, undefined, '604800001ms must omit offset (undefined)');
      assert.strictEqual(harness.repo.getIngestCursor('tg_bot_604800001'), null, 'Cursor reset in DB');
    }

    // 4. Future updatedAtMs fail-closed
    {
      const registryFuture = AccountRegistry.fromMetadata('telegram', [
        { id: 'tg_bot_future', label: 'Bot Future', enabled: true },
      ]);
      registryFuture.setActive('tg_bot_future');
      const secretProviderFuture = new FakeSecretProvider({
        'tg_bot_future': '77777:token_future',
      });

      harness.repo.ingestMessage({
        accountId: 'tg_bot_future',
        platformEventId: 'evt_future',
        platformMsgId: 'msg_future',
        channelId: 'telegram',
        content: 'content_future',
        cursorValue: '800',
        cursorObservedAtMs: fixedNow,
      });

      const rawDb = new DatabaseSync(harness.repo.databasePath);
      rawDb.prepare('UPDATE ingest_cursor SET updated_at_ms = ? WHERE account_id = ?;').run(fixedNow + 60000, 'tg_bot_future');
      rawDb.close();

      const adapterFuture = trackAdapter(new TelegramInboundAdapter({
        accountRegistry: registryFuture,
        secretProvider: secretProviderFuture,
        stateRepository: harness.repo,
        fetchFn: async () => {
          await new Promise((resolve) => setImmediate(resolve));
          return { ok: true, status: 200, json: async () => ({ ok: true, result: [] }) };
        },
        now: () => fixedNow,
      }));

      adapterFuture.start();
      await new Promise((resolve) => {
        const t = setTimeout(resolve, 20);
        t.unref?.();
      });

      assert.strictEqual(adapterFuture.isRunning, false);
      assert.strictEqual(adapterFuture.terminalReason, 'INVALID_CURSOR_TIMESTAMP');
    }
  } finally {
    harness.cleanup();
  }
});

// ============================================================================
// Malformed Updates & Poison Loop Prevention (F9, items 60-61)
// ============================================================================

test('Update Classification & Poison Loop Prevention: valid update_id malformed payload -> IGNORED + cursor, invalid update_id -> zero mutation', { timeout: 5000 }, async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_malform', label: 'Bot Malform', enabled: true },
    ]);
    registry.setActive('tg_bot_malform');
    const secretProvider = new FakeSecretProvider({
      'tg_bot_malform': '88888:malform_token',
    });

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

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchPayloads,
    }));

    adapter.start();
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 40);
      t.unref?.();
    });
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

test('Section 35: Continuous synthetic polling yields to macrotasks and stops cleanly', { timeout: 5000 }, async () => {
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

    const adapter = trackAdapter(new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetchContinuous,
    }));

    adapter.start();
    // Allow continuous polling to run several cycles
    await new Promise((resolve) => {
      const t = setTimeout(resolve, 30);
      t.unref?.();
    });
    assert.ok(pollCycles >= 2, 'Poll executed multiple cycles without starving event loop');

    // stop() resolves cleanly and quiesces
    await adapter.stop();
    assert.strictEqual(adapter.isRunning, false);
  } finally {
    harness.cleanup();
  }
});
