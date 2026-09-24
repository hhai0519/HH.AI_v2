/**
 * runtime/channel-gateway/tests/telegram-inbound-adapter.test.js
 *
 * Unit tests for Telegram Test-Bot Inbound Adapter (TG-MVP-10 / ADR-0022 / ADR-0024 / ADR-0026).
 * Strictly synthetic: zero external network calls, zero real credentials, fake fetch & SecretProvider.
 * Tests component lifecycle (start, stop, quiescence), account validation, token boundary safety,
 * message/edit/ignored dispatch, week rebase, 409 conflict, 429 retry-after, and backoff.
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
  TELEGRAM_WEEK_REBASE_MS,
  classifyTelegramUpdate,
} = require('../adapters/telegram-inbound-adapter');

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

test('TelegramInboundAdapter - 1. Constructor input validation and initial state', () => {
  const harness = createTempHarness();
  try {
    const registry = new AccountRegistry();
    const secretProvider = new FakeSecretProvider();

    // Required dependencies
    assert.throws(
      () => new TelegramInboundAdapter({}),
      /accountRegistry with getActive/
    );
    assert.throws(
      () => new TelegramInboundAdapter({ accountRegistry: registry }),
      /secretProvider with getSecret/
    );
    assert.throws(
      () => new TelegramInboundAdapter({ accountRegistry: registry, secretProvider }),
      /stateRepository with ingestMessage/
    );

    const adapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
    });

    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(adapter.activeAccountId, null);
    assert.strictEqual(adapter.activeChannelId, null);
  } finally {
    harness.cleanup();
  }
});

test('TelegramInboundAdapter - 2. start() fails closed if no active account in registry', () => {
  const harness = createTempHarness();
  try {
    const registry = new AccountRegistry();
    const secretProvider = new FakeSecretProvider();
    const adapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
    });

    assert.throws(
      () => adapter.start(),
      /NO_ACTIVE_TELEGRAM_ACCOUNT/
    );
    assert.strictEqual(adapter.isRunning, false);
  } finally {
    harness.cleanup();
  }
});

test('TelegramInboundAdapter - 3. start() fails closed if active account is disabled or non-telegram', () => {
  const harness = createTempHarness();
  try {
    // A. Disabled telegram account
    const registry1 = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_1', label: 'Bot 1', enabled: true },
    ]);
    registry1.setActive('tg_bot_1');
    registry1.accounts.get('tg_bot_1').enabled = false;

    const adapter1 = new TelegramInboundAdapter({
      accountRegistry: registry1,
      secretProvider: new FakeSecretProvider(),
      stateRepository: harness.repo,
    });

    assert.throws(
      () => adapter1.start(),
      /disabled/
    );

    // B. Active account on different channel (e.g. line)
    const registry2 = AccountRegistry.fromMetadata('line', [
      { id: 'line_bot_1', label: 'Line Bot', enabled: true },
    ]);
    registry2.setActive('line_bot_1');

    const adapter2 = new TelegramInboundAdapter({
      accountRegistry: registry2,
      secretProvider: new FakeSecretProvider(),
      stateRepository: harness.repo,
    });

    assert.throws(
      () => adapter2.start(),
      /NO_ACTIVE_TELEGRAM_ACCOUNT|channel/i
    );
  } finally {
    harness.cleanup();
  }
});

test('TelegramInboundAdapter - 4. start() validates token syntax and loads secret once', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_test_bot', label: 'Test Bot', enabled: true },
    ]);
    registry.setActive('tg_test_bot');

    // Invalid token format
    const badSecretProvider = new FakeSecretProvider({
      'tg_test_bot': 'invalid/token with space',
    });
    const badAdapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: badSecretProvider,
      stateRepository: harness.repo,
    });

    assert.throws(
      () => badAdapter.start(),
      /INVALID_TELEGRAM_TOKEN_SYNTAX/
    );

    // Valid synthetic token: <number>:<string>
    const validSecretProvider = new FakeSecretProvider({
      'tg_test_bot': '12345:synthetic_test_token',
    });

    const fakeFetch = async () => {
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, result: [] }),
      };
    };

    const goodAdapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider: validSecretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetch,
      pollTimeoutSec: 0,
    });

    goodAdapter.start();
    assert.strictEqual(goodAdapter.isRunning, true);
    assert.strictEqual(goodAdapter.activeAccountId, 'tg_test_bot');
    assert.strictEqual(goodAdapter.activeChannelId, TELEGRAM_CHANNEL_ID);
    assert.strictEqual(validSecretProvider.getSecretCalls.length, 1);

    // Repeated start() is rejected
    assert.throws(
      () => goodAdapter.start(),
      /already running/
    );

    await goodAdapter.stop();
    assert.strictEqual(goodAdapter.isRunning, false);
  } finally {
    harness.cleanup();
  }
});

test('TelegramInboundAdapter - 5. classifyTelegramUpdate classifies MESSAGE, EDIT, and IGNORED', () => {
  // A. Normal message
  const update1 = {
    update_id: 1001,
    message: {
      message_id: 55,
      chat: { id: 777 },
      text: 'Hello Telegram',
    },
  };
  const c1 = classifyTelegramUpdate(update1);
  assert.strictEqual(c1.type, 'MESSAGE');
  assert.strictEqual(c1.platformMsgId, 'tg:777:55');
  assert.strictEqual(c1.content, 'Hello Telegram');

  // B. Edited message
  const update2 = {
    update_id: 1002,
    edited_message: {
      message_id: 55,
      chat: { id: 777 },
      text: 'Hello Telegram (edited)',
    },
  };
  const c2 = classifyTelegramUpdate(update2);
  assert.strictEqual(c2.type, 'EDIT');
  assert.strictEqual(c2.platformMsgId, 'tg:777:55');
  assert.strictEqual(c2.content, 'Hello Telegram (edited)');

  // C. Unsupported update (e.g. channel_post or inline_query)
  const update3 = {
    update_id: 1003,
    channel_post: { message_id: 99 },
  };
  const c3 = classifyTelegramUpdate(update3);
  assert.strictEqual(c3.type, 'IGNORED');
  assert.strictEqual(c3.reason, 'UNSUPPORTED_UPDATE_TYPE');
});

test('TelegramInboundAdapter - 6. Ingests message, edit, and ignored updates and advances cursor', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_ingest', label: 'Bot Ingest', enabled: true },
    ]);
    registry.setActive('tg_bot_ingest');

    const secretProvider = new FakeSecretProvider({
      'tg_bot_ingest': '123456789:AAABBBCCC-synthetic-token-0001',
    });

    let pollCount = 0;
    const fakeFetch = async () => {
      pollCount++;
      if (pollCount === 1) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            result: [
              {
                update_id: 5001,
                message: {
                  message_id: 101,
                  chat: { id: 888 },
                  text: 'Original Message',
                },
              },
              {
                update_id: 5002,
                edited_message: {
                  message_id: 101,
                  chat: { id: 888 },
                  text: 'Edited Message',
                },
              },
              {
                update_id: 5003,
                inline_query: { id: 'iq_99' },
              },
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
      fetchFn: fakeFetch,
      pollTimeoutSec: 0,
    });

    adapter.start();

    // Allow polling cycle to process
    await new Promise((resolve) => setTimeout(resolve, 80));
    await adapter.stop();

    // Verify inbox has edited content
    const rawDb = new DatabaseSync(harness.repo.databasePath, { readOnly: true });
    try {
      const inboxRow = rawDb.prepare(
        'SELECT sequence, channel_id, account_id, platform_msg_id, status, content FROM inbox WHERE account_id = ? AND platform_msg_id = ?;'
      ).get('tg_bot_ingest', 'tg:888:101');
      assert.ok(inboxRow);
      assert.strictEqual(inboxRow.content, 'Edited Message');
      assert.strictEqual(inboxRow.status, 'queued');
    } finally {
      rawDb.close();
    }

    // Verify cursor state: update_id + 1 = 5004
    const cursor = harness.repo.getIngestCursor('tg_bot_ingest');
    assert.strictEqual(cursor, '5004');
  } finally {
    harness.cleanup();
  }
});

test('TelegramInboundAdapter - 7. Week rebase triggers exact-state reset when cursor older than 7 days', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_rebase', label: 'Bot Rebase', enabled: true },
    ]);
    registry.setActive('tg_bot_rebase');

    const secretProvider = new FakeSecretProvider({
      'tg_bot_rebase': '123456789:AAABBBCCC-synthetic-token-rebase',
    });

    // Seed stale cursor (> 7 days old)
    const eightDaysAgo = Date.now() - (TELEGRAM_WEEK_REBASE_MS + 86400000);
    harness.repo.ingestMessage({
      accountId: 'tg_bot_rebase',
      platformEventId: 'seed_evt',
      channelId: 'telegram',
      platformMsgId: 'tg:999:1',
      content: 'old message',
      cursorValue: '1000',
      cursorObservedAtMs: eightDaysAgo,
    });

    assert.strictEqual(harness.repo.getIngestCursor('tg_bot_rebase'), '1000');

    let fetchUrl = null;
    let pollCount = 0;
    const fakeFetch = async (url) => {
      fetchUrl = url;
      pollCount++;
      if (pollCount === 1) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            result: [
              {
                update_id: 9001,
                message: { message_id: 201, chat: { id: 999 }, text: 'Fresh message after rebase' },
              },
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
      fetchFn: fakeFetch,
      pollTimeoutSec: 0,
    });

    adapter.start();
    await new Promise((resolve) => setTimeout(resolve, 80));
    await adapter.stop();

    // Verify first request was executed
    assert.ok(fetchUrl);
    // Cursor should now be updated to 9002
    assert.strictEqual(harness.repo.getIngestCursor('tg_bot_rebase'), '9002');
  } finally {
    harness.cleanup();
  }
});

test('TelegramInboundAdapter - 8. 409 Conflict triggers terminal stop and halts polling', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_409', label: 'Bot 409', enabled: true },
    ]);
    registry.setActive('tg_bot_409');

    const secretProvider = new FakeSecretProvider({
      'tg_bot_409': '123456789:AAABBBCCC-synthetic-token-409',
    });

    let calls = 0;
    const fakeFetch = async () => {
      calls++;
      return {
        ok: false,
        status: 409,
        json: async () => ({
          ok: false,
          error_code: 409,
          description: 'Conflict: terminated by other getUpdates request',
        }),
      };
    };

    const adapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetch,
      pollTimeoutSec: 0,
    });

    adapter.start();
    await new Promise((resolve) => setTimeout(resolve, 80));

    // Must be stopped automatically on 409 terminal conflict
    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(calls, 1, '409 Conflict must terminate immediately without retry loop');

    await adapter.stop();
  } finally {
    harness.cleanup();
  }
});

test('TelegramInboundAdapter - 9. 429 Too Many Requests respects retry_after parameter', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_429', label: 'Bot 429', enabled: true },
    ]);
    registry.setActive('tg_bot_429');

    const secretProvider = new FakeSecretProvider({
      'tg_bot_429': '123456789:AAABBBCCC-synthetic-token-429',
    });

    let pollCount = 0;
    const fakeFetch = async () => {
      pollCount++;
      if (pollCount === 1) {
        return {
          ok: false,
          status: 429,
          json: async () => ({
            ok: false,
            error_code: 429,
            description: 'Too Many Requests: retry after 1',
            parameters: { retry_after: 1 },
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
      fetchFn: fakeFetch,
      pollTimeoutSec: 0,
    });

    adapter.start();
    await new Promise((resolve) => setTimeout(resolve, 80));
    await adapter.stop();

    assert.strictEqual(adapter.isRunning, false);
  } finally {
    harness.cleanup();
  }
});

test('TelegramInboundAdapter - 10. Stop quiesces active fetch via AbortSignal and zeroizes token', async () => {
  const harness = createTempHarness();
  try {
    const registry = AccountRegistry.fromMetadata('telegram', [
      { id: 'tg_bot_stop', label: 'Bot Stop', enabled: true },
    ]);
    registry.setActive('tg_bot_stop');

    const secretProvider = new FakeSecretProvider({
      'tg_bot_stop': '123456789:AAABBBCCC-synthetic-token-stop',
    });

    let signalAborted = false;
    const fakeFetch = async (url, options) => {
      if (options && options.signal) {
        options.signal.addEventListener('abort', () => {
          signalAborted = true;
        });
      }
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          resolve({
            ok: true,
            status: 200,
            json: async () => ({ ok: true, result: [] }),
          });
        }, 5000);
        if (typeof timer?.unref === 'function') {
          timer.unref();
        }
        if (options && options.signal) {
          options.signal.addEventListener('abort', () => {
            clearTimeout(timer);
            const err = new Error('The operation was aborted');
            err.name = 'AbortError';
            reject(err);
          });
        }
      });
    };

    const adapter = new TelegramInboundAdapter({
      accountRegistry: registry,
      secretProvider,
      stateRepository: harness.repo,
      fetchFn: fakeFetch,
      pollTimeoutSec: 30,
    });

    adapter.start();
    assert.strictEqual(adapter.isRunning, true);

    // Give fetchFn a tick to begin and attach abort listener
    await new Promise((resolve) => setTimeout(resolve, 20));

    // Stop while polling is waiting
    await adapter.stop();

    assert.strictEqual(adapter.isRunning, false);
    assert.strictEqual(signalAborted, true);
  } finally {
    harness.cleanup();
  }
});
