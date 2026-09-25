/**
 * runtime/channel-gateway/tests/gateway-runtime-owner.test.js
 *
 * TG-MVP-11: GatewayRuntimeOwner and bin/gateway.js lifecycle and bootstrap tests.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { GatewayRuntimeOwner, OWNER_STATUS } = require('../core/gateway-runtime-owner');
const { runGateway, bootstrapGateway, resolveSecretProviderClass } = require('../bin/gateway');

const FAKE_SECRET_SOURCE = Buffer.from(
  '00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff',
  'hex'
);

class FakeSecretProvider {
  constructor() {
    this.lastReturnedBuffer = null;
  }

  getSecret(_ref) {
    const buf = Buffer.from(FAKE_SECRET_SOURCE);
    this.lastReturnedBuffer = buf;
    return buf;
  }
}

class FakeBackupOwner {
  constructor(stateRoot) {
    this.stateRoot = stateRoot;
    this.started = false;
    this.stopped = false;
    this.repository = {
      isClosed: false,
      close: () => {
        this.repository.isClosed = true;
      },
    };
  }

  start() {
    this.started = true;
  }

  stop() {
    this.stopped = true;
    this.repository.close();
  }
}

class FakeLocalApiServer {
  constructor(opts) {
    this.opts = opts;
    this.started = false;
    this.stopped = false;
    this.isStopping = false;
    this.server = {
      close: () => {},
    };
  }

  async start() {
    this.started = true;
  }

  async stop() {
    this.isStopping = true;
    this.stopped = true;
  }
}

class FakeTelegramAdapter {
  constructor() {
    this.started = false;
    this.stopped = false;
  }

  async start() {
    this.started = true;
  }

  async stop() {
    this.stopped = true;
  }
}

test('safe to require bin/gateway.js with zero side effects', () => {
  const mod = require('../bin/gateway');
  assert.strictEqual(typeof mod.runGateway, 'function');
});

test('GatewayRuntimeOwner normal startup and ordered shutdown sequence', async () => {
  const lifecycleEvents = [];
  const fakeProvider = new FakeSecretProvider();

  const fakeBackup = {
    repository: { name: 'mock-repo' },
    start: () => {
      lifecycleEvents.push('backup.start');
    },
    stop: () => {
      lifecycleEvents.push('backup.stop');
    },
  };

  const fakeServer = {
    isStopping: false,
    server: {
      close: () => {
        lifecycleEvents.push('server.closeListener');
      },
    },
    start: async () => {
      lifecycleEvents.push('server.start');
    },
    stop: async () => {
      lifecycleEvents.push('server.stop');
    },
  };

  const fakeAdapter = {
    start: async () => {
      lifecycleEvents.push('adapter.start');
    },
    stop: async () => {
      lifecycleEvents.push('adapter.stop');
    },
  };

  const processEmitter = new EventEmitter();

  const owner = new GatewayRuntimeOwner({
    stateRoot: 'C:\\fake\\stateRoot',
    secretProvider: fakeProvider,
    backupRuntimeOwner: fakeBackup,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    processEmitter,
  });

  assert.strictEqual(owner.status, OWNER_STATUS.INITIALIZED);
  await owner.start();

  assert.strictEqual(owner.status, OWNER_STATUS.RUNNING);
  assert.strictEqual(owner.isRunning, true);

  // Assert startup order: 1. backup, 2. server, 3. adapter
  assert.deepStrictEqual(lifecycleEvents, [
    'backup.start',
    'server.start',
    'adapter.start',
  ]);

  // Execute graceful stop
  lifecycleEvents.length = 0;
  await owner.stop();

  assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);
  assert.strictEqual(owner.isRunning, false);

  // Assert stop order (Mutation T17 requirement):
  // adapter.stop() MUST happen BEFORE backup.stop() / repo close
  const adapterStopIdx = lifecycleEvents.indexOf('adapter.stop');
  const backupStopIdx = lifecycleEvents.indexOf('backup.stop');
  assert.ok(adapterStopIdx !== -1, 'adapter.stop must be called');
  assert.ok(backupStopIdx !== -1, 'backup.stop must be called');
  assert.ok(
    adapterStopIdx < backupStopIdx,
    'adapter.stop must complete before backup.stop'
  );

  // Assert secret zeroization
  assert.ok(fakeProvider.lastReturnedBuffer, 'provider returned buffer must exist');
  for (let i = 0; i < fakeProvider.lastReturnedBuffer.length; i++) {
    assert.strictEqual(fakeProvider.lastReturnedBuffer[i], 0);
  }
});

test('GatewayRuntimeOwner startup rollback when telegram adapter fails', async () => {
  const rollbackEvents = [];
  const fakeProvider = new FakeSecretProvider();

  const fakeBackup = {
    repository: { name: 'mock-repo' },
    start: () => {
      rollbackEvents.push('backup.start');
    },
    stop: () => {
      rollbackEvents.push('backup.stop');
    },
  };

  const fakeServer = {
    isStopping: false,
    start: async () => {
      rollbackEvents.push('server.start');
    },
    stop: async () => {
      rollbackEvents.push('server.stop');
    },
  };

  const fakeAdapter = {
    start: async () => {
      rollbackEvents.push('adapter.start');
      throw new Error('TELEGRAM_STARTUP_FAILURE');
    },
    stop: async () => {
      rollbackEvents.push('adapter.stop');
    },
  };

  const owner = new GatewayRuntimeOwner({
    stateRoot: 'C:\\fake\\stateRoot',
    secretProvider: fakeProvider,
    backupRuntimeOwner: fakeBackup,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
  });

  await assert.rejects(
    async () => {
      await owner.start();
    },
    /TELEGRAM_STARTUP_FAILURE/
  );

  assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);

  // Rollback order: server.stop -> backup.stop
  assert.ok(rollbackEvents.includes('server.stop'));
  assert.ok(rollbackEvents.includes('backup.stop'));

  // Secret must be zeroized on rollback
  assert.ok(fakeProvider.lastReturnedBuffer);
  for (let i = 0; i < fakeProvider.lastReturnedBuffer.length; i++) {
    assert.strictEqual(fakeProvider.lastReturnedBuffer[i], 0);
  }
});

test('GatewayRuntimeOwner startup rollback when Local API server fails to bind (T19)', async () => {
  const rollbackEvents = [];
  const fakeProvider = new FakeSecretProvider();

  const fakeBackup = {
    repository: { name: 'mock-repo' },
    start: () => {
      rollbackEvents.push('backup.start');
    },
    stop: () => {
      rollbackEvents.push('backup.stop');
    },
  };

  const fakeServer = {
    isStopping: false,
    start: async () => {
      rollbackEvents.push('server.start');
      throw new Error('EADDRINUSE: port 3003 already bound');
    },
    stop: async () => {
      rollbackEvents.push('server.stop');
    },
  };

  let adapterStarted = false;
  const fakeAdapter = {
    start: async () => {
      adapterStarted = true;
    },
    stop: async () => {},
  };

  const owner = new GatewayRuntimeOwner({
    stateRoot: 'C:\\fake\\stateRoot',
    secretProvider: fakeProvider,
    backupRuntimeOwner: fakeBackup,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
  });

  await assert.rejects(
    async () => {
      await owner.start();
    },
    /EADDRINUSE/
  );

  assert.strictEqual(adapterStarted, false, 'Telegram adapter must NOT start if server bind fails');
  assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);
  assert.ok(rollbackEvents.includes('backup.stop'), 'Backup owner must be stopped on server bind rollback');

  // Secret must be zeroized on rollback
  assert.ok(fakeProvider.lastReturnedBuffer);
  for (let i = 0; i < fakeProvider.lastReturnedBuffer.length; i++) {
    assert.strictEqual(fakeProvider.lastReturnedBuffer[i], 0);
  }
});

test('GatewayRuntimeOwner signal handling triggers stop and removes listeners', async () => {
  const processEmitter = new EventEmitter();
  const fakeProvider = new FakeSecretProvider();

  let backupStopped = false;
  const fakeBackup = {
    repository: {},
    start: () => {},
    stop: () => {
      backupStopped = true;
    },
  };

  const fakeServer = {
    isStopping: false,
    start: async () => {},
    stop: async () => {},
  };

  const fakeAdapter = {
    start: async () => {},
    stop: async () => {},
  };

  const owner = new GatewayRuntimeOwner({
    stateRoot: 'C:\\fake\\stateRoot',
    secretProvider: fakeProvider,
    backupRuntimeOwner: fakeBackup,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    processEmitter,
    platform: 'win32',
  });

  await owner.start();
  assert.ok(processEmitter.listenerCount('SIGINT') > 0);
  assert.ok(processEmitter.listenerCount('SIGBREAK') > 0);

  // Emit SIGINT
  processEmitter.emit('SIGINT');

  // Wait brief tick for async stop to complete
  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);
  assert.strictEqual(backupStopped, true);

  // Listeners must be removed after stop
  assert.strictEqual(processEmitter.listenerCount('SIGINT'), 0);
  assert.strictEqual(processEmitter.listenerCount('SIGBREAK'), 0);
});

test('runGateway bootstrap function runs GatewayRuntimeOwner cleanly', async () => {
  let started = false;
  let stopped = false;

  const mockOwner = {
    start: async () => {
      started = true;
    },
    stop: async () => {
      stopped = true;
    },
  };

  const result = await runGateway({ owner: mockOwner });
  assert.strictEqual(started, true);
  assert.strictEqual(result, mockOwner);
});

function createMockStderr() {
  let content = '';
  return {
    write(chunk) {
      content += chunk;
    },
    get content() {
      return content;
    },
  };
}

test('bootstrapGateway - CASE 0: zero enabled Telegram accounts fails closed with GATEWAY_CONFIG_ERROR (D-TG11-3)', async () => {
  const stderr = createMockStderr();
  let ownerStarted = false;

  const mockConfig = {
    dataLocations: { stateRoot: 'C:\\fake\\state' },
    gateway: { localPort: 3003 },
    accounts: {
      telegram: [
        { id: 'acc1', label: 'Disabled Account', enabled: false },
      ],
    },
  };

  const result = await bootstrapGateway({
    configPath: 'C:\\fake\\config.json',
    loadConfig: () => mockConfig,
    secretProvider: new FakeSecretProvider(),
    owner: {
      start: async () => { ownerStarted = true; },
    },
    stderr,
    exit: () => {},
  });

  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.code, 'GATEWAY_CONFIG_ERROR');
  assert.strictEqual(stderr.content, 'GATEWAY_CONFIG_ERROR\n');
  assert.strictEqual(ownerStarted, false, 'Runtime owner start MUST NOT be reached');
});

test('bootstrapGateway - CASE 1: exactly one enabled Telegram account activates sole account and starts owner (D-TG11-3)', async () => {
  const stderr = createMockStderr();
  let ownerStarted = false;
  let receivedDeps = null;
  let loaderOptionsPassed = null;

  const mockConfig = {
    dataLocations: { stateRoot: 'C:\\fake\\state' },
    gateway: { localPort: 3003 },
    accounts: {
      telegram: [
        { id: 'acc-disabled', label: 'Disabled', enabled: false },
        { id: 'acc-active', label: 'Sole Enabled', enabled: true },
      ],
    },
  };

  const fakeSecretProvider = new FakeSecretProvider();

  class MockOwner {
    constructor(deps) {
      receivedDeps = deps;
    }
    async start() {
      ownerStarted = true;
    }
  }

  const result = await bootstrapGateway({
    configPath: 'C:\\fake\\config.json',
    loadConfig: (_path, opts) => {
      loaderOptionsPassed = opts;
      return mockConfig;
    },
    secretProvider: fakeSecretProvider,
    RuntimeOwnerClass: MockOwner,
    stderr,
    exit: () => {},
  });

  assert.strictEqual(result.ok, true);
  assert.strictEqual(ownerStarted, true);
  assert.strictEqual(stderr.content, '');

  // Loader contract: repoRoot supplied & validateStartupLocations requested
  assert.ok(loaderOptionsPassed);
  assert.strictEqual(typeof loaderOptionsPassed.repoRoot, 'string');
  assert.strictEqual(loaderOptionsPassed.validateStartupLocations, true);

  // AccountRegistry: channel = telegram, sole enabled account active
  const registry = result.accountRegistry;
  assert.strictEqual(registry.channel, 'telegram');
  const active = registry.getActive();
  assert.ok(active);
  assert.strictEqual(active.id, 'acc-active');

  // Owner received correct dependencies
  assert.strictEqual(receivedDeps.accountRegistry, registry);
  assert.strictEqual(receivedDeps.secretProvider, fakeSecretProvider);
  assert.strictEqual(receivedDeps.stateRoot, 'C:\\fake\\state');
  assert.strictEqual(receivedDeps.config.gateway.localPort, 3003);
});

test('bootstrapGateway - CASE 2: two enabled Telegram accounts fails closed with GATEWAY_CONFIG_ERROR without arbitrary selection (D-TG11-3)', async () => {
  const stderr = createMockStderr();
  let ownerStarted = false;

  const mockConfig = {
    dataLocations: { stateRoot: 'C:\\fake\\state' },
    gateway: { localPort: 3003 },
    accounts: {
      telegram: [
        { id: 'acc1', label: 'First Account', enabled: true },
        { id: 'acc2', label: 'Second Account', enabled: true },
      ],
    },
  };

  const result = await bootstrapGateway({
    configPath: 'C:\\fake\\config.json',
    loadConfig: () => mockConfig,
    secretProvider: new FakeSecretProvider(),
    owner: {
      start: async () => { ownerStarted = true; },
    },
    stderr,
    exit: () => {},
  });

  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.code, 'GATEWAY_CONFIG_ERROR');
  assert.strictEqual(stderr.content, 'GATEWAY_CONFIG_ERROR\n');
  assert.strictEqual(ownerStarted, false, 'Runtime owner start MUST NOT be reached');
});

test('bootstrapGateway - post-config runtime startup failure emits strictly bounded GATEWAY_STARTUP_ERROR (R1-F8)', async () => {
  const stderr = createMockStderr();

  const mockConfig = {
    dataLocations: { stateRoot: 'C:\\fake\\state' },
    gateway: { localPort: 3003 },
    accounts: {
      telegram: [
        { id: 'acc-single', label: 'Single', enabled: true },
      ],
    },
  };

  const result = await bootstrapGateway({
    configPath: 'C:\\fake\\config.json',
    loadConfig: () => mockConfig,
    secretProvider: new FakeSecretProvider(),
    owner: {
      start: async () => {
        throw new Error('Secret internal connection string / port in use error: raw leak');
      },
    },
    stderr,
    exit: () => {},
  });

  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.code, 'GATEWAY_STARTUP_ERROR');
  assert.strictEqual(stderr.content, 'GATEWAY_STARTUP_ERROR\n');
  assert.strictEqual(stderr.content.includes('raw leak'), false, 'Raw error message MUST NOT be leaked');
});

test('resolveSecretProviderClass - returns concrete WindowsCredentialManagerSecretProvider by default without instantiation (R2-F1 / Test A)', () => {
  const { WindowsCredentialManagerSecretProvider } = require('../core/windows-credential-manager-provider');

  const resolved = resolveSecretProviderClass();
  assert.strictEqual(resolved, WindowsCredentialManagerSecretProvider);

  const resolvedEmpty = resolveSecretProviderClass({});
  assert.strictEqual(resolvedEmpty, WindowsCredentialManagerSecretProvider);
});

test('resolveSecretProviderClass - returns injected SecretProviderClass when provided (R2-F1 / Test B)', () => {
  class CustomSecretProvider {}
  const resolved = resolveSecretProviderClass({ SecretProviderClass: CustomSecretProvider });
  assert.strictEqual(resolved, CustomSecretProvider);
});

test('bootstrapGateway - instantiates SecretProviderClass when secretProvider instance is not supplied (R2-F1 / Test C)', async () => {
  let constructorCalled = false;
  class InjectedSecretProviderClass {
    constructor() {
      constructorCalled = true;
    }
  }

  const mockConfig = {
    dataLocations: { stateRoot: 'C:\\fake\\state' },
    gateway: { localPort: 3003 },
    accounts: {
      telegram: [
        { id: 'acc-single', label: 'Single Account', enabled: true },
      ],
    },
  };

  let capturedDeps = null;
  class MockOwner {
    constructor(deps) {
      capturedDeps = deps;
    }
    async start() {}
  }

  const result = await bootstrapGateway({
    configPath: 'C:\\fake\\config.json',
    loadConfig: () => mockConfig,
    SecretProviderClass: InjectedSecretProviderClass,
    RuntimeOwnerClass: MockOwner,
    exit: () => {},
  });

  assert.strictEqual(result.ok, true);
  assert.strictEqual(constructorCalled, true);
  assert.ok(capturedDeps.secretProvider instanceof InjectedSecretProviderClass);
  assert.strictEqual(result.accountRegistry.getActive().id, 'acc-single');
});
