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
