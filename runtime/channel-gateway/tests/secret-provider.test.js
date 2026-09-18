/**
 * runtime/channel-gateway/tests/secret-provider.test.js
 *
 * ADR-0026: Deterministic Credential Reference & SecretProvider Core Tests.
 * Uses node:test and node:assert only. Pure Node.js, zero OS API calls.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const {
  TARGET_NAMESPACE_PREFIX,
  SECRET_PURPOSES,
  SecretRef,
  SecretProvider,
  SecretProviderError,
  encodeAccountId,
} = require('../core/secret-provider');
const { AccountRegistry } = require('../core/account-registry');

test('SecretRef - 1. deterministic target namespace prefix', () => {
  assert.strictEqual(TARGET_NAMESPACE_PREFIX, 'HH.AI_v2/channel-gateway/v1');
});

test('SecretRef - 2. same input produces identical target', () => {
  const ref1 = SecretRef.telegramBotToken('test-bot-01');
  const ref2 = SecretRef.telegramBotToken('test-bot-01');
  assert.strictEqual(ref1.getTargetName(), ref2.getTargetName());
  assert.strictEqual(
    ref1.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/telegram/test-bot-01/bot-token'
  );
});

test('SecretRef - 3. different account produces different target', () => {
  const refA = SecretRef.telegramBotToken('bot-alpha');
  const refB = SecretRef.telegramBotToken('bot-beta');
  assert.notStrictEqual(refA.getTargetName(), refB.getTargetName());
  assert.strictEqual(
    refA.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/telegram/bot-alpha/bot-token'
  );
  assert.strictEqual(
    refB.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/telegram/bot-beta/bot-token'
  );
});

test('SecretRef - 4. different channel produces different target', () => {
  const refTg = SecretRef.telegramBotToken('shared-id');
  const refLineToken = SecretRef.lineChannelAccessToken('shared-id');
  const refLineSecret = SecretRef.lineChannelSecret('shared-id');

  assert.notStrictEqual(refTg.getTargetName(), refLineToken.getTargetName());
  assert.notStrictEqual(refLineToken.getTargetName(), refLineSecret.getTargetName());
  assert.strictEqual(
    refTg.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/telegram/shared-id/bot-token'
  );
  assert.strictEqual(
    refLineToken.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/line/shared-id/channel-access-token'
  );
  assert.strictEqual(
    refLineSecret.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/line/shared-id/channel-secret'
  );
});

test('SecretRef - 5. different purpose produces different target', () => {
  const refToken = SecretRef.lineChannelAccessToken('acc-01');
  const refSecret = SecretRef.lineChannelSecret('acc-01');

  assert.notStrictEqual(refToken.getTargetName(), refSecret.getTargetName());
  assert.strictEqual(
    refToken.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/line/acc-01/channel-access-token'
  );
  assert.strictEqual(
    refSecret.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/line/acc-01/channel-secret'
  );
});

test('SecretRef - 6. separator and traversal injection cannot alias another target', () => {
  const refInjected = SecretRef.telegramBotToken('foo/bar..baz');
  const target = refInjected.getTargetName();

  // Forward slash must be percent-encoded to prevent path-segment injection
  assert.strictEqual(target.includes('foo%2Fbar..baz'), true);
  assert.strictEqual(target.includes('/foo/'), false);

  // Control characters must be rejected outright
  assert.throws(
    () => SecretRef.telegramBotToken('evil\x00account'),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => SecretRef.telegramBotToken('evil\r\naccount'),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => SecretRef.telegramBotToken('evil\x1Faccount'),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
});

test('SecretRef - 7. global Local API HMAC target', () => {
  const refHmac1 = SecretRef.localApiHmac();
  const refHmac2 = SecretRef.localApiHmac();

  assert.strictEqual(refHmac1.getTargetName(), refHmac2.getTargetName());
  assert.strictEqual(
    refHmac1.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/local-api/hmac'
  );
  assert.strictEqual(refHmac1.accountId, null);

  // Passing accountId to global purpose must fail closed
  assert.throws(
    () => new SecretRef({ channel: 'local-api', purpose: SECRET_PURPOSES.LOCAL_API_HMAC, accountId: 'unwanted' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
});

test('SecretRef - 8. unsupported purposes fail closed', () => {
  assert.throws(
    () => new SecretRef({ channel: 'telegram', purpose: 'unsupported-purpose', accountId: 'acc1' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => new SecretRef({ channel: 'unknown-channel', purpose: SECRET_PURPOSES.TELEGRAM_BOT_TOKEN, accountId: 'acc1' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
});

test('SecretRef - 9. malformed references fail closed', () => {
  assert.throws(
    () => new SecretRef({ channel: '', purpose: SECRET_PURPOSES.TELEGRAM_BOT_TOKEN, accountId: 'acc1' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => new SecretRef({ channel: 'telegram', purpose: '', accountId: 'acc1' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => SecretRef.telegramBotToken(''),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => SecretRef.telegramBotToken('   '),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => SecretRef.telegramBotToken(null),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
});

test('SecretRef - 10. target contains only non-secret metadata', () => {
  const accountId = 'user-selected-bot-label';
  const ref = SecretRef.telegramBotToken(accountId);
  const target = ref.getTargetName();

  // TargetName must match exact structural template
  assert.strictEqual(
    target,
    `HH.AI_v2/channel-gateway/v1/telegram/${encodeURIComponent(accountId)}/bot-token`
  );
  // Contains only prefix, channel, encoded ID, and purpose
  assert.strictEqual(target.startsWith(TARGET_NAMESPACE_PREFIX), true);
  assert.strictEqual(target.endsWith('/bot-token'), true);
});

test('SecretRef - 11. AccountRegistry mutation not required', () => {
  const registry = new AccountRegistry('telegram');
  const registered = registry.register({
    id: 'test-bot-01',
    label: 'Test Bot 01',
    description: 'Non-secret account metadata',
    enabled: true,
  });

  // AccountRegistry stores zero secret references or values
  assert.strictEqual(registered.id, 'test-bot-01');
  assert.strictEqual(registered.secretRef, undefined);
  assert.strictEqual(registered.token, undefined);

  // The SecretRef is deterministically derived from registered account.id
  const derivedRef = SecretRef.telegramBotToken(registered.id);
  assert.strictEqual(
    derivedRef.getTargetName(),
    'HH.AI_v2/channel-gateway/v1/telegram/test-bot-01/bot-token'
  );
});

test('SecretProvider - 12. contract validation rejects invalid refs', () => {
  assert.throws(
    () => SecretProvider.validateSecretRef(null),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => SecretProvider.validateSecretRef({ notARef: true }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  const validRef = SecretRef.localApiHmac();
  const validated = SecretProvider.validateSecretRef(validRef);
  assert.strictEqual(validated, validRef);
});

test('SecretProvider - 13. base class getSecret throws error', () => {
  const provider = new SecretProvider();
  const ref = SecretRef.localApiHmac();
  assert.throws(
    () => provider.getSecret(ref),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
});
