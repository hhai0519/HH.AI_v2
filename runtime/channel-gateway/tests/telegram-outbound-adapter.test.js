/**
 * runtime/channel-gateway/tests/telegram-outbound-adapter.test.js
 *
 * TG-MVP-13: Telegram Outbound Adapter Unit Test Suite.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  TelegramOutboundAdapter,
  TELEGRAM_CHANNEL_ID,
  NOT_SENT_CAUSE_CODES,
} = require('../adapters/telegram-outbound-adapter');

function createFakeRegistry(account = { id: 'tg_bot_1', channel: 'telegram', enabled: true }) {
  let active = account;
  return {
    getActive: () => active,
    setActive: (newAccount) => {
      active = newAccount;
    },
  };
}

function createFakeSecretProvider(token = '123456:ABC-DEF_ghi') {
  let calls = 0;
  let fail = false;
  return {
    get calls() {
      return calls;
    },
    set fail(val) {
      fail = val;
    },
    getSecret: async () => {
      calls++;
      if (fail) {
        throw new Error('Secret retrieval failed');
      }
      return Buffer.from(token, 'utf8');
    },
  };
}

test('Constructor options allowlist and parameter validation', { timeout: 10000 }, () => {
  const reg = createFakeRegistry();
  const sec = createFakeSecretProvider();

  assert.throws(
    () => new TelegramOutboundAdapter(null),
    TypeError
  );

  assert.throws(
    () => new TelegramOutboundAdapter({ accountRegistry: reg, secretProvider: sec, unknownOption: 123 }),
    /Unknown constructor option: 'unknownOption'/
  );

  assert.throws(
    () => new TelegramOutboundAdapter({ secretProvider: sec }),
    /accountRegistry with getActive\(\) is required/
  );

  assert.throws(
    () => new TelegramOutboundAdapter({ accountRegistry: reg }),
    /secretProvider with getSecret\(\) is required/
  );

  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
  });
  assert.strictEqual(adapter.isRunning, false);
});

test('start() and stop() lifecycle and token zeroization', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry();
  const sec = createFakeSecretProvider('12345:TOKEN_abc');

  let fetchCalled = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCalled++;
      return {
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 1 } }),
      };
    },
  });

  // start() does not eagerly load token
  adapter.start();
  assert.strictEqual(adapter.isRunning, true);
  assert.strictEqual(sec.calls, 0);

  // deliver loads token
  const res = await adapter.deliver({
    account_id: 'tg_bot_1',
    platform: 'telegram',
    recipient: '123456',
    body: 'hello',
  });
  assert.strictEqual(res.success, true);
  assert.strictEqual(sec.calls, 1);
  assert.strictEqual(adapter.cachedAccountId, 'tg_bot_1');

  // stop() clears and zeroizes
  await adapter.stop();
  assert.strictEqual(adapter.isRunning, false);
  assert.strictEqual(adapter.cachedAccountId, null);

  // deliver after stop returns ADAPTER_NOT_RUNNING
  const postStopRes = await adapter.deliver({
    account_id: 'tg_bot_1',
    platform: 'telegram',
    recipient: '123456',
    body: 'hello',
  });
  assert.strictEqual(postStopRes.error_code, 'ADAPTER_NOT_RUNNING');
});

test('Strict Native Reply (D-R3-REPLY-A): reply_parameters formatting and validation', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry();
  const sec = createFakeSecretProvider('12345:TOKEN_abc');

  let sentBody = null;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async (_url, options) => {
      sentBody = JSON.parse(options.body);
      return {
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 42 } }),
      };
    },
  });
  adapter.start();

  try {
    // Valid reply target
    const res = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'telegram',
      recipient: '98765',
      logical_reply_target: 'tg:98765:1001',
      body: 'Replying to message 1001',
    });

    assert.strictEqual(res.success, true);
    assert.deepStrictEqual(sentBody, {
      chat_id: '98765',
      text: 'Replying to message 1001',
      reply_parameters: {
        message_id: 1001,
      },
    });
    assert.strictEqual('parse_mode' in sentBody, false);
    assert.strictEqual('allow_sending_without_reply' in sentBody, false);

    // Mismatched chat_id in reply target -> 0 network + TELEGRAM_REPLY_TARGET_INVALID
    sentBody = null;
    const mismatchRes = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'telegram',
      recipient: '98765',
      logical_reply_target: 'tg:88888:1001',
      body: 'Chat mismatch',
    });
    assert.strictEqual(mismatchRes.transport_phase, 'NOT_SENT');
    assert.strictEqual(mismatchRes.error_code, 'TELEGRAM_REPLY_TARGET_INVALID');
    assert.strictEqual(sentBody, null);

    // Malformed reply target -> 0 network
    for (const badTarget of ['invalid', 'tg:98765:', 'tg:abc:123', 'tg:98765:-5', 'tg:98765:0']) {
      const badRes = await adapter.deliver({
        account_id: 'tg_bot_1',
        platform: 'telegram',
        recipient: '98765',
        logical_reply_target: badTarget,
        body: 'Malformed target',
      });
      assert.strictEqual(badRes.transport_phase, 'NOT_SENT');
      assert.strictEqual(badRes.error_code, 'TELEGRAM_REPLY_TARGET_INVALID');
    }
  } finally {
    await adapter.stop();
  }
});

test('Account mismatch pre-request -> 0 network, no token lookup', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'active_bot', channel: 'telegram', enabled: true });
  const sec = createFakeSecretProvider();

  let fetchCount = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCount++;
      return { status: 200, text: async () => '{}' };
    },
  });
  adapter.start();

  try {
    const res = await adapter.deliver({
      account_id: 'old_bot_account',
      platform: 'telegram',
      recipient: '123',
      body: 'hello',
    });

    assert.strictEqual(res.transport_phase, 'NOT_SENT');
    assert.strictEqual(res.error_code, 'ACCOUNT_MISMATCH_PRE_REQUEST');
    assert.strictEqual(sec.calls, 0);
    assert.strictEqual(fetchCount, 0);
  } finally {
    await adapter.stop();
  }
});

test('SecretProvider failure -> 0 network, bounded terminal code', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry();
  const sec = createFakeSecretProvider();
  sec.fail = true;

  let fetchCount = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCount++;
      return { status: 200, text: async () => '{}' };
    },
  });
  adapter.start();

  try {
    const res = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'telegram',
      recipient: '123',
      body: 'hello',
    });

    assert.strictEqual(res.transport_phase, 'NOT_SENT');
    assert.strictEqual(res.error_code, 'TELEGRAM_SECRET_UNAVAILABLE');
    assert.strictEqual(fetchCount, 0);
  } finally {
    await adapter.stop();
  }
});

test('Invalid token syntax -> zero network, zeroize, INVALID_TELEGRAM_TOKEN_SYNTAX', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry();
  const sec = createFakeSecretProvider('invalid-token-no-colon');

  let fetchCount = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCount++;
      return { status: 200, text: async () => '{}' };
    },
  });
  adapter.start();

  try {
    const res = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'telegram',
      recipient: '123',
      body: 'hello',
    });

    assert.strictEqual(res.transport_phase, 'NOT_SENT');
    assert.strictEqual(res.error_code, 'INVALID_TELEGRAM_TOKEN_SYNTAX');
    assert.strictEqual(fetchCount, 0);
    assert.strictEqual(adapter.cachedAccountId, null);
  } finally {
    await adapter.stop();
  }
});

test('Token reuse for same account across N commands and zeroize on switch', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'bot_alpha', channel: 'telegram', enabled: true });
  const sec = createFakeSecretProvider('12345:TOKEN_A');

  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => ({
      status: 200,
      text: async () => JSON.stringify({ ok: true, result: { message_id: 1 } }),
    }),
  });
  adapter.start();

  try {
    // Command 1 loads token
    await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      recipient: '100',
      body: 'msg 1',
    });
    assert.strictEqual(sec.calls, 1);

    // Command 2 & 3 reuse token
    await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      recipient: '100',
      body: 'msg 2',
    });
    await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      recipient: '100',
      body: 'msg 3',
    });
    assert.strictEqual(sec.calls, 1);

    // Switch active account
    reg.setActive({ id: 'bot_beta', channel: 'telegram', enabled: true });

    // Old account command rejected pre-network, does not load token
    const oldRes = await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      recipient: '100',
      body: 'old account msg',
    });
    assert.strictEqual(oldRes.error_code, 'ACCOUNT_MISMATCH_PRE_REQUEST');
    assert.strictEqual(sec.calls, 1);

    // New account command loads new token
    const newRes = await adapter.deliver({
      account_id: 'bot_beta',
      platform: 'telegram',
      recipient: '100',
      body: 'new account msg',
    });
    assert.strictEqual(newRes.success, true);
    assert.strictEqual(sec.calls, 2);
    assert.strictEqual(adapter.cachedAccountId, 'bot_beta');
  } finally {
    await adapter.stop();
  }
});

test('Transport error classification: narrow NOT_SENT vs MAY_HAVE_BEEN_SENT', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry();
  const sec = createFakeSecretProvider();

  // Test allowlist codes: ENOTFOUND, EAI_AGAIN, ECONNREFUSED -> NOT_SENT
  for (const code of ['ENOTFOUND', 'EAI_AGAIN', 'ECONNREFUSED']) {
    const adapter = new TelegramOutboundAdapter({
      accountRegistry: reg,
      secretProvider: sec,
      fetchFn: async () => {
        const err = new Error('network down');
        err.cause = { code };
        throw err;
      },
    });
    adapter.start();
    try {
      const res = await adapter.deliver({
        account_id: 'tg_bot_1',
        platform: 'telegram',
        recipient: '100',
        body: 'test',
      });
      assert.strictEqual(res.transport_phase, 'NOT_SENT', `code ${code} must be NOT_SENT`);
      assert.strictEqual(res.success, false);
    } finally {
      await adapter.stop();
    }
  }

  // Test uncertain codes: ECONNRESET, UND_ERR_SOCKET_TIMEOUT, AbortError, no-cause -> MAY_HAVE_BEEN_SENT
  const uncertainErrors = [
    (() => { const e = new Error('reset'); e.cause = { code: 'ECONNRESET' }; return e; })(),
    (() => { const e = new Error('timeout'); e.cause = { code: 'UND_ERR_SOCKET_TIMEOUT' }; return e; })(),
    (() => { const e = new Error('aborted'); e.name = 'AbortError'; return e; })(),
    new Error('no cause error'),
  ];

  for (const err of uncertainErrors) {
    const adapter = new TelegramOutboundAdapter({
      accountRegistry: reg,
      secretProvider: sec,
      fetchFn: async () => {
        throw err;
      },
    });
    adapter.start();
    try {
      const res = await adapter.deliver({
        account_id: 'tg_bot_1',
        platform: 'telegram',
        recipient: '100',
        body: 'test',
      });
      assert.strictEqual(res.transport_phase, 'MAY_HAVE_BEEN_SENT');
      assert.strictEqual(res.success, false);
    } finally {
      await adapter.stop();
    }
  }
});

test('HTTP Response classification: 2xx structured check, 429 retry_after, 4xx, 5xx', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry();
  const sec = createFakeSecretProvider();

  // Valid 2xx with ok: true and object result
  {
    const adapter = new TelegramOutboundAdapter({
      accountRegistry: reg,
      secretProvider: sec,
      fetchFn: async () => ({
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 123 } }),
      }),
    });
    adapter.start();
    try {
      const res = await adapter.deliver({
        account_id: 'tg_bot_1',
        platform: 'telegram',
        recipient: '100',
        body: 'valid 200',
      });
      assert.strictEqual(res.success, true);
      assert.strictEqual(res.http_status, 200);
    } finally {
      await adapter.stop();
    }
  }

  // Malformed 2xx: ok: false
  {
    const adapter = new TelegramOutboundAdapter({
      accountRegistry: reg,
      secretProvider: sec,
      fetchFn: async () => ({
        status: 200,
        text: async () => JSON.stringify({ ok: false, description: 'ambiguous' }),
      }),
    });
    adapter.start();
    try {
      const res = await adapter.deliver({
        account_id: 'tg_bot_1',
        platform: 'telegram',
        recipient: '100',
        body: 'malformed 200',
      });
      assert.strictEqual(res.success, false);
      assert.strictEqual(res.transport_phase, 'MAY_HAVE_BEEN_SENT');
    } finally {
      await adapter.stop();
    }
  }

  // 429 with retry_after in parameters
  {
    const adapter = new TelegramOutboundAdapter({
      accountRegistry: reg,
      secretProvider: sec,
      fetchFn: async () => ({
        status: 429,
        text: async () => JSON.stringify({ ok: false, parameters: { retry_after: 45 } }),
      }),
    });
    adapter.start();
    try {
      const res = await adapter.deliver({
        account_id: 'tg_bot_1',
        platform: 'telegram',
        recipient: '100',
        body: 'throttled',
      });
      assert.strictEqual(res.success, false);
      assert.strictEqual(res.http_status, 429);
      assert.strictEqual(res.retry_after, 45);
    } finally {
      await adapter.stop();
    }
  }

  // 403 Forbidden
  {
    const adapter = new TelegramOutboundAdapter({
      accountRegistry: reg,
      secretProvider: sec,
      fetchFn: async () => ({
        status: 403,
        text: async () => JSON.stringify({ ok: false, error_code: 403 }),
      }),
    });
    adapter.start();
    try {
      const res = await adapter.deliver({
        account_id: 'tg_bot_1',
        platform: 'telegram',
        recipient: '100',
        body: 'blocked',
      });
      assert.strictEqual(res.success, false);
      assert.strictEqual(res.http_status, 403);
    } finally {
      await adapter.stop();
    }
  }

  // 502 Bad Gateway
  {
    const adapter = new TelegramOutboundAdapter({
      accountRegistry: reg,
      secretProvider: sec,
      fetchFn: async () => ({
        status: 502,
        text: async () => 'Bad Gateway',
      }),
    });
    adapter.start();
    try {
      const res = await adapter.deliver({
        account_id: 'tg_bot_1',
        platform: 'telegram',
        recipient: '100',
        body: 'server error',
      });
      assert.strictEqual(res.success, false);
      assert.strictEqual(res.http_status, 502);
      assert.strictEqual(res.transport_phase, 'MAY_HAVE_BEEN_SENT');
    } finally {
      await adapter.stop();
    }
  }
});

test('Active account changes after fetch invocation preserves uncertainty', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'tg_bot_1', channel: 'telegram', enabled: true });
  const sec = createFakeSecretProvider();

  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      // Simulate account switch while request in-flight
      reg.setActive({ id: 'tg_bot_2', channel: 'telegram', enabled: true });
      return {
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 55 } }),
      };
    },
  });
  adapter.start();

  try {
    const res = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'telegram',
      recipient: '100',
      body: 'in flight switch',
    });

    // Must NOT be success, must preserve uncertainty
    assert.strictEqual(res.success, false);
    assert.strictEqual(res.transport_phase, 'MAY_HAVE_BEEN_SENT');
  } finally {
    await adapter.stop();
  }
});
