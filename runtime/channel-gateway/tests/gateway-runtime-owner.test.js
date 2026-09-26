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
      recoverInFlightCommands: () => ({ requeuedCount: 0, uncertainCount: 0, total: 0 }),
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

class FakeTelegramOutboundAdapter {
  constructor() {
    this.started = false;
    this.stopped = false;
    this.isZeroized = false;
    this.deliveries = [];
  }

  async start() {
    this.started = true;
  }

  async stop() {
    this.stopped = true;
    this.isZeroized = true;
  }

  async deliver(cmd) {
    this.deliveries.push(cmd);
    return { success: true, http_status: 200, transport_phase: 'MAY_HAVE_BEEN_SENT' };
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

  const fakeOutbound = {
    start: async () => {
      lifecycleEvents.push('outbound.start');
    },
    stop: async () => {
      lifecycleEvents.push('outbound.stop');
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

  const fakeWorker = {
    start: async () => {
      lifecycleEvents.push('worker.start');
    },
    stop: async () => {
      lifecycleEvents.push('worker.stop');
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
    telegramOutboundAdapter: fakeOutbound,
    outboxWorker: fakeWorker,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    processEmitter,
  });

  assert.strictEqual(owner.status, OWNER_STATUS.INITIALIZED);
  await owner.start();

  assert.strictEqual(owner.status, OWNER_STATUS.RUNNING);
  assert.strictEqual(owner.isRunning, true);

  // Assert startup order: 1. backup, 2. outbound, 3. worker, 4. server, 5. adapter
  assert.deepStrictEqual(lifecycleEvents, [
    'backup.start',
    'outbound.start',
    'worker.start',
    'server.start',
    'adapter.start',
  ]);

  // Execute graceful stop
  lifecycleEvents.length = 0;
  await owner.stop();

  assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);
  assert.strictEqual(owner.isRunning, false);

  // Assert stop order (Mutation T17 requirement & §22/§26):
  // adapter.stop() and worker.stop() and outbound.stop() MUST happen BEFORE backup.stop() / repo close
  // worker.stop() MUST happen BEFORE outbound.stop() (quiesce before zeroization)
  const adapterStopIdx = lifecycleEvents.indexOf('adapter.stop');
  const workerStopIdx = lifecycleEvents.indexOf('worker.stop');
  const outboundStopIdx = lifecycleEvents.indexOf('outbound.stop');
  const backupStopIdx = lifecycleEvents.indexOf('backup.stop');
  assert.ok(adapterStopIdx !== -1, 'adapter.stop must be called');
  assert.ok(workerStopIdx !== -1, 'worker.stop must be called');
  assert.ok(outboundStopIdx !== -1, 'outbound.stop must be called');
  assert.ok(backupStopIdx !== -1, 'backup.stop must be called');
  assert.ok(
    adapterStopIdx < backupStopIdx,
    'adapter.stop must complete before backup.stop'
  );
  assert.ok(
    workerStopIdx < outboundStopIdx,
    'worker.stop must complete before outbound.stop'
  );
  assert.ok(
    outboundStopIdx < backupStopIdx,
    'outbound.stop must complete before backup.stop'
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

  const fakeOutbound = {
    start: async () => {
      rollbackEvents.push('outbound.start');
    },
    stop: async () => {
      rollbackEvents.push('outbound.stop');
    },
  };

  const fakeWorker = {
    start: async () => {
      rollbackEvents.push('worker.start');
    },
    stop: async () => {
      rollbackEvents.push('worker.stop');
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
    telegramOutboundAdapter: fakeOutbound,
    outboxWorker: fakeWorker,
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

  // Rollback order: server.stop -> worker.stop -> outbound.stop -> backup.stop
  assert.ok(rollbackEvents.includes('server.stop'));
  assert.ok(rollbackEvents.includes('worker.stop'));
  assert.ok(rollbackEvents.includes('outbound.stop'));
  assert.ok(rollbackEvents.includes('backup.stop'));
  const outboundStopIdx = rollbackEvents.indexOf('outbound.stop');
  const backupStopIdx = rollbackEvents.indexOf('backup.stop');
  assert.ok(outboundStopIdx < backupStopIdx, 'outbound.stop must occur before backup.stop on rollback');

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

  const fakeOutbound = {
    start: async () => {
      rollbackEvents.push('outbound.start');
    },
    stop: async () => {
      rollbackEvents.push('outbound.stop');
    },
  };

  const fakeWorker = {
    start: async () => {
      rollbackEvents.push('worker.start');
    },
    stop: async () => {
      rollbackEvents.push('worker.stop');
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
    telegramOutboundAdapter: fakeOutbound,
    outboxWorker: fakeWorker,
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
  assert.ok(rollbackEvents.includes('worker.stop'), 'Worker must be stopped on server bind rollback');
  assert.ok(rollbackEvents.includes('outbound.stop'), 'Outbound must be stopped on server bind rollback');
  assert.ok(rollbackEvents.includes('backup.stop'), 'Backup owner must be stopped on server bind rollback');

  // Secret must be zeroized on rollback
  assert.ok(fakeProvider.lastReturnedBuffer);
  for (let i = 0; i < fakeProvider.lastReturnedBuffer.length; i++) {
    assert.strictEqual(fakeProvider.lastReturnedBuffer[i], 0);
  }
});

test('GatewayRuntimeOwner startup rollback when TelegramOutboundAdapter fails to start', async () => {
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

  const fakeOutbound = {
    start: async () => {
      rollbackEvents.push('outbound.start');
      throw new Error('TELEGRAM_OUTBOUND_STARTUP_FAILURE');
    },
    stop: async () => {
      rollbackEvents.push('outbound.stop');
    },
  };

  let workerStarted = false;
  const fakeWorker = {
    start: async () => {
      workerStarted = true;
    },
    stop: async () => {},
  };

  const owner = new GatewayRuntimeOwner({
    stateRoot: 'C:\\fake\\stateRoot',
    secretProvider: fakeProvider,
    backupRuntimeOwner: fakeBackup,
    telegramOutboundAdapter: fakeOutbound,
    outboxWorker: fakeWorker,
  });

  await assert.rejects(
    async () => {
      await owner.start();
    },
    /TELEGRAM_OUTBOUND_STARTUP_FAILURE/
  );

  assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);
  assert.strictEqual(workerStarted, false, 'Worker must not start if outbound adapter fails');
  assert.ok(rollbackEvents.includes('backup.stop'), 'Backup owner must be stopped on rollback');
});

test('GatewayRuntimeOwner signal handling triggers stop and removes listeners', async () => {
  const processEmitter = new EventEmitter();
  const fakeProvider = new FakeSecretProvider();

  let backupStopped = false;
  let workerStopped = false;
  let outboundStopped = false;
  const fakeBackup = {
    repository: {
      recoverInFlightCommands: () => ({ requeuedCount: 0, uncertainCount: 0, total: 0 }),
    },
    start: () => {},
    stop: () => {
      backupStopped = true;
    },
  };

  const fakeOutbound = {
    start: async () => {},
    stop: async () => {
      outboundStopped = true;
    },
  };

  const fakeWorker = {
    start: async () => {},
    stop: async () => {
      workerStopped = true;
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
    telegramOutboundAdapter: fakeOutbound,
    outboxWorker: fakeWorker,
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
  assert.strictEqual(workerStopped, true);
  assert.strictEqual(outboundStopped, true);
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

test('GatewayRuntimeOwner passes accountRegistry to dispatcherFactory and LocalApiDispatcher (ADR-0025)', async () => {
  const fakeAccountRegistry = {
    getActive: () => ({ id: 'acc-active', channel: 'telegram' }),
    get: (id) => ({ id, channel: 'telegram' }),
  };

  let capturedDispatcherDeps = null;
  const fakeDispatcherFactory = (deps) => {
    capturedDispatcherDeps = deps;
    return { dispatch: () => ({ status: 200, body: {} }) };
  };

  const fakeBackup = {
    repository: { isClosed: false, close: () => {} },
    start: () => {},
    stop: () => {},
  };

  const fakeServer = {
    start: async () => {},
    stop: async () => {},
  };

  const fakeAdapter = {
    start: async () => {},
    stop: async () => {},
  };

  const fakeWorker = {
    start: async () => {},
    stop: async () => {},
  };

  const owner = new GatewayRuntimeOwner({
    accountRegistry: fakeAccountRegistry,
    backupRuntimeOwner: fakeBackup,
    telegramOutboundAdapter: new FakeTelegramOutboundAdapter(),
    outboxWorker: fakeWorker,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    dispatcherFactory: fakeDispatcherFactory,
    secretBuffer: Buffer.alloc(32),
  });

  await owner.start();
  try {
    assert.ok(capturedDispatcherDeps);
    assert.strictEqual(capturedDispatcherDeps.accountRegistry, fakeAccountRegistry);
    assert.strictEqual(capturedDispatcherDeps.repository, fakeBackup.repository);
  } finally {
    await owner.stop();
  }
});

test('production-wiring: Gateway start calls OutboxWorker.start()', async () => {
  let workerStarted = false;
  const fakeBackup = {
    repository: { isClosed: false },
    start: () => {},
    stop: () => {},
  };
  const fakeWorker = {
    start: async () => {
      workerStarted = true;
    },
    stop: async () => {},
  };
  const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };
  const fakeAdapter = { start: async () => {}, stop: async () => {} };
  const owner = new GatewayRuntimeOwner({
    stateRoot: 'C:\\fake\\state',
    backupRuntimeOwner: fakeBackup,
    telegramOutboundAdapter: new FakeTelegramOutboundAdapter(),
    outboxWorker: fakeWorker,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    secretBuffer: Buffer.alloc(32),
  });

  await owner.start();
  assert.strictEqual(workerStarted, true);
  assert.strictEqual(owner.outboxWorker, fakeWorker);
  await owner.stop();
});

test('production-wiring: Gateway stop calls OutboxWorker.stop() before repository close', async () => {
  const events = [];
  const fakeBackup = {
    repository: { isClosed: false },
    start: () => {},
    stop: () => {
      events.push('backup.stop');
      fakeBackup.repository.isClosed = true;
    },
  };
  const fakeWorker = {
    start: async () => {},
    stop: async () => {
      events.push('worker.stop');
      assert.strictEqual(fakeBackup.repository.isClosed, false, 'Repository must still be open when OutboxWorker stops');
    },
  };
  const fakeOutbound = {
    start: async () => {},
    stop: async () => {
      events.push('outbound.stop');
      assert.strictEqual(fakeBackup.repository.isClosed, false, 'Repository must still be open when outbound adapter stops');
    },
  };
  const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };
  const fakeAdapter = { start: async () => {}, stop: async () => {} };
  const owner = new GatewayRuntimeOwner({
    stateRoot: 'C:\\fake\\state',
    backupRuntimeOwner: fakeBackup,
    telegramOutboundAdapter: fakeOutbound,
    outboxWorker: fakeWorker,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    secretBuffer: Buffer.alloc(32),
  });

  await owner.start();
  await owner.stop();
  assert.deepStrictEqual(events, ['worker.stop', 'outbound.stop', 'backup.stop']);
});

test('production-wiring: startup failure rollback stops an already-started worker', async () => {
  const events = [];
  const fakeBackup = {
    repository: {},
    start: () => { events.push('backup.start'); },
    stop: () => { events.push('backup.stop'); },
  };
  const fakeOutbound = {
    start: async () => { events.push('outbound.start'); },
    stop: async () => { events.push('outbound.stop'); },
  };
  const fakeWorker = {
    start: async () => { events.push('worker.start'); },
    stop: async () => { events.push('worker.stop'); },
  };
  const fakeServer = {
    start: async () => {
      events.push('server.start');
      throw new Error('SERVER_START_FAIL');
    },
    stop: async () => {},
  };
  const fakeAdapter = { start: async () => {}, stop: async () => {} };
  const owner = new GatewayRuntimeOwner({
    stateRoot: 'C:\\fake\\state',
    backupRuntimeOwner: fakeBackup,
    telegramOutboundAdapter: fakeOutbound,
    outboxWorker: fakeWorker,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    secretBuffer: Buffer.alloc(32),
  });

  await assert.rejects(async () => { await owner.start(); }, /SERVER_START_FAIL/);
  assert.ok(events.includes('worker.stop'), 'worker.stop must be called on rollback');
  assert.ok(events.includes('outbound.stop'), 'outbound.stop must be called on rollback');
  const workerStopIdx = events.indexOf('worker.stop');
  const outboundStopIdx = events.indexOf('outbound.stop');
  const backupStopIdx = events.indexOf('backup.stop');
  assert.ok(workerStopIdx < backupStopIdx, 'worker.stop must occur before backup.stop on rollback');
  assert.ok(outboundStopIdx < backupStopIdx, 'outbound.stop must occur before backup.stop on rollback');
});

test('production-wiring: GatewayRuntimeOwner wires TelegramOutboundAdapter.deliver as default OutboxWorker deliveryExecutor', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const os = require('node:os');
  const { SqliteStateRepository } = require('../core/sqlite-state-repository');
  const { computeCanonicalPayloadHash } = require('../core/outbox-delivery-policy');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-gw-wiring-exec-'));
  const repo = new SqliteStateRepository(dir);
  try {
    repo.takeoverChannel('tg:chat:w1', 'holder1');
    const rawDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
    try {
      rawDb
        .prepare(
          `INSERT INTO inbox (channel_id, account_id, platform_msg_id, status, content, claimed_by, claimed_at_token)
           VALUES ('tg:chat:w1', 'acc_tg', 'tg:w1:1', 'claimed', 'test content', 'holder1', 1);`
        )
        .run();
    } finally {
      rawDb.close();
    }

    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: 'w1',
      logical_reply_target: 'tg:w1:1',
      message_type: 'text',
      body: 'Executor wiring test',
    });

    const enqueueRes = repo.enqueueAuthorizedReply({
      clientRequestId: 'req_w1',
      channelId: 'tg:chat:w1',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:w1:1',
      replyingAccountId: 'acc_tg',
      text: 'Executor wiring test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: 'w1',
      logicalReplyTarget: 'tg:w1:1',
      messageType: 'text',
      payloadHash: hash,
    });
    const cmdId = enqueueRes.commandId;

    const fakeBackup = {
      repository: repo,
      start: () => {},
      stop: () => {},
    };
    const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };
    const fakeAdapter = { start: async () => {}, stop: async () => {} };

    const fakeOutbound = new FakeTelegramOutboundAdapter();

    const owner = new GatewayRuntimeOwner({
      stateRoot: dir,
      backupRuntimeOwner: fakeBackup,
      telegramOutboundAdapter: fakeOutbound,
      // no deliveryExecutor provided: wires fakeOutbound.deliver automatically
      localApiServer: fakeServer,
      telegramAdapter: fakeAdapter,
      secretBuffer: Buffer.alloc(32),
    });

    await owner.start();
    assert.ok(owner.outboxWorker);
    assert.strictEqual(owner.outboxWorker.hasActiveTimer, true);

    await new Promise((resolve) => setTimeout(resolve, 50));

    assert.strictEqual(fakeOutbound.deliveries.length, 1);
    assert.strictEqual(fakeOutbound.deliveries[0].command_id, cmdId);

    const cmd = repo.getOutboxCommand(cmdId);
    assert.strictEqual(cmd.status, 'ACCEPTED_BY_PLATFORM');
    assert.strictEqual(cmd.attempt_count, 1);

    await owner.stop();
  } finally {
    repo.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('production-wiring: Gateway restart path causes Telegram IN_FLIGHT -> UNCERTAIN', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const os = require('node:os');
  const { SqliteStateRepository } = require('../core/sqlite-state-repository');
  const { computeCanonicalPayloadHash } = require('../core/outbox-delivery-policy');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-gw-wiring-restart-'));
  const repo1 = new SqliteStateRepository(dir);
  let cmdId;
  try {
    repo1.takeoverChannel('tg:chat:w2', 'holder1');
    const rawDb = new (require('node:sqlite').DatabaseSync)(repo1.databasePath);
    try {
      rawDb
        .prepare(
          `INSERT INTO inbox (channel_id, account_id, platform_msg_id, status, content, claimed_by, claimed_at_token)
           VALUES ('tg:chat:w2', 'acc_tg', 'tg:w2:1', 'claimed', 'test content', 'holder1', 1);`
        )
        .run();
    } finally {
      rawDb.close();
    }

    const hash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'acc_tg',
      endpoint_operation: 'sendMessage',
      recipient: 'w2',
      logical_reply_target: 'tg:w2:1',
      message_type: 'text',
      body: 'Restart recovery test',
    });

    const enqueueRes = repo1.enqueueAuthorizedReply({
      clientRequestId: 'req_w2',
      channelId: 'tg:chat:w2',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:w2:1',
      replyingAccountId: 'acc_tg',
      text: 'Restart recovery test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: 'w2',
      logicalReplyTarget: 'tg:w2:1',
      messageType: 'text',
      payloadHash: hash,
    });
    cmdId = enqueueRes.commandId;

    // Transition to IN_FLIGHT before simulated crash
    const claimed = repo1.claimNextQueuedOutboxCommand();
    assert.strictEqual(claimed.command_id, cmdId);
    assert.strictEqual(claimed.status, 'IN_FLIGHT');
  } finally {
    repo1.close();
  }

  // Simulated gateway restart: new repo, new GatewayRuntimeOwner with production OutboxWorker
  const repo2 = new SqliteStateRepository(dir);
  try {
    const fakeBackup = {
      repository: repo2,
      start: () => {},
      stop: () => {},
    };
    const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };
    const fakeAdapter = { start: async () => {}, stop: async () => {} };

    const owner = new GatewayRuntimeOwner({
      stateRoot: dir,
      backupRuntimeOwner: fakeBackup,
      telegramOutboundAdapter: new FakeTelegramOutboundAdapter(),
      localApiServer: fakeServer,
      telegramAdapter: fakeAdapter,
      secretBuffer: Buffer.alloc(32),
    });

    // Start runs OutboxWorker recovery on restart
    await owner.start();

    // Verify Telegram IN_FLIGHT became UNCERTAIN
    const recoveredCmd = repo2.getOutboxCommand(cmdId);
    assert.strictEqual(recoveredCmd.status, 'UNCERTAIN');

    await owner.stop();
  } finally {
    repo2.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

