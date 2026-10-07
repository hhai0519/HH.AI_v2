/**
 * runtime/channel-gateway/tests/windows-credential-manager-access.test.js
 *
 * SEC-02 INC-2: Windows Credential Manager Guarded Access Tests.
 * Uses node:test and node:assert only.
 * Covers TargetResolver, JS wrapper with injected spawnSync, live Windows synthetic integration,
 * and native fault injection/mutex cleanup.
 *
 * NOTE: Absolutely zero timing markers in this file.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const crypto = require('node:crypto');
const child_process = require('node:child_process');

const {
  resolveManagedTarget,
  CredentialManagerError,
} = require('../core/managed-credential-target');

const {
  WindowsCredentialManagerAccess,
  MAX_BLOB_SIZE,
} = require('../core/windows-credential-manager-access');

const { SecretRef } = require('../core/secret-provider');
const {
  WindowsCredentialManagerSecretProvider,
} = require('../core/windows-credential-manager-provider');

// ---------------------------------------------------------------------------
// 1. Target Resolver Unit Tests
// ---------------------------------------------------------------------------

test('TargetResolver - resolves all 6 approved inventory items to canonical targets', () => {
  // 1. gateway-telegram-bot-token
  const tgTarget = resolveManagedTarget({
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'alpha-bot',
  });
  assert.strictEqual(
    tgTarget,
    'HH.AI_v2/channel-gateway/v1/telegram/alpha-bot/bot-token'
  );

  // 2. gateway-line-channel-access-token
  const lineTokenTarget = resolveManagedTarget({
    inventoryId: 'gateway-line-channel-access-token',
    accountId: 'line-acc-1',
  });
  assert.strictEqual(
    lineTokenTarget,
    'HH.AI_v2/channel-gateway/v1/line/line-acc-1/channel-access-token'
  );

  // 3. gateway-line-channel-secret
  const lineSecTarget = resolveManagedTarget({
    inventoryId: 'gateway-line-channel-secret',
    accountId: 'line-acc-1',
  });
  assert.strictEqual(
    lineSecTarget,
    'HH.AI_v2/channel-gateway/v1/line/line-acc-1/channel-secret'
  );

  // 4. gateway-local-api-hmac (fixed)
  const hmacTarget = resolveManagedTarget({
    inventoryId: 'gateway-local-api-hmac',
  });
  assert.strictEqual(
    hmacTarget,
    'HH.AI_v2/channel-gateway/v1/local-api/hmac'
  );

  // 5. mcp-jules-api-key (fixed)
  const julesTarget = resolveManagedTarget({
    inventoryId: 'mcp-jules-api-key',
  });
  assert.strictEqual(
    julesTarget,
    'HH.AI_v2/mcp-launcher/v1/jules/api-key'
  );

  // 6. mcp-notion-api-token (fixed)
  const notionTarget = resolveManagedTarget({
    inventoryId: 'mcp-notion-api-token',
  });
  assert.strictEqual(
    notionTarget,
    'HH.AI_v2/mcp-launcher/v1/notion/api-token'
  );
});

test('TargetResolver - rejects excluded categories, unknown items, and caller overrides', () => {
  const rejectedIds = [
    'gemini-api-key',
    'gh-cli-oauth-token',
    'gh-cli-user-pat',
    'gcm-oauth-token',
    'antigravity-secret-storage',
    'mcp-notion-openapi-headers',
    'unknown-custom-secret',
    '',
  ];

  for (const id of rejectedIds) {
    assert.throws(
      () => resolveManagedTarget({ inventoryId: id }),
      { code: 'INVALID_SECRET_REFERENCE' }
    );
  }

  // Caller override attempts
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-local-api-hmac',
      targetName: 'custom/override',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-local-api-hmac',
      TargetName: 'custom/override',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-local-api-hmac',
      extraField: 'unexpected',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // Fixed items with accountId must fail
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-local-api-hmac',
      accountId: 'some-account',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'mcp-jules-api-key',
      accountId: 'some-account',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'mcp-notion-api-token',
      accountId: 'some-account',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // Account-scoped items without accountId must fail
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'gateway-telegram-bot-token' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'gateway-telegram-bot-token', accountId: '' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'gateway-telegram-bot-token', accountId: '   ' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
});

test('TargetResolver - closed reference: prototype, ownKeys, descriptors, Symbol, getters, fixed fields', () => {
  // 1. Prototype must be Object.prototype or null
  const nullProtoRef = Object.create(null);
  nullProtoRef.inventoryId = 'gateway-local-api-hmac';
  assert.strictEqual(
    resolveManagedTarget(nullProtoRef),
    'HH.AI_v2/channel-gateway/v1/local-api/hmac'
  );

  class CustomClass {
    constructor() {
      this.inventoryId = 'gateway-local-api-hmac';
    }
  }
  assert.throws(
    () => resolveManagedTarget(new CustomClass()),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  const customProto = Object.create({ inherited: true });
  customProto.inventoryId = 'gateway-local-api-hmac';
  assert.throws(
    () => resolveManagedTarget(customProto),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // 2. Inherited inventoryId rejected
  const inheritedInv = Object.create({ inventoryId: 'gateway-local-api-hmac' });
  assert.throws(
    () => resolveManagedTarget(inheritedInv),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // 3. Hidden unknown property (non-enumerable) rejected
  const hiddenRef = { inventoryId: 'gateway-local-api-hmac' };
  Object.defineProperty(hiddenRef, 'hiddenProp', { value: 'forbidden', enumerable: false });
  assert.throws(
    () => resolveManagedTarget(hiddenRef),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // 4. Symbol property rejected
  const symRef = {
    inventoryId: 'gateway-local-api-hmac',
    [Symbol('secretSymbol')]: 'forbidden',
  };
  assert.throws(
    () => resolveManagedTarget(symRef),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // 5. Getter property rejected (does not invoke throwing getter)
  let getterInvoked = false;
  const getterRef = { inventoryId: 'gateway-local-api-hmac' };
  Object.defineProperty(getterRef, 'accountId', {
    get() {
      getterInvoked = true;
      throw new Error('getter should not be called');
    },
    configurable: true,
  });
  assert.throws(
    () => resolveManagedTarget(getterRef),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.strictEqual(getterInvoked, false, 'Getter must not be invoked');

  // 6. Fixed items reject accountId field presence even if null or undefined
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'gateway-local-api-hmac', accountId: null }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'gateway-local-api-hmac', accountId: undefined }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'mcp-jules-api-key', accountId: null }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'mcp-jules-api-key', accountId: undefined }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'mcp-notion-api-token', accountId: null }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({ inventoryId: 'mcp-notion-api-token', accountId: undefined }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
});

test('TargetResolver - account encoding, normalization, apostrophe, wildcards, and surrogates', () => {
  // Apostrophe encoded as %27
  const apoTarget = resolveManagedTarget({
    inventoryId: 'gateway-telegram-bot-token',
    accountId: "user'bot",
  });
  assert.strictEqual(
    apoTarget,
    'HH.AI_v2/channel-gateway/v1/telegram/user%27bot/bot-token'
  );

  // Slash encoded as %2F
  const slashTarget = resolveManagedTarget({
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'team/bot',
  });
  assert.strictEqual(
    slashTarget,
    'HH.AI_v2/channel-gateway/v1/telegram/team%2Fbot/bot-token'
  );

  // Unicode account encoded properly
  const unicodeTarget = resolveManagedTarget({
    inventoryId: 'gateway-telegram-bot-token',
    accountId: '測試帳號',
  });
  assert.strictEqual(
    unicodeTarget,
    `HH.AI_v2/channel-gateway/v1/telegram/${encodeURIComponent('測試帳號')}/bot-token`
  );

  // Wildcards rejected
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-telegram-bot-token',
      accountId: 'bot*name',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-telegram-bot-token',
      accountId: 'bot?name',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // Control characters rejected
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-telegram-bot-token',
      accountId: 'bot\x00name',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-telegram-bot-token',
      accountId: 'bot\x1Fname',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-telegram-bot-token',
      accountId: 'bot\x7Fname',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // Unpaired surrogates rejected
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-telegram-bot-token',
      accountId: 'bot\uD800name',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-telegram-bot-token',
      accountId: 'bot\uDC00name',
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );

  // Excessive length rejected
  const longAccount = 'a'.repeat(33000);
  assert.throws(
    () => resolveManagedTarget({
      inventoryId: 'gateway-telegram-bot-token',
      accountId: longAccount,
    }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
});

// ---------------------------------------------------------------------------
// 2. JS Wrapper Injected Spawn Tests
// ---------------------------------------------------------------------------

test('WindowsCredManAccess - non-win32 platform fails UNSUPPORTED_PLATFORM', () => {
  assert.throws(
    () => new WindowsCredentialManagerAccess({ platform: 'linux' }),
    { code: 'UNSUPPORTED_PLATFORM' }
  );
  assert.throws(
    () => new WindowsCredentialManagerAccess({ platform: 'darwin' }),
    { code: 'UNSUPPORTED_PLATFORM' }
  );
});

test('WindowsCredManAccess - invalid ref and blob rejected before spawn', () => {
  let spawnCalled = false;
  const mockSpawn = () => {
    spawnCalled = true;
    return { status: 0, stdout: Buffer.from('PRESENT\r\n'), stderr: Buffer.from('') };
  };

  const access = new WindowsCredentialManagerAccess({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  // Invalid ref: missing accountId
  assert.throws(
    () => access.isPresent({ inventoryId: 'gateway-telegram-bot-token' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.strictEqual(spawnCalled, false, 'spawnSync must not be called on invalid ref');

  // Invalid blob: odd byte length
  const oddBlob = Buffer.from([0x61, 0x00, 0x62]);
  assert.throws(
    () => access.createNew({ inventoryId: 'gateway-local-api-hmac' }, oddBlob),
    { code: 'SECRET_ENCODING_INVALID' }
  );
  assert.strictEqual(spawnCalled, false, 'spawnSync must not be called on odd blob');

  // Invalid blob: BOM (0xFEFF)
  const bomBlob = Buffer.from([0xFF, 0xFE, 0x61, 0x00]); // 0xFEFF in LE
  assert.throws(
    () => access.createNew({ inventoryId: 'gateway-local-api-hmac' }, bomBlob),
    { code: 'SECRET_ENCODING_INVALID' }
  );
  assert.strictEqual(spawnCalled, false, 'spawnSync must not be called on BOM');

  // Invalid blob: NUL byte
  const nulBlob = Buffer.from([0x00, 0x00]);
  assert.throws(
    () => access.createNew({ inventoryId: 'gateway-local-api-hmac' }, nulBlob),
    { code: 'SECRET_ENCODING_INVALID' }
  );
  assert.strictEqual(spawnCalled, false, 'spawnSync must not be called on NUL');

  // Invalid blob: exceeds max size
  const largeBlob = Buffer.alloc(MAX_BLOB_SIZE + 2, 0x61);
  assert.throws(
    () => access.createNew({ inventoryId: 'gateway-local-api-hmac' }, largeBlob),
    { code: 'SECRET_ENCODING_INVALID' }
  );
  assert.strictEqual(spawnCalled, false, 'spawnSync must not be called on oversized blob');
});

test('WindowsCredManAccess - createNew borrows caller buffer without mutating it and scrubs private copy', () => {
  let capturedInput = null;
  const mockSpawn = (cmd, args, opts) => {
    capturedInput = opts.input;
    return { status: 0, stdout: Buffer.from('CREATED\r\n'), stderr: Buffer.from('') };
  };

  const access = new WindowsCredentialManagerAccess({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  const callerBlob = Buffer.from('secret-token-1234', 'utf16le');
  const callerOriginalCopy = Buffer.from(callerBlob);

  const result = access.createNew({ inventoryId: 'gateway-local-api-hmac' }, callerBlob);
  assert.strictEqual(result, true);

  // Assert caller buffer unchanged
  assert.strictEqual(
    callerBlob.equals(callerOriginalCopy),
    true,
    'Caller buffer must not be modified or zeroed by createNew'
  );

  // Assert private copy delivered to spawnSync was zeroed in finally
  assert.strictEqual(
    capturedInput !== callerBlob,
    true,
    'Delivered input must be private copy, not caller buffer'
  );
  assert.strictEqual(
    capturedInput.every((b) => b === 0),
    true,
    'Private copy must be zeroized in finally'
  );
});

test('WindowsCredManAccess - child execution options, arguments, and environment are sanitized', () => {
  let capturedCmd = null;
  let capturedArgs = null;
  let capturedOpts = null;

  const mockSpawn = (cmd, args, opts) => {
    capturedCmd = cmd;
    capturedArgs = args;
    capturedOpts = opts;
    return { status: 0, stdout: Buffer.from('PRESENT\r\n'), stderr: Buffer.from('') };
  };

  const access = new WindowsCredentialManagerAccess({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
    timeoutMs: 45000,
  });

  const ref = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'secure-acc',
  };
  const isPres = access.isPresent(ref);
  assert.strictEqual(isPres, true);

  assert.strictEqual(capturedOpts.shell, false);
  assert.strictEqual(capturedOpts.windowsHide, true);
  assert.strictEqual(capturedOpts.timeout, 45000);

  // Exactly 6 allowed child environment keys
  const envKeys = Object.keys(capturedOpts.env).sort();
  assert.deepStrictEqual(envKeys, ['PATH', 'PATHEXT', 'SystemDrive', 'SystemRoot', 'TEMP', 'TMP']);

  // Args contain exact operation and TargetName
  assert.strictEqual(capturedArgs.includes('-Operation'), true);
  assert.strictEqual(capturedArgs.includes('presence'), true);
  assert.strictEqual(
    capturedArgs.includes('HH.AI_v2/channel-gateway/v1/telegram/secure-acc/bot-token'),
    true
  );
});

test('WindowsCredManAccess - wire protocol token parsing and non-zero exit code mapping', () => {
  const createMock = (status, stdoutVal, stderrVal = Buffer.from('')) => () => ({
    status,
    stdout: typeof stdoutVal === 'string' ? Buffer.from(stdoutVal) : stdoutVal,
    stderr: typeof stderrVal === 'string' ? Buffer.from(stderrVal) : stderrVal,
  });

  const makeAccess = (mockFn) =>
    new WindowsCredentialManagerAccess({
      platform: 'win32',
      powershellPath: process.execPath,
      scriptPath: __filename,
      spawnSync: mockFn,
    });

  const hmacRef = { inventoryId: 'gateway-local-api-hmac' };
  const validBlob = Buffer.from('valid-secret', 'utf16le');

  // 1. isPresent: PRESENT -> true, ABSENT -> false
  assert.strictEqual(makeAccess(createMock(0, 'PRESENT\r\n')).isPresent(hmacRef), true);
  assert.strictEqual(makeAccess(createMock(0, 'PRESENT\n')).isPresent(hmacRef), true);
  assert.strictEqual(makeAccess(createMock(0, 'PRESENT')).isPresent(hmacRef), true);
  assert.strictEqual(makeAccess(createMock(0, 'ABSENT\r\n')).isPresent(hmacRef), false);

  // 2. deleteExact: DELETED -> true, ABSENT -> false
  assert.strictEqual(makeAccess(createMock(0, 'DELETED\r\n')).deleteExact(hmacRef), true);
  assert.strictEqual(makeAccess(createMock(0, 'ABSENT\r\n')).deleteExact(hmacRef), false);

  // 3. createNew: CREATED -> true
  assert.strictEqual(makeAccess(createMock(0, 'CREATED\r\n')).createNew(hmacRef, validBlob), true);

  // 4. Protocol rejection: missing/null/string/non-buffer stdout/stderr
  assert.throws(
    () => makeAccess(createMock(0, 'PRESENT\r\n', null)).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => makeAccess(createMock(0, null, Buffer.from(''))).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => makeAccess(() => ({ status: 0, stdout: 'PRESENT\r\n', stderr: Buffer.from('') })).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => makeAccess(() => ({ status: 0, stdout: Buffer.from('PRESENT\r\n'), stderr: 'warning' })).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );

  // 5. Unexpected token or extra lines fail PROVIDER_PROTOCOL_ERROR
  assert.throws(
    () => makeAccess(createMock(0, 'PRESENT\r\nextra line')).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => makeAccess(createMock(0, '  PRESENT  ')).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => makeAccess(createMock(0, '{"token":"PRESENT"}')).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => makeAccess(createMock(0, '\uFEFFPRESENT\r\n')).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );

  // 6. Non-empty stderr on exit 0 fails PROVIDER_PROTOCOL_ERROR
  assert.throws(
    () => makeAccess(createMock(0, 'PRESENT\r\n', 'warning msg')).isPresent(hmacRef),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );

  // 7. Status code mappings
  // status 3 -> PROVIDER_ACCESS_DENIED
  assert.throws(
    () => makeAccess(createMock(3, '')).isPresent(hmacRef),
    { code: 'PROVIDER_ACCESS_DENIED' }
  );

  // status 4 -> CREDENTIAL_ALREADY_EXISTS
  assert.throws(
    () => makeAccess(createMock(4, '')).createNew(hmacRef, validBlob),
    { code: 'CREDENTIAL_ALREADY_EXISTS' }
  );

  // status 5 -> CREDENTIAL_BUSY
  assert.throws(
    () => makeAccess(createMock(5, '')).createNew(hmacRef, validBlob),
    { code: 'CREDENTIAL_BUSY' }
  );

  // status 6 -> SECRET_ENCODING_INVALID
  assert.throws(
    () => makeAccess(createMock(6, '')).createNew(hmacRef, validBlob),
    { code: 'SECRET_ENCODING_INVALID' }
  );

  // status 1 -> PROVIDER_UNAVAILABLE
  assert.throws(
    () => makeAccess(createMock(1, '')).isPresent(hmacRef),
    (err) => {
      assert.strictEqual(err.code, 'PROVIDER_UNAVAILABLE');
      assert.strictEqual(err.message, 'Windows Credential Manager provider is unavailable');
      return true;
    }
  );

  // timeout -> PROVIDER_UNAVAILABLE
  assert.throws(
    () => makeAccess(() => ({
      error: { code: 'ETIMEDOUT' },
      status: null,
      stdout: Buffer.from(''),
      stderr: Buffer.from(''),
    })).isPresent(hmacRef),
    (err) => {
      assert.strictEqual(err.code, 'PROVIDER_UNAVAILABLE');
      assert.strictEqual(err.message, 'Windows Credential Manager access timed out');
      return true;
    }
  );

  // other spawn error -> PROVIDER_UNAVAILABLE
  assert.throws(
    () => makeAccess(() => ({
      error: { code: 'ENOENT' },
      status: null,
      stdout: Buffer.from(''),
      stderr: Buffer.from(''),
    })).isPresent(hmacRef),
    (err) => {
      assert.strictEqual(err.code, 'PROVIDER_UNAVAILABLE');
      assert.strictEqual(err.message, 'Error executing Windows Credential Manager bridge');
      return true;
    }
  );

  // spawn throw -> PROVIDER_UNAVAILABLE
  assert.throws(
    () => makeAccess(() => { throw new Error('spawn failure'); }).isPresent(hmacRef),
    (err) => {
      assert.strictEqual(err.code, 'PROVIDER_UNAVAILABLE');
      assert.strictEqual(err.message, 'Failed to execute Windows Credential Manager bridge');
      return true;
    }
  );

  // no result -> PROVIDER_UNAVAILABLE
  assert.throws(
    () => makeAccess(() => null).isPresent(hmacRef),
    (err) => {
      assert.strictEqual(err.code, 'PROVIDER_UNAVAILABLE');
      assert.strictEqual(err.message, 'Windows Credential Manager bridge returned no result');
      return true;
    }
  );

  // signal -> PROVIDER_PROTOCOL_ERROR
  assert.throws(
    () => makeAccess(() => ({
      signal: 'SIGTERM',
      status: null,
      stdout: Buffer.from(''),
      stderr: Buffer.from(''),
    })).isPresent(hmacRef),
    (err) => {
      assert.strictEqual(err.code, 'PROVIDER_PROTOCOL_ERROR');
      assert.strictEqual(err.message, 'Windows Credential Manager bridge terminated by signal');
      return true;
    }
  );

  // Verify private copy zeroed on failure branches in createNew
  const testScrubOnFail = (mockFn) => {
    let delivered = null;
    const trackingMock = (cmd, args, opts) => {
      delivered = opts.input;
      return mockFn(cmd, args, opts);
    };
    const access = makeAccess(trackingMock);
    const borrowed = Buffer.from('test-secret-payload', 'utf16le');
    const orig = Buffer.from(borrowed);
    try {
      assert.throws(() => access.createNew(hmacRef, borrowed));
      assert.strictEqual(borrowed.equals(orig), true, 'Borrowed buffer must not be mutated');
      if (delivered) {
        assert.strictEqual(delivered.every((b) => b === 0), true, 'Private copy must be zeroized');
      }
    } finally {
      borrowed.fill(0);
      orig.fill(0);
    }
  };

  testScrubOnFail(createMock(1, ''));
  testScrubOnFail(createMock(3, ''));
  testScrubOnFail(createMock(4, ''));
  testScrubOnFail(createMock(5, ''));
  testScrubOnFail(createMock(6, ''));
  testScrubOnFail(createMock(0, 'INVALID_TOKEN\r\n'));
  testScrubOnFail(() => ({ error: { code: 'ETIMEDOUT' }, status: null, stdout: Buffer.from(''), stderr: Buffer.from('') }));
  testScrubOnFail(() => ({ signal: 'SIGTERM', status: null, stdout: Buffer.from(''), stderr: Buffer.from('') }));
  testScrubOnFail(() => { throw new Error('spawn failure'); });
});

// ---------------------------------------------------------------------------
// 3. Live Windows Synthetic Tests (Windows only)
// ---------------------------------------------------------------------------

test('WindowsCredManAccess - Live Windows synthetic credential lifecycle and provider readback', (t) => {
  if (process.platform !== 'win32') {
    assert.throws(
      () => new WindowsCredentialManagerAccess(),
      { code: 'UNSUPPORTED_PLATFORM' }
    );
    return;
  }

  const access = new WindowsCredentialManagerAccess();
  const provider = new WindowsCredentialManagerSecretProvider();

  // Synthetic account with random UUID
  const randomId = 'syn-' + crypto.randomUUID();
  const ref = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: randomId,
  };
  const secretProviderRef = SecretRef.telegramBotToken(randomId);

  const syntheticSecretText = `synthetic-secret-token-€-🌟-${randomId}`;
  const syntheticBlob = Buffer.from(syntheticSecretText, 'utf16le');

  try {
    // 1. Initial presence must be false (ABSENT)
    const initialPresent = access.isPresent(ref);
    assert.strictEqual(initialPresent, false, 'Initial synthetic target must be ABSENT');

    // 2. createNew must succeed and return true
    const created = access.createNew(ref, syntheticBlob);
    assert.strictEqual(created, true, 'createNew must return true on success');

    // 3. isPresent must now be true (PRESENT)
    const afterCreatePresent = access.isPresent(ref);
    assert.strictEqual(afterCreatePresent, true, 'Target must be PRESENT after createNew');

    // 4. Existing Gateway provider reads back identical decoded Unicode payload
    const retrievedBuffer = provider.getSecret(secretProviderRef);
    assert.strictEqual(Buffer.isBuffer(retrievedBuffer), true);
    assert.strictEqual(
      retrievedBuffer.toString('utf8'),
      syntheticSecretText,
      'Provider must read back identical Unicode secret'
    );
    retrievedBuffer.fill(0);

    // 5. Subsequent createNew on existing target fails CREDENTIAL_ALREADY_EXISTS
    const anotherBlob = Buffer.from('another-token', 'utf16le');
    assert.throws(
      () => access.createNew(ref, anotherBlob),
      { code: 'CREDENTIAL_ALREADY_EXISTS' }
    );
    anotherBlob.fill(0);

    // Verify original content was NOT overwritten
    const checkBuffer = provider.getSecret(secretProviderRef);
    assert.strictEqual(checkBuffer.toString('utf8'), syntheticSecretText);
    checkBuffer.fill(0);

    // 6. Case alias TargetName createNew also fails CREDENTIAL_ALREADY_EXISTS
    const uppercaseRef = {
      inventoryId: 'gateway-telegram-bot-token',
      accountId: randomId.toUpperCase(),
    };
    assert.throws(
      () => access.createNew(uppercaseRef, syntheticBlob),
      { code: 'CREDENTIAL_ALREADY_EXISTS' }
    );

    // 7. deleteExact succeeds and returns true
    const deleted = access.deleteExact(ref);
    assert.strictEqual(deleted, true, 'deleteExact must return true on existing target');

    // 8. isPresent is now false
    const afterDelPresent = access.isPresent(ref);
    assert.strictEqual(afterDelPresent, false, 'Target must be ABSENT after deletion');

    // 9. Second deleteExact returns false (already absent)
    const deletedAgain = access.deleteExact(ref);
    assert.strictEqual(deletedAgain, false, 'deleteExact must return false if already absent');
  } finally {
    try {
      access.deleteExact(ref);
    } catch {
      // Ignore
    }
    syntheticBlob.fill(0);
    assert.strictEqual(access.isPresent(ref), false, 'Cleanup must leave synthetic target absent');
  }
});

// ---------------------------------------------------------------------------
// 4. Native Mutex & Cleanup Fault Tests (R11)
// ---------------------------------------------------------------------------

function spawnFixtureProcess({ scriptPath, powershellPath, operation, targetName, testFaultStage }) {
  const systemRoot = process.env.SystemRoot || 'C:\\Windows';
  const childEnv = {
    SystemRoot: systemRoot,
    SystemDrive: process.env.SystemDrive || 'C:',
    PATH: process.env.PATH || `${systemRoot}\\System32;${systemRoot}`,
    PATHEXT: process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC',
    TEMP: process.env.TEMP || `${systemRoot}\\Temp`,
    TMP: process.env.TMP || `${systemRoot}\\Temp`,
  };
  const args = [
    '-NoLogo',
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy', 'Bypass',
    '-File', scriptPath,
    '-Operation', operation,
    '-TargetName', targetName,
    '-TestFaultStage', testFaultStage,
  ];
  const proc = child_process.spawn(powershellPath, args, {
    env: childEnv,
    windowsHide: true,
    shell: false,
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  proc.stdin.on('error', (err) => {
    if (!streamError) {
      streamError = err;
    }
  });

  let stdoutBuf = '';
  let stderrBuf = '';
  let stdoutLen = 0;
  let stderrLen = 0;
  let streamError = null;

  proc.stdout.on('data', (d) => {
    stdoutLen += d.length;
    if (stdoutLen > 4096) {
      streamError = new Error('STDOUT_OVERFLOW');
    } else {
      stdoutBuf += d.toString('utf8');
    }
  });

  proc.stderr.on('data', (d) => {
    stderrLen += d.length;
    if (stderrLen > 4096) {
      streamError = new Error('STDERR_OVERFLOW');
    } else {
      stderrBuf += d.toString('utf8');
    }
  });

  let closed = false;
  let closeResult = null;

  proc.on('close', (code, signal) => {
    closed = true;
    closeResult = { code, signal };
  });

  const waitForClose = (timeoutMs = 5000) => {
    if (closed) {
      return Promise.resolve(closeResult);
    }
    return new Promise((resolve, reject) => {
      let timer = null;
      let settled = false;

      const onClose = (code, signal) => {
        if (settled) return;
        settled = true;
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        proc.removeListener('close', onClose);
        proc.removeListener('error', onError);
        resolve({ code, signal });
      };

      const onError = (err) => {
        if (settled) return;
        settled = true;
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        proc.removeListener('close', onClose);
        proc.removeListener('error', onError);
        reject(err);
      };

      const onTimeout = () => {
        if (settled) return;
        settled = true;
        proc.removeListener('close', onClose);
        proc.removeListener('error', onError);
        reject(new Error('S1_NATIVE_TIMEOUT: timed out waiting for child close'));
      };

      proc.on('close', onClose);
      proc.on('error', onError);
      timer = setTimeout(onTimeout, timeoutMs);
    });
  };

  const waitForSignal = (expectedSignal, timeoutMs = 5000) => {
    return new Promise((resolve, reject) => {
      if (streamError) {
        return reject(new Error(`S1_OWNED_CHILD_CLEANUP_UNPROVEN: ${streamError.message}`));
      }
      const target1 = `${expectedSignal}\r\n`;
      const target2 = `${expectedSignal}\n`;
      if (stdoutBuf === target1 || stdoutBuf === target2) {
        return resolve();
      }

      let timer = null;
      let settled = false;

      const onData = () => {
        if (settled) return;
        if (streamError) {
          cleanup();
          return reject(new Error(`S1_OWNED_CHILD_CLEANUP_UNPROVEN: ${streamError.message}`));
        }
        if (stdoutBuf === target1 || stdoutBuf === target2) {
          cleanup();
          return resolve();
        }
        if (stdoutBuf.length > target1.length) {
          cleanup();
          return reject(new Error('S1_OWNED_CHILD_CLEANUP_UNPROVEN: Extra output before signal'));
        }
      };

      const onClose = (code, signal) => {
        if (settled) return;
        cleanup();
        reject(new Error(`S1_OWNED_CHILD_CLEANUP_UNPROVEN: Child closed prematurely with code=${code} signal=${signal}`));
      };

      const onError = (err) => {
        if (settled) return;
        cleanup();
        reject(err);
      };

      const onTimeout = () => {
        if (settled) return;
        cleanup();
        reject(new Error(`S1_NATIVE_TIMEOUT: Timed out waiting for signal ${expectedSignal}`));
      };

      function cleanup() {
        settled = true;
        if (timer) {
          clearTimeout(timer);
          timer = null;
        }
        proc.stdout.removeListener('data', onData);
        proc.removeListener('close', onClose);
        proc.removeListener('error', onError);
      }

      proc.stdout.on('data', onData);
      proc.on('close', onClose);
      proc.on('error', onError);
      timer = setTimeout(onTimeout, timeoutMs);
    });
  };

  const cleanup = async (timeoutMs = 5000) => {
    if (closed) {
      return closeResult;
    }
    try {
      proc.stdin.destroy();
    } catch {
      // ignore
    }
    try {
      proc.kill();
    } catch {
      // ignore
    }
    try {
      return await waitForClose(timeoutMs);
    } catch (err) {
      throw new Error(`S1_OWNED_CHILD_CLEANUP_UNPROVEN: ${err.message}`);
    }
  };

  return {
    proc,
    waitForClose,
    waitForSignal,
    cleanup,
  };
}

function parseCleanupTrace(stderrBuf) {
  const str = stderrBuf.toString('utf8').trim();
  const match = /^CLEANUP: acquired=(\d+) readCalls=(\d+) writeCalls=(\d+) deleteCalls=(\d+) readFree=(\d+) blobClear=(\d+) blobFree=(\d+) mutexRelease=(\d+) mutexDispose=(\d+) cleanupFailed=(\d+)$/.exec(str);
  if (!match) {
    throw new Error(`Invalid cleanup trace: ${str}`);
  }
  return {
    acquired: Number(match[1]),
    readCalls: Number(match[2]),
    writeCalls: Number(match[3]),
    deleteCalls: Number(match[4]),
    readFree: Number(match[5]),
    blobClear: Number(match[6]),
    blobFree: Number(match[7]),
    mutexRelease: Number(match[8]),
    mutexDispose: Number(match[9]),
    cleanupFailed: Number(match[10]),
  };
}

test('WindowsCredManAccess - Native bridge mutex busy counterexample exits 5', async (t) => {
  if (process.platform !== 'win32') {
    return;
  }

  const scriptPath = path.resolve(
    __dirname,
    '..',
    'bin',
    'windows-credential-manager-access.ps1'
  );
  const powershellPath = path.join(
    process.env.SystemRoot || 'C:\\Windows',
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe'
  );

  const ref = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'syn-' + crypto.randomUUID(),
  };
  const testTarget = resolveManagedTarget(ref);

  const holder = spawnFixtureProcess({
    scriptPath,
    powershellPath,
    operation: 'create',
    targetName: testTarget,
    testFaultStage: 'hold-mutex',
  });

  try {
    await holder.waitForSignal('HELD', 5000);

    const runRes = child_process.spawnSync(
      powershellPath,
      [
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        scriptPath,
        '-Operation',
        'create',
        '-TargetName',
        testTarget,
        '-TraceCleanup',
      ],
      { timeout: 5000, windowsHide: true }
    );

    assert.strictEqual(runRes.status, 5, 'Bridge must exit 5 when mutex is busy');
    const trace = parseCleanupTrace(runRes.stderr);
    assert.strictEqual(trace.acquired, 0);
    assert.strictEqual(trace.mutexRelease, 0);
    assert.strictEqual(trace.mutexDispose, 1);
    assert.strictEqual(trace.readCalls, 0);
    assert.strictEqual(trace.writeCalls, 0);
    assert.strictEqual(trace.deleteCalls, 0);
    assert.strictEqual(trace.cleanupFailed, 0);
  } finally {
    await holder.cleanup(5000);
  }
});

test('WindowsCredManAccess - Native bridge abandoned mutex maps to exit 1 / PROVIDER_UNAVAILABLE', async (t) => {
  if (process.platform !== 'win32') {
    return;
  }

  const scriptPath = path.resolve(
    __dirname,
    '..',
    'bin',
    'windows-credential-manager-access.ps1'
  );
  const powershellPath = path.join(
    process.env.SystemRoot || 'C:\\Windows',
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe'
  );

  // Part A: Raw bridge on abandoned mutex
  const ref1 = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'syn-' + crypto.randomUUID(),
  };
  const testTarget1 = resolveManagedTarget(ref1);

  const keeper1 = spawnFixtureProcess({
    scriptPath,
    powershellPath,
    operation: 'create',
    targetName: testTarget1,
    testFaultStage: 'keep-mutex-open',
  });

  try {
    await keeper1.waitForSignal('KEEPER_READY', 5000);

    const holder1 = spawnFixtureProcess({
      scriptPath,
      powershellPath,
      operation: 'create',
      targetName: testTarget1,
      testFaultStage: 'hold-mutex',
    });

    try {
      await holder1.waitForSignal('HELD', 5000);
      const killRes1 = holder1.proc.kill();
      assert.strictEqual(killRes1, true, 'holder1 process kill must return true');
      const closeRes1 = await holder1.waitForClose(5000);
      assert.ok(closeRes1 !== null, 'holder1 process close result must be proven');

      const bridgeRes = child_process.spawnSync(
        powershellPath,
        [
          '-NoLogo',
          '-NoProfile',
          '-NonInteractive',
          '-ExecutionPolicy',
          'Bypass',
          '-File',
          scriptPath,
          '-Operation',
          'create',
          '-TargetName',
          testTarget1,
          '-TraceCleanup',
        ],
        { timeout: 5000, windowsHide: true }
      );

      assert.strictEqual(bridgeRes.status, 1, 'Bridge must exit 1 on abandoned mutex');
      const trace = parseCleanupTrace(bridgeRes.stderr);
      assert.strictEqual(trace.acquired, 1, 'Abandoned mutex acquisition must record acquired=1');
      assert.strictEqual(trace.mutexRelease, 1, 'Abandoned mutex must be released in finally');
      assert.strictEqual(trace.mutexDispose, 1, 'Abandoned mutex must be disposed in finally');
      assert.strictEqual(trace.readCalls, 0);
      assert.strictEqual(trace.writeCalls, 0);
      assert.strictEqual(trace.deleteCalls, 0);
      assert.strictEqual(trace.cleanupFailed, 0);
    } finally {
      await holder1.cleanup(5000);
    }
  } finally {
    await keeper1.cleanup(5000);
  }

  // Part B: Actual WindowsCredentialManagerAccess wrapper with second independent randomUUID
  const ref2 = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'syn-' + crypto.randomUUID(),
  };
  const testTarget2 = resolveManagedTarget(ref2);

  const keeper2 = spawnFixtureProcess({
    scriptPath,
    powershellPath,
    operation: 'create',
    targetName: testTarget2,
    testFaultStage: 'keep-mutex-open',
  });

  const borrowedBlob = Buffer.from('test-abandoned-secret-token', 'utf16le');
  const originalCopy = Buffer.from(borrowedBlob);

  try {
    await keeper2.waitForSignal('KEEPER_READY', 5000);

    const holder2 = spawnFixtureProcess({
      scriptPath,
      powershellPath,
      operation: 'create',
      targetName: testTarget2,
      testFaultStage: 'hold-mutex',
    });

    try {
      await holder2.waitForSignal('HELD', 5000);
      const killRes2 = holder2.proc.kill();
      assert.strictEqual(killRes2, true, 'holder2 process kill must return true');
      const closeRes2 = await holder2.waitForClose(5000);
      assert.ok(closeRes2 !== null, 'holder2 process close result must be proven');

      const access = new WindowsCredentialManagerAccess();
      assert.throws(
        () => access.createNew(ref2, borrowedBlob),
        (err) => {
          assert.strictEqual(err.code, 'PROVIDER_UNAVAILABLE');
          assert.strictEqual(err.message, 'Windows Credential Manager provider is unavailable');
          return true;
        }
      );
      assert.strictEqual(
        borrowedBlob.equals(originalCopy),
        true,
        'Borrowed buffer must not be modified by createNew'
      );
    } finally {
      await holder2.cleanup(5000);
    }
  } finally {
    borrowedBlob.fill(0);
    originalCopy.fill(0);
    await keeper2.cleanup(5000);
  }
});

test('WindowsCredManAccess - Native bridge fault injection stages and cleanup counters', (t) => {
  if (process.platform !== 'win32') {
    return;
  }

  const scriptPath = path.resolve(
    __dirname,
    '..',
    'bin',
    'windows-credential-manager-access.ps1'
  );
  const powershellPath = path.join(
    process.env.SystemRoot || 'C:\\Windows',
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe'
  );

  const access = new WindowsCredentialManagerAccess();

  // 1. acquired-read fault stage (must test on existing synthetic target, verifying readFree=1)
  const readRef = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'syn-' + crypto.randomUUID(),
  };
  const readTarget = resolveManagedTarget(readRef);
  const setupBlob = Buffer.from('setup-secret', 'utf16le');
  try {
    assert.strictEqual(access.createNew(readRef, setupBlob), true);
    assert.strictEqual(access.isPresent(readRef), true);

    const resRead = child_process.spawnSync(
      powershellPath,
      [
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        scriptPath,
        '-Operation',
        'presence',
        '-TargetName',
        readTarget,
        '-TestFaultStage',
        'acquired-read',
        '-TraceCleanup',
      ],
      { timeout: 5000, windowsHide: true }
    );
    assert.strictEqual(resRead.status, 1);
    const traceRead = parseCleanupTrace(resRead.stderr);
    assert.strictEqual(traceRead.acquired, 0);
    assert.strictEqual(traceRead.readCalls, 1);
    assert.strictEqual(traceRead.readFree, 1);
    assert.strictEqual(traceRead.writeCalls, 0);
    assert.strictEqual(traceRead.deleteCalls, 0);
    assert.strictEqual(traceRead.cleanupFailed, 0);
  } finally {
    setupBlob.fill(0);
    try {
      access.deleteExact(readRef);
    } catch {
      // ignore
    }
    assert.strictEqual(access.isPresent(readRef), false);
  }

  // 2. after-read-check fault stage (on absent target)
  const absentRef1 = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'syn-' + crypto.randomUUID(),
  };
  const absentTarget1 = resolveManagedTarget(absentRef1);
  const validBlob1 = Buffer.from('test-secret-1', 'utf16le');
  try {
    assert.strictEqual(access.isPresent(absentRef1), false);
    const res1 = child_process.spawnSync(
      powershellPath,
      [
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        scriptPath,
        '-Operation',
        'create',
        '-TargetName',
        absentTarget1,
        '-TestFaultStage',
        'after-read-check',
        '-TraceCleanup',
      ],
      { input: validBlob1, timeout: 5000, windowsHide: true }
    );
    assert.strictEqual(res1.status, 1);
    const trace1 = parseCleanupTrace(res1.stderr);
    assert.strictEqual(trace1.acquired, 1);
    assert.strictEqual(trace1.readCalls, 1);
    assert.strictEqual(trace1.writeCalls, 0);
    assert.strictEqual(trace1.deleteCalls, 0);
    assert.strictEqual(trace1.readFree, 0);
    assert.strictEqual(trace1.blobClear, 0);
    assert.strictEqual(trace1.blobFree, 0);
    assert.strictEqual(trace1.mutexRelease, 1);
    assert.strictEqual(trace1.mutexDispose, 1);
    assert.strictEqual(trace1.cleanupFailed, 0);
  } finally {
    validBlob1.fill(0);
    assert.strictEqual(access.isPresent(absentRef1), false);
  }

  // 3. after-blob-alloc fault stage (on absent target)
  const absentRef2 = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'syn-' + crypto.randomUUID(),
  };
  const absentTarget2 = resolveManagedTarget(absentRef2);
  const validBlob2 = Buffer.from('test-secret-2', 'utf16le');
  try {
    assert.strictEqual(access.isPresent(absentRef2), false);
    const res2 = child_process.spawnSync(
      powershellPath,
      [
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        scriptPath,
        '-Operation',
        'create',
        '-TargetName',
        absentTarget2,
        '-TestFaultStage',
        'after-blob-alloc',
        '-TraceCleanup',
      ],
      { input: validBlob2, timeout: 5000, windowsHide: true }
    );
    assert.strictEqual(res2.status, 1);
    const trace2 = parseCleanupTrace(res2.stderr);
    assert.strictEqual(trace2.acquired, 1);
    assert.strictEqual(trace2.readCalls, 1);
    assert.strictEqual(trace2.writeCalls, 0);
    assert.strictEqual(trace2.deleteCalls, 0);
    assert.strictEqual(trace2.readFree, 0);
    assert.strictEqual(trace2.blobClear, 1);
    assert.strictEqual(trace2.blobFree, 1);
    assert.strictEqual(trace2.mutexRelease, 1);
    assert.strictEqual(trace2.mutexDispose, 1);
    assert.strictEqual(trace2.cleanupFailed, 0);
  } finally {
    validBlob2.fill(0);
    assert.strictEqual(access.isPresent(absentRef2), false);
  }

  // 4. before-stdout fault stage (on absent target, CredWrite succeeds before stdout failure)
  const absentRef3 = {
    inventoryId: 'gateway-telegram-bot-token',
    accountId: 'syn-' + crypto.randomUUID(),
  };
  const absentTarget3 = resolveManagedTarget(absentRef3);
  const validBlob3 = Buffer.from('test-secret-3', 'utf16le');
  try {
    assert.strictEqual(access.isPresent(absentRef3), false);
    const res3 = child_process.spawnSync(
      powershellPath,
      [
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        scriptPath,
        '-Operation',
        'create',
        '-TargetName',
        absentTarget3,
        '-TestFaultStage',
        'before-stdout',
        '-TraceCleanup',
      ],
      { input: validBlob3, timeout: 5000, windowsHide: true }
    );
    assert.strictEqual(res3.status, 1);
    const trace3 = parseCleanupTrace(res3.stderr);
    assert.strictEqual(trace3.acquired, 1);
    assert.strictEqual(trace3.readCalls, 1);
    assert.strictEqual(trace3.writeCalls, 1);
    assert.strictEqual(trace3.deleteCalls, 0);
    assert.strictEqual(trace3.readFree, 0);
    assert.strictEqual(trace3.blobClear, 1);
    assert.strictEqual(trace3.blobFree, 1);
    assert.strictEqual(trace3.mutexRelease, 1);
    assert.strictEqual(trace3.mutexDispose, 1);
    assert.strictEqual(trace3.cleanupFailed, 0);

    // Credential write succeeded before stdout failure, target is now PRESENT
    assert.strictEqual(access.isPresent(absentRef3), true);
  } finally {
    validBlob3.fill(0);
    try {
      access.deleteExact(absentRef3);
    } catch {
      // ignore
    }
    assert.strictEqual(access.isPresent(absentRef3), false);
  }
});
