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
  CANONICAL_TARGET_REGEX,
  assertCanonicalTargetGrammar,
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

test('SecretRef - 14. instances are frozen and immutable (F1-C)', () => {
  const ref = SecretRef.telegramBotToken('immutable-bot');
  assert.strictEqual(Object.isFrozen(ref), true);

  // In strict mode, modifying a property throws TypeError
  assert.throws(
    () => {
      ref.channel = 'line';
    },
    { name: 'TypeError' }
  );
  assert.throws(
    () => {
      ref.accountId = 'hijacked';
    },
    { name: 'TypeError' }
  );
  assert.throws(
    () => {
      ref.newProp = 'injected';
    },
    { name: 'TypeError' }
  );
  assert.strictEqual(ref.channel, 'telegram');
  assert.strictEqual(ref.accountId, 'immutable-bot');
});

test('SecretRef - 15. attempted mutation cannot alter canonical target semantics (F1-C)', () => {
  const ref = SecretRef.lineChannelAccessToken('orig-acc');
  const origTarget = ref.getTargetName();

  assert.throws(
    () => {
      ref.encodedAccountId = 'tampered';
    },
    { name: 'TypeError' }
  );
  assert.strictEqual(ref.getTargetName(), origTarget);
  assert.strictEqual(SecretRef.deriveCanonicalTarget(ref), origTarget);
});

test('SecretRef - 16. subclass override of getTargetName cannot become authority (F1-C)', () => {
  class MaliciousSubclassSecretRef extends SecretRef {
    getTargetName() {
      return 'HH.AI_v2/channel-gateway/v1/telegram/hijacked-target/bot-token';
    }
  }

  const evilRef = new MaliciousSubclassSecretRef({
    channel: 'telegram',
    purpose: SECRET_PURPOSES.TELEGRAM_BOT_TOKEN,
    accountId: 'legit-account',
  });

  // Direct getTargetName returns the overridden string on subclass instance
  assert.strictEqual(evilRef.getTargetName(), 'HH.AI_v2/channel-gateway/v1/telegram/hijacked-target/bot-token');

  // But contract validation must reject subclass instances
  assert.throws(
    () => SecretProvider.validateSecretRef(evilRef),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // And canonical derivation must reject subclass instances
  assert.throws(
    () => SecretRef.deriveCanonicalTarget(evilRef),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
});

test('SecretRef - 17. canonical derivation is deterministic and independent of instance methods', () => {
  const ref1 = SecretRef.telegramBotToken('det-acc-01');
  const ref2 = SecretRef.telegramBotToken('det-acc-01');

  const derived1 = SecretRef.deriveCanonicalTarget(ref1);
  const derived2 = SecretRef.deriveCanonicalTarget(ref2);

  assert.strictEqual(derived1, derived2);
  assert.strictEqual(
    derived1,
    'HH.AI_v2/channel-gateway/v1/telegram/det-acc-01/bot-token'
  );
});

test('SecretRef - 18. canonical grammar accepts all four valid families', () => {
  const families = [
    'HH.AI_v2/channel-gateway/v1/telegram/valid-bot-01/bot-token',
    'HH.AI_v2/channel-gateway/v1/line/valid-line-01/channel-access-token',
    'HH.AI_v2/channel-gateway/v1/line/valid-line-01/channel-secret',
    'HH.AI_v2/channel-gateway/v1/local-api/hmac',
    // With percent encoding in account
    'HH.AI_v2/channel-gateway/v1/telegram/valid%20bot%2001/bot-token',
  ];

  for (const target of families) {
    assert.doesNotThrow(() => assertCanonicalTargetGrammar(target));
    assert.strictEqual(CANONICAL_TARGET_REGEX.test(target), true);
  }
});

test('SecretRef - 19. canonical grammar rejects unauthorized families, suffixes, or segments', () => {
  const invalidTargets = [
    // Extra path segment
    'HH.AI_v2/channel-gateway/v1/telegram/acc/bot-token/extra',
    'HH.AI_v2/channel-gateway/v1/local-api/hmac/extra',
    // Wrong namespace
    'OTHER_NS/channel-gateway/v1/telegram/acc/bot-token',
    'HH.AI_v2/channel-gateway/v2/telegram/acc/bot-token',
    // Unknown purpose suffix
    'HH.AI_v2/channel-gateway/v1/telegram/acc/admin-token',
    'HH.AI_v2/channel-gateway/v1/line/acc/bot-token',
    // Missing segments
    'HH.AI_v2/channel-gateway/v1/telegram/bot-token',
    'HH.AI_v2/channel-gateway/v1/local-api',
  ];

  for (const target of invalidTargets) {
    assert.throws(
      () => assertCanonicalTargetGrammar(target),
      { code: 'INVALID_SECRET_REFERENCE' }
    );
    assert.strictEqual(CANONICAL_TARGET_REGEX.test(target), false);
  }
});

test('SecretRef - 20. canonical grammar rejects control chars, whitespace, quotes, backslashes, queries, and bad escapes', () => {
  const rejectedTargets = [
    // Control characters
    'HH.AI_v2/channel-gateway/v1/telegram/acc\x00/bot-token',
    'HH.AI_v2/channel-gateway/v1/telegram/acc\r\n/bot-token',
    // Whitespace
    'HH.AI_v2/channel-gateway/v1/telegram/acc with space/bot-token',
    ' HH.AI_v2/channel-gateway/v1/local-api/hmac',
    'HH.AI_v2/channel-gateway/v1/local-api/hmac ',
    // Quotes
    'HH.AI_v2/channel-gateway/v1/telegram/acc\'quote/bot-token',
    'HH.AI_v2/channel-gateway/v1/telegram/acc"quote/bot-token',
    // Backslashes
    'HH.AI_v2/channel-gateway/v1/telegram/acc\\slash/bot-token',
    // Query / hash syntax
    'HH.AI_v2/channel-gateway/v1/local-api/hmac?query=1',
    'HH.AI_v2/channel-gateway/v1/local-api/hmac#hash',
    // Invalid percent escape
    'HH.AI_v2/channel-gateway/v1/telegram/acc%2/bot-token',
    'HH.AI_v2/channel-gateway/v1/telegram/acc%ZZ/bot-token',
    'HH.AI_v2/channel-gateway/v1/telegram/acc%%/bot-token',
  ];

  for (const target of rejectedTargets) {
    assert.throws(
      () => assertCanonicalTargetGrammar(target),
      { code: 'INVALID_SECRET_REFERENCE' }
    );
    assert.strictEqual(CANONICAL_TARGET_REGEX.test(target), false);
  }
});
