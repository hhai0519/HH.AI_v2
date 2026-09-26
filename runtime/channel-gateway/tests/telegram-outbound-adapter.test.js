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
  const returnedBuffers = [];
  return {
    get calls() {
      return calls;
    },
    get returnedBuffers() {
      return returnedBuffers;
    },
    set fail(val) {
      fail = val;
    },
    getSecret: async () => {
      calls++;
      if (fail) {
        throw new Error('Secret retrieval failed');
      }
      const buf = Buffer.from(token, 'utf8');
      returnedBuffers.push(buf);
      return buf;
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
    endpoint_operation: 'sendMessage',
    message_type: 'text',
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
    endpoint_operation: 'sendMessage',
    message_type: 'text',
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
      endpoint_operation: 'sendMessage',
      message_type: 'text',
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
      endpoint_operation: 'sendMessage',
      message_type: 'text',
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
        endpoint_operation: 'sendMessage',
        message_type: 'text',
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
      endpoint_operation: 'sendMessage',
      message_type: 'text',
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
      endpoint_operation: 'sendMessage',
      message_type: 'text',
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
      endpoint_operation: 'sendMessage',
      message_type: 'text',
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
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'msg 1',
    });
    assert.strictEqual(sec.calls, 1);

    // Command 2 & 3 reuse token
    await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'msg 2',
    });
    await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'msg 3',
    });
    assert.strictEqual(sec.calls, 1);

    const tokenBufA = sec.returnedBuffers[0];
    assert.ok(tokenBufA.some(b => b !== 0));

    // Switch active account
    reg.setActive({ id: 'bot_beta', channel: 'telegram', enabled: true });

    // Old account command rejected pre-network, zeroizes cached buffer, does not load token
    const oldRes = await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'old account msg',
    });
    assert.strictEqual(oldRes.error_code, 'ACCOUNT_MISMATCH_PRE_REQUEST');
    assert.strictEqual(sec.calls, 1);
    assert.ok(tokenBufA.every(b => b === 0), 'Stale token buffer A must be zeroized');
    assert.strictEqual(adapter.cachedAccountId, null);

    // New account command loads new token
    const newRes = await adapter.deliver({
      account_id: 'bot_beta',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
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
        endpoint_operation: 'sendMessage',
        message_type: 'text',
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
        endpoint_operation: 'sendMessage',
        message_type: 'text',
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
        endpoint_operation: 'sendMessage',
        message_type: 'text',
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
        endpoint_operation: 'sendMessage',
        message_type: 'text',
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
        endpoint_operation: 'sendMessage',
        message_type: 'text',
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
        endpoint_operation: 'sendMessage',
        message_type: 'text',
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
        endpoint_operation: 'sendMessage',
        message_type: 'text',
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
      endpoint_operation: 'sendMessage',
      message_type: 'text',
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

test('F3 command boundary: platform, endpoint_operation, message_type fail closed before secret/network', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry();
  const sec = createFakeSecretProvider();
  let fetchCalls = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCalls++;
      return { status: 200, text: async () => JSON.stringify({ ok: true, result: { message_id: 1 } }) };
    },
  });
  adapter.start();
  try {
    // 1. platform = 'line' -> 0 secret, 0 network, TELEGRAM_CLIENT_ERROR_400
    const resLine = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'line',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '123456',
      body: 'hello',
    });
    assert.strictEqual(resLine.transport_phase, 'NOT_SENT');
    assert.strictEqual(resLine.success, false);
    assert.strictEqual(resLine.error_code, 'TELEGRAM_CLIENT_ERROR_400');
    assert.strictEqual(resLine.http_status, 400);
    assert.strictEqual(sec.calls, 0);
    assert.strictEqual(fetchCalls, 0);

    // 2. wrong endpoint_operation -> 0 secret, 0 network
    const resOp = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'telegram',
      endpoint_operation: 'editMessageText',
      message_type: 'text',
      recipient: '123456',
      body: 'hello',
    });
    assert.strictEqual(resOp.transport_phase, 'NOT_SENT');
    assert.strictEqual(resOp.success, false);
    assert.strictEqual(resOp.error_code, 'TELEGRAM_CLIENT_ERROR_400');
    assert.strictEqual(resOp.http_status, 400);
    assert.strictEqual(sec.calls, 0);
    assert.strictEqual(fetchCalls, 0);

    // 3. message_type != text -> 0 secret, 0 network
    const resType = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'image',
      recipient: '123456',
      body: 'hello',
    });
    assert.strictEqual(resType.transport_phase, 'NOT_SENT');
    assert.strictEqual(resType.success, false);
    assert.strictEqual(resType.error_code, 'TELEGRAM_CLIENT_ERROR_400');
    assert.strictEqual(resType.http_status, 400);
    assert.strictEqual(sec.calls, 0);
    assert.strictEqual(fetchCalls, 0);

    // 4. Missing boundary fields
    const resMissing = await adapter.deliver({
      account_id: 'tg_bot_1',
      recipient: '123456',
      body: 'hello',
    });
    assert.strictEqual(resMissing.transport_phase, 'NOT_SENT');
    assert.strictEqual(resMissing.success, false);
    assert.strictEqual(resMissing.error_code, 'TELEGRAM_CLIENT_ERROR_400');
    assert.strictEqual(resMissing.http_status, 400);
    assert.strictEqual(sec.calls, 0);
    assert.strictEqual(fetchCalls, 0);

    // 5. Canonical telegram / sendMessage / text -> existing behavior unchanged
    const resOk = await adapter.deliver({
      account_id: 'tg_bot_1',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '123456',
      body: 'hello',
    });
    assert.strictEqual(resOk.success, true);
    assert.strictEqual(sec.calls, 1);
    assert.strictEqual(fetchCalls, 1);
  } finally {
    await adapter.stop();
  }
});

test('F1: Stale token zeroization when active account switches or becomes inactive', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'bot_alpha', channel: 'telegram', enabled: true });
  const sec = createFakeSecretProvider('12345:TOKEN_A');
  let fetchCount = 0;

  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCount++;
      return {
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 10 } }),
      };
    },
  });
  adapter.start();
  try {
    // 1. Deliver for bot_alpha -> token cached
    const res1 = await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'msg alpha',
    });
    assert.strictEqual(res1.success, true);
    assert.strictEqual(sec.calls, 1);
    assert.strictEqual(fetchCount, 1);
    assert.strictEqual(adapter.cachedAccountId, 'bot_alpha');

    const tokenBufA = sec.returnedBuffers[0];
    assert.ok(tokenBufA.some(b => b !== 0), 'Buffer must initially contain non-zero bytes');

    // 2. Active switch to bot_beta -> stale bot_alpha command
    reg.setActive({ id: 'bot_beta', channel: 'telegram', enabled: true });

    const resStaleA = await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'stale alpha msg',
    });
    assert.strictEqual(resStaleA.transport_phase, 'NOT_SENT');
    assert.strictEqual(resStaleA.error_code, 'ACCOUNT_MISMATCH_PRE_REQUEST');

    // Immediate assert old A Buffer every byte == 0
    assert.ok(tokenBufA.every(b => b === 0), 'Stale token buffer A must be zeroized');
    assert.strictEqual(adapter.cachedAccountId, null);
    assert.strictEqual(sec.calls, 1, 'getSecret count unchanged (no new secret lookup)');
    assert.strictEqual(fetchCount, 1, 'fetch count unchanged (no network call)');

    // 3. Re-cache for bot_beta
    const resB = await adapter.deliver({
      account_id: 'bot_beta',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'msg beta',
    });
    assert.strictEqual(resB.success, true);
    assert.strictEqual(sec.calls, 2);
    assert.strictEqual(fetchCount, 2);
    assert.strictEqual(adapter.cachedAccountId, 'bot_beta');
    const tokenBufB = sec.returnedBuffers[1];
    assert.ok(tokenBufB.some(b => b !== 0));

    // 4. Active account becomes null -> observation clears stale token
    reg.setActive(null);
    const resNull = await adapter.deliver({
      account_id: 'bot_beta',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'msg when null',
    });
    assert.strictEqual(resNull.transport_phase, 'NOT_SENT');
    assert.strictEqual(resNull.error_code, 'ACCOUNT_MISMATCH_PRE_REQUEST');
    assert.ok(tokenBufB.every(b => b === 0), 'Token B must be zeroized when active is null');
    assert.strictEqual(adapter.cachedAccountId, null);

    // 5. Re-cache for bot_alpha, then active becomes disabled
    reg.setActive({ id: 'bot_alpha', channel: 'telegram', enabled: true });
    await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'msg alpha 2',
    });
    assert.strictEqual(adapter.cachedAccountId, 'bot_alpha');
    const tokenBufA2 = sec.returnedBuffers[2];
    assert.ok(tokenBufA2.some(b => b !== 0));

    reg.setActive({ id: 'bot_alpha', channel: 'telegram', enabled: false });
    const resDisabled = await adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'msg when disabled',
    });
    assert.strictEqual(resDisabled.transport_phase, 'NOT_SENT');
    assert.strictEqual(resDisabled.error_code, 'ACCOUNT_MISMATCH_PRE_REQUEST');
    assert.ok(tokenBufA2.every(b => b === 0), 'Token A2 must be zeroized when active is disabled');
    assert.strictEqual(adapter.cachedAccountId, null);
  } finally {
    await adapter.stop();
  }
});

test('F1: Post-request active account change preserves MAY_HAVE_BEEN_SENT and immediately zeroizes old token', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'bot_alpha', channel: 'telegram', enabled: true });
  const sec = createFakeSecretProvider('12345:TOKEN_A');
  let fetchStarted = false;
  let triggerSwitch = null;
  const switchTriggered = new Promise((resolve) => { triggerSwitch = resolve; });

  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchStarted = true;
      triggerSwitch();
      // Wait slightly so test switches active account
      await new Promise(r => setTimeout(r, 40));
      return {
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 99 } }),
      };
    },
  });
  adapter.start();
  try {
    const deliverPromise = adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'mid-flight test',
    });

    await switchTriggered;
    // Transport has started -> switch active account to bot_beta
    reg.setActive({ id: 'bot_beta', channel: 'telegram', enabled: true });

    const res = await deliverPromise;
    assert.strictEqual(fetchStarted, true);
    assert.strictEqual(res.transport_phase, 'MAY_HAVE_BEEN_SENT');
    assert.strictEqual(res.success, false);

    const tokenBuf = sec.returnedBuffers[0];
    assert.ok(tokenBuf.every(b => b === 0), 'Old token buffer must be zeroized in post-request uncertainty path');
    assert.strictEqual(adapter.cachedAccountId, null);
    assert.strictEqual(sec.calls, 1, 'Zero B-token lookup');
  } finally {
    await adapter.stop();
  }
});

function createDeferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test('F4-T1: Active account switch during pending getSecret prevents request and zeroizes token', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'bot_alpha', channel: 'telegram', enabled: true });
  let secretCallCount = 0;
  const deferredSecret = createDeferred();
  const tokenBufA = Buffer.from('123456:ABC-DEF_ghi', 'utf8');

  const sec = {
    getSecret: async () => {
      secretCallCount++;
      return deferredSecret.promise;
    },
  };

  let fetchCalls = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCalls++;
      return {
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 1 } }),
      };
    },
  });

  adapter.start();
  try {
    const deliverPromise = adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'test msg',
    });

    while (secretCallCount === 0) {
      await new Promise(r => setImmediate(r));
    }

    // Switch active account A -> B while getSecret is pending
    reg.setActive({ id: 'bot_beta', channel: 'telegram', enabled: true });

    // Resolve old A token Buffer
    deferredSecret.resolve(tokenBufA);

    const result = await deliverPromise;

    assert.strictEqual(fetchCalls, 0, 'fetchCount must be 0');
    assert.strictEqual(result.transport_phase, 'NOT_SENT');
    assert.strictEqual(result.error_code, 'ACCOUNT_MISMATCH_PRE_REQUEST');
    assert.strictEqual(result.success, false);
    assert.ok(tokenBufA.every(b => b === 0), 'old returned Buffer every byte == 0');
    assert.strictEqual(adapter.cachedAccountId, null, 'cachedAccountId must be null');
    assert.strictEqual(secretCallCount, 1, 'no B token lookup');
  } finally {
    await adapter.stop();
  }
});

test('F4-T2: getSecret rejection after account switch yields ACCOUNT_MISMATCH_PRE_REQUEST over secret failure', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'bot_alpha', channel: 'telegram', enabled: true });
  let secretCallCount = 0;
  const deferredSecret = createDeferred();

  const sec = {
    getSecret: async () => {
      secretCallCount++;
      return deferredSecret.promise;
    },
  };

  let fetchCalls = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCalls++;
      return {
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 1 } }),
      };
    },
  });

  adapter.start();
  try {
    const deliverPromise = adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'test msg',
    });

    while (secretCallCount === 0) {
      await new Promise(r => setImmediate(r));
    }

    // Switch active account A -> B
    reg.setActive({ id: 'bot_beta', channel: 'telegram', enabled: true });

    // Reject getSecret
    deferredSecret.reject(new Error('KMS provider failure'));

    const result = await deliverPromise;

    assert.strictEqual(fetchCalls, 0, 'zero network');
    assert.strictEqual(result.transport_phase, 'NOT_SENT');
    assert.strictEqual(result.error_code, 'ACCOUNT_MISMATCH_PRE_REQUEST');
    assert.notStrictEqual(result.error_code, 'TELEGRAM_SECRET_UNAVAILABLE');
    assert.strictEqual(result.success, false);
    assert.strictEqual(adapter.cachedAccountId, null);
  } finally {
    await adapter.stop();
  }
});

test('F5-T1: stop() waits for pending getSecret and quiesces without request', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'bot_alpha', channel: 'telegram', enabled: true });
  let secretCallCount = 0;
  const deferredSecret = createDeferred();
  const tokenBufA = Buffer.from('123456:ABC-DEF_ghi', 'utf8');

  const sec = {
    getSecret: async () => {
      secretCallCount++;
      return deferredSecret.promise;
    },
  };

  let fetchCalls = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCalls++;
      return {
        status: 200,
        text: async () => JSON.stringify({ ok: true, result: { message_id: 1 } }),
      };
    },
  });

  adapter.start();

  const deliverPromise = adapter.deliver({
    account_id: 'bot_alpha',
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    message_type: 'text',
    recipient: '100',
    body: 'test msg',
  });

  while (secretCallCount === 0) {
    await new Promise(r => setImmediate(r));
  }

  // Call adapter.stop() while getSecret remains pending
  let stopCompleted = false;
  const stopPromise = adapter.stop().then(() => {
    stopCompleted = true;
  });

  // Verify stop does not complete prematurely while getSecret is pending
  await new Promise(r => setImmediate(r));
  assert.strictEqual(stopCompleted, false, 'stop must not complete prematurely while getSecret is pending');

  // Resolve old token
  deferredSecret.resolve(tokenBufA);

  const deliverResult = await deliverPromise;
  await stopPromise;

  assert.strictEqual(stopCompleted, true, 'stop completes after deliver quiesces');
  assert.strictEqual(fetchCalls, 0, 'no fetch');
  assert.ok(tokenBufA.every(b => b === 0), 'Buffer zeroized');
  assert.strictEqual(deliverResult.transport_phase, 'NOT_SENT');
  assert.strictEqual(deliverResult.success, false);
});

test('F5-T2: Account switch during pending response.text() rejects body read and zeroizes cached token', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'bot_alpha', channel: 'telegram', enabled: true });
  const sec = createFakeSecretProvider('123456:ABC-DEF_ghi');
  const deferredText = createDeferred();

  let fetchCalls = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async () => {
      fetchCalls++;
      return {
        status: 200,
        text: () => deferredText.promise,
      };
    },
  });

  adapter.start();
  try {
    const deliverPromise = adapter.deliver({
      account_id: 'bot_alpha',
      platform: 'telegram',
      endpoint_operation: 'sendMessage',
      message_type: 'text',
      recipient: '100',
      body: 'test msg',
    });

    while (fetchCalls === 0) {
      await new Promise(r => setImmediate(r));
    }

    // While response.text pending: switch A -> B and reject body read
    reg.setActive({ id: 'bot_beta', channel: 'telegram', enabled: true });
    deferredText.reject(new Error('Connection reset while reading body'));

    const result = await deliverPromise;

    assert.strictEqual(result.transport_phase, 'MAY_HAVE_BEEN_SENT');
    assert.strictEqual(result.success, false);
    const tokenBuf = sec.returnedBuffers[0];
    assert.ok(tokenBuf.every(b => b === 0), 'old token Buffer zeroized');
    assert.strictEqual(adapter.cachedAccountId, null, 'cachedAccountId null');
    assert.strictEqual(sec.calls, 1, 'no B token lookup');
  } finally {
    await adapter.stop();
  }
});

test('F5-T3: stop() during response.text() aborts controller, waits for delivery settlement, and zeroizes token', { timeout: 10000 }, async () => {
  const reg = createFakeRegistry({ id: 'bot_alpha', channel: 'telegram', enabled: true });
  const sec = createFakeSecretProvider('123456:ABC-DEF_ghi');
  let textReadStarted = false;

  let fetchCalls = 0;
  const adapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: async (url, options) => {
      fetchCalls++;
      return {
        status: 200,
        text: () => {
          textReadStarted = true;
          return new Promise((resolve, reject) => {
            if (options.signal && options.signal.aborted) {
              const err = new Error('The operation was aborted');
              err.name = 'AbortError';
              return reject(err);
            }
            if (options.signal) {
              options.signal.addEventListener('abort', () => {
                const err = new Error('The operation was aborted');
                err.name = 'AbortError';
                reject(err);
              });
            }
          });
        },
      };
    },
  });

  adapter.start();

  let deliverSettled = false;
  const deliverPromise = adapter.deliver({
    account_id: 'bot_alpha',
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    message_type: 'text',
    recipient: '100',
    body: 'test msg',
  }).finally(() => {
    deliverSettled = true;
  });

  while (!textReadStarted) {
    await new Promise(r => setImmediate(r));
  }

  let stopCompleted = false;
  const stopPromise = adapter.stop().then(() => {
    stopCompleted = true;
    assert.strictEqual(deliverSettled, true, 'deliver must be settled when stop completes');
  });

  const deliverResult = await deliverPromise;
  await stopPromise;

  assert.strictEqual(stopCompleted, true, 'stop waits for complete delivery settlement');
  assert.strictEqual(deliverResult.transport_phase, 'MAY_HAVE_BEEN_SENT');
  assert.strictEqual(deliverResult.success, false);

  const tokenBuf = sec.returnedBuffers[0];
  assert.ok(tokenBuf.every(b => b === 0), 'final zeroization occurs');
  assert.strictEqual(adapter.cachedAccountId, null);

  // Assert no post-stop new request occurs
  const postStopResult = await adapter.deliver({
    account_id: 'bot_alpha',
    platform: 'telegram',
    endpoint_operation: 'sendMessage',
    message_type: 'text',
    recipient: '100',
    body: 'after stop',
  });
  assert.strictEqual(postStopResult.transport_phase, 'NOT_SENT');
  assert.strictEqual(postStopResult.error_code, 'ADAPTER_NOT_RUNNING');
  assert.strictEqual(fetchCalls, 1, 'no post-stop new request occurs');
});

