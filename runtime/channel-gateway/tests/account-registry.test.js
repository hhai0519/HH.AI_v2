/**
 * runtime/channel-gateway/tests/account-registry.test.js
 *
 * Canonical Node tests for ADR-0022 D3 / D26 non-secret account registry semantics.
 * Uses node:test and node:assert only.
 * All test fixtures and metadata are purely synthetic.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { AccountRegistry, ALLOWED_METADATA_FIELDS } = require('../core/account-registry');

test('AccountRegistry - 14. multiple registered accounts allowed', () => {
  const registry = new AccountRegistry('telegram');

  const acc1 = registry.register({
    id: 'syn-bot-alpha',
    label: 'Synthetic Alpha Bot',
    description: 'First synthetic registered bot',
    enabled: true,
  });

  const acc2 = registry.register({
    id: 'syn-bot-beta',
    label: 'Synthetic Beta Bot',
    description: 'Second synthetic registered bot',
    enabled: true,
  });

  assert.strictEqual(acc1.id, 'syn-bot-alpha');
  assert.strictEqual(acc2.id, 'syn-bot-beta');

  const all = registry.list();
  assert.strictEqual(all.length, 2);
  assert.strictEqual(all.some((a) => a.id === 'syn-bot-alpha'), true);
  assert.strictEqual(all.some((a) => a.id === 'syn-bot-beta'), true);
});

test('AccountRegistry - 15. at most one active account', () => {
  const registry = new AccountRegistry('telegram');

  registry.register({
    id: 'syn-bot-1',
    label: 'Bot 1',
    description: 'Desc 1',
    enabled: true,
  });
  registry.register({
    id: 'syn-bot-2',
    label: 'Bot 2',
    description: 'Desc 2',
    enabled: true,
  });

  assert.strictEqual(registry.getActive(), null);

  registry.setActive('syn-bot-1');
  const active1 = registry.getActive();
  assert.strictEqual(active1.id, 'syn-bot-1');
  assert.strictEqual(active1.isActive, true);

  // Exactly one active account: activating second switches active
  registry.setActive('syn-bot-2');
  const active2 = registry.getActive();
  assert.strictEqual(active2.id, 'syn-bot-2');
  assert.strictEqual(active2.isActive, true);

  // List confirms only one has isActive: true
  const list = registry.list();
  const activeCount = list.filter((a) => a.isActive).length;
  assert.strictEqual(activeCount, 1);
});

test('AccountRegistry - 16. disabled account cannot become active', () => {
  const registry = new AccountRegistry('telegram');

  registry.register({
    id: 'syn-bot-disabled',
    label: 'Disabled Bot',
    description: 'Formal bot awaiting cutover',
    enabled: false,
  });

  assert.throws(
    () => {
      registry.setActive('syn-bot-disabled');
    },
    {
      message: /Cannot activate disabled account 'syn-bot-disabled'/,
    }
  );

  assert.strictEqual(registry.getActive(), null);
});

test('AccountRegistry - 17. switching active metadata clears previous active state', () => {
  const registry = new AccountRegistry('telegram');

  registry.register({
    id: 'bot-a',
    label: 'Bot A',
    description: 'Desc A',
    enabled: true,
  });
  registry.register({
    id: 'bot-b',
    label: 'Bot B',
    description: 'Desc B',
    enabled: true,
  });

  registry.setActive('bot-a');
  assert.strictEqual(registry.get('bot-a').isActive, true);
  assert.strictEqual(registry.get('bot-b').isActive, false);

  registry.setActive('bot-b');
  assert.strictEqual(registry.get('bot-a').isActive, false);
  assert.strictEqual(registry.get('bot-b').isActive, true);
});

test('AccountRegistry - 18. unknown field rejected', () => {
  const registry = new AccountRegistry('telegram');

  assert.throws(
    () => {
      registry.register({
        id: 'bot-custom',
        label: 'Bot Custom',
        description: 'Desc',
        enabled: true,
        extraUnexpectedKey: 'not-allowed',
      });
    },
    {
      message: /Schema rejection: Unknown field 'extraUnexpectedKey'/,
    }
  );
});

test('AccountRegistry - 19. token-like / secret field rejected', () => {
  const registry = new AccountRegistry('telegram');

  const secretFieldTests = [
    { token: 'synthetic-secret-123' },
    { botToken: 'synthetic-secret-123' },
    { accessToken: 'synthetic-secret-123' },
    { channelSecret: 'synthetic-secret-123' },
    { secret: 'synthetic-secret-123' },
    { password: 'synthetic-secret-123' },
    { apiKey: 'synthetic-secret-123' },
    { api_key: 'synthetic-secret-123' },
    { credential: 'synthetic-secret-123' },
  ];

  for (const extra of secretFieldTests) {
    const keyName = Object.keys(extra)[0];
    assert.throws(
      () => {
        registry.register({
          id: `bot-secret-${keyName}`,
          label: 'Secret Bot',
          description: 'Desc',
          enabled: true,
          ...extra,
        });
      },
      {
        message: new RegExp(`Security rejection: Field '${keyName}' is forbidden`),
      }
    );
  }
});

test('AccountRegistry - 20. list output contains no secret material and only allowlisted keys', () => {
  const registry = new AccountRegistry('telegram');

  registry.register({
    id: 'syn-bot-clean-1',
    label: 'Clean Bot 1',
    description: 'Non-secret bot 1',
    enabled: true,
  });
  registry.register({
    id: 'syn-bot-clean-2',
    label: 'Clean Bot 2',
    description: 'Non-secret bot 2',
    enabled: false,
  });
  registry.setActive('syn-bot-clean-1');

  const accounts = registry.list();
  assert.strictEqual(accounts.length, 2);

  const allowedOutputKeys = new Set([...ALLOWED_METADATA_FIELDS, 'isActive']);

  for (const acc of accounts) {
    const keys = Object.keys(acc);
    for (const k of keys) {
      assert.strictEqual(
        allowedOutputKeys.has(k),
        true,
        `Key '${k}' must be within allowed output schema`
      );
    }
    // Verify no secret value leakage
    assert.strictEqual(acc.token, undefined);
    assert.strictEqual(acc.secret, undefined);
    assert.strictEqual(acc.botToken, undefined);
    assert.strictEqual(acc.password, undefined);
  }
});

test('AccountRegistry - 21. ordinary Test Bot requires no special account type', () => {
  const registry = new AccountRegistry('telegram');

  // Test Bot is registered exactly like any ordinary account (D14 / D26)
  const testBot = registry.register({
    id: 'syn-telegram-test-bot',
    label: 'Telegram Development Test Bot',
    description: 'Used for dev testing without special architecture branch',
    enabled: true,
  });

  assert.strictEqual(testBot.id, 'syn-telegram-test-bot');
  assert.strictEqual(testBot.type, undefined); // No special architecture type field
  assert.strictEqual(testBot.isSpecialTestType, undefined);

  // Activates identically to any ordinary registered account
  registry.setActive('syn-telegram-test-bot');
  assert.strictEqual(registry.getActive().id, 'syn-telegram-test-bot');
  assert.strictEqual(registry.getActive().isActive, true);
});

test('AccountRegistry - F1.1 Telegram registry + omitted account channel -> output channel = telegram', () => {
  const registry = new AccountRegistry('telegram');
  const acc = registry.register({
    id: 'tg-bot-omitted',
    label: 'TG Bot Omitted Channel',
    description: 'Channel omitted in input metadata',
    enabled: true,
  });
  assert.strictEqual(acc.channel, 'telegram');
  assert.strictEqual(registry.get('tg-bot-omitted').channel, 'telegram');
});

test('AccountRegistry - F1.2 Telegram registry + explicit channel telegram -> accepted', () => {
  const registry = new AccountRegistry('telegram');
  const acc = registry.register({
    id: 'tg-bot-explicit',
    label: 'TG Bot Explicit Channel',
    description: 'Channel explicitly set to telegram',
    enabled: true,
    channel: 'telegram',
  });
  assert.strictEqual(acc.channel, 'telegram');
});

test('AccountRegistry - F1.3 Telegram registry + explicit channel line -> rejected', () => {
  const registry = new AccountRegistry('telegram');
  assert.throws(
    () => {
      registry.register({
        id: 'line-bot-in-tg',
        label: 'Line Bot in TG Registry',
        description: 'Should be rejected due to channel mismatch',
        enabled: true,
        channel: 'line',
      });
    },
    {
      message: /CHANNEL_MISMATCH/,
    }
  );
});

test('AccountRegistry - F1.4 LINE registry + explicit channel telegram -> rejected', () => {
  const registry = new AccountRegistry('line');
  assert.throws(
    () => {
      registry.register({
        id: 'tg-bot-in-line',
        label: 'TG Bot in LINE Registry',
        description: 'Should be rejected due to channel mismatch',
        enabled: true,
        channel: 'telegram',
      });
    },
    {
      message: /CHANNEL_MISMATCH/,
    }
  );
});

test('AccountRegistry - F1.5 invalid / blank registry channel -> rejected', () => {
  assert.throws(
    () => new AccountRegistry(''),
    {
      name: 'TypeError',
      message: /channel must be a non-empty string/,
    }
  );
  assert.throws(
    () => new AccountRegistry('   '),
    {
      name: 'TypeError',
      message: /channel must be a non-empty string/,
    }
  );
  assert.throws(
    () => new AccountRegistry(null),
    {
      name: 'TypeError',
      message: /channel must be a non-empty string/,
    }
  );
  assert.throws(
    () => new AccountRegistry(123),
    {
      name: 'TypeError',
      message: /channel must be a non-empty string/,
    }
  );
});

test('AccountRegistry - 22. account ID accepts internal space, backslash, question, hash, quotes, Unicode (F2-B)', () => {
  const registry = new AccountRegistry('telegram');
  const validCases = [
    { id: 'alpha beta', label: 'Space Bot' },
    { id: 'alpha\\beta', label: 'Backslash Bot' },
    { id: 'alpha?beta', label: 'Question Bot' },
    { id: 'alpha#beta', label: 'Hash Bot' },
    { id: "alpha'beta", label: 'Single Quote Bot' },
    { id: 'alpha"beta', label: 'Double Quote Bot' },
    { id: 'unicode-測試', label: 'Unicode Bot' },
  ];

  for (const c of validCases) {
    const acc = registry.register({
      id: c.id,
      label: c.label,
      description: 'Synthetic valid domain test',
      enabled: true,
    });
    assert.strictEqual(acc.id, c.id);
    assert.strictEqual(registry.get(c.id).id, c.id);
  }
});

test('AccountRegistry - 23. account ID rejects ASCII controls (NUL, CR, LF, TAB, DEL) including leading/trailing (F2-B)', () => {
  const registry = new AccountRegistry('telegram');
  const controlCases = [
    'alpha\x00beta', // NUL
    'alpha\rbeta',   // CR
    'alpha\nbeta',   // LF
    'alpha\tbeta',   // TAB
    'alpha\x7Fbeta', // DEL
    '\x00alpha',     // leading NUL
    'alpha\x00',     // trailing NUL
    '\talpha',       // leading TAB
    'alpha\t',       // trailing TAB
    '\ralpha',       // leading CR
    'alpha\r',       // trailing CR
    '\nalpha',       // leading LF
    'alpha\n',       // trailing LF
  ];

  for (const invalidId of controlCases) {
    assert.throws(
      () => registry.register({
        id: invalidId,
        label: 'Control Bot',
        description: 'Should reject control character',
        enabled: true,
      }),
      {
        message: /id contains forbidden control characters/,
      }
    );
    assert.throws(
      () => registry.setActive(invalidId),
      {
        message: /id contains forbidden control characters/,
      }
    );
  }
});

test('AccountRegistry - 24. ordinary leading/trailing spaces continue following trim normalization (F2-B)', () => {
  const registry = new AccountRegistry('telegram');
  const acc = registry.register({
    id: '   trimmed-bot   ',
    label: 'Trimmed Bot',
    description: 'Should trim ordinary spaces',
    enabled: true,
  });
  assert.strictEqual(acc.id, 'trimmed-bot');
  assert.strictEqual(registry.get('trimmed-bot').id, 'trimmed-bot');
  registry.setActive('   trimmed-bot   ');
  assert.strictEqual(registry.getActive().id, 'trimmed-bot');
});

