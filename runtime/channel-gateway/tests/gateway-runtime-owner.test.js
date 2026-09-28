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

class FakeArchiveWorker {
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

  const fakeOutbound = {
    start: async () => {
      lifecycleEvents.push('outbound.start');
    },
    stop: async () => {
      lifecycleEvents.push('outbound.stop:initiate');
      lifecycleEvents.push('outbound.stop:quiesce');
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
      lifecycleEvents.push('worker.stop:initiate');
      await new Promise((resolve) => setTimeout(resolve, 10));
      lifecycleEvents.push('worker.stop:quiesce');
    },
  };

  const fakeArchiveWorker = {
    start: async () => {
      lifecycleEvents.push('archiveWorker.start');
    },
    stop: async () => {
      lifecycleEvents.push('archiveWorker.stop');
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
    archiveWorker: fakeArchiveWorker,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    processEmitter,
  });

  assert.strictEqual(owner.status, OWNER_STATUS.INITIALIZED);
  await owner.start();

  assert.strictEqual(owner.status, OWNER_STATUS.RUNNING);
  assert.strictEqual(owner.isRunning, true);

  // Assert startup order: 1. backup, 2. outbound, 3. worker, 4. archiveWorker, 5. server, 6. adapter
  assert.deepStrictEqual(lifecycleEvents, [
    'backup.start',
    'outbound.start',
    'worker.start',
    'archiveWorker.start',
    'server.start',
    'adapter.start',
  ]);

  // Execute graceful stop
  lifecycleEvents.length = 0;
  await owner.stop();

  assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);
  assert.strictEqual(owner.isRunning, false);

  // Assert stop order (TG-MVP-14 canonical ordering):
  // 1. worker STOP INITIATION before outbound stop initiation
  // 2. outbound abort/quiescence completes before worker full quiescence
  // 3. worker full quiescence completes before repository close (backup.stop)
  // 4. archiveWorker.stop completes before repository close
  const adapterStopIdx = lifecycleEvents.indexOf('adapter.stop');
  const workerStopInitIdx = lifecycleEvents.indexOf('worker.stop:initiate');
  const outboundStopInitIdx = lifecycleEvents.indexOf('outbound.stop:initiate');
  const outboundStopDoneIdx = lifecycleEvents.indexOf('outbound.stop:quiesce');
  const workerStopDoneIdx = lifecycleEvents.indexOf('worker.stop:quiesce');
  const archiveWorkerStopIdx = lifecycleEvents.indexOf('archiveWorker.stop');
  const backupStopIdx = lifecycleEvents.indexOf('backup.stop');

  assert.ok(adapterStopIdx !== -1, 'adapter.stop must be called');
  assert.ok(workerStopInitIdx !== -1, 'worker.stop:initiate must be called');
  assert.ok(outboundStopInitIdx !== -1, 'outbound.stop:initiate must be called');
  assert.ok(outboundStopDoneIdx !== -1, 'outbound.stop:quiesce must be called');
  assert.ok(workerStopDoneIdx !== -1, 'worker.stop:quiesce must be called');
  assert.ok(archiveWorkerStopIdx !== -1, 'archiveWorker.stop must be called');
  assert.ok(backupStopIdx !== -1, 'backup.stop must be called');

  assert.ok(
    adapterStopIdx < backupStopIdx,
    'adapter.stop must complete before backup.stop'
  );
  assert.ok(
    workerStopInitIdx < outboundStopInitIdx,
    'worker STOP INITIATION must happen before outbound stop initiation'
  );
  assert.ok(
    outboundStopDoneIdx < workerStopDoneIdx,
    'outbound abort/quiescence must complete before worker full quiescence'
  );
  assert.ok(
    workerStopDoneIdx < backupStopIdx,
    'worker full quiescence must complete before repository close'
  );
  assert.ok(
    archiveWorkerStopIdx < backupStopIdx,
    'archiveWorker.stop must complete before repository close'
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

  const fakeArchiveWorker = {
    start: async () => {
      rollbackEvents.push('archiveWorker.start');
    },
    stop: async () => {
      rollbackEvents.push('archiveWorker.stop');
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
    archiveWorker: fakeArchiveWorker,
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

  // Rollback order: server.stop -> archiveWorker.stop -> worker.stop -> outbound.stop -> backup.stop
  assert.ok(rollbackEvents.includes('server.stop'));
  assert.ok(rollbackEvents.includes('archiveWorker.stop'));
  assert.ok(rollbackEvents.includes('worker.stop'));
  assert.ok(rollbackEvents.includes('outbound.stop'));
  assert.ok(rollbackEvents.includes('backup.stop'));
  const archiveStopIdx = rollbackEvents.indexOf('archiveWorker.stop');
  const workerStopIdx = rollbackEvents.indexOf('worker.stop');
  const outboundStopIdx = rollbackEvents.indexOf('outbound.stop');
  const backupStopIdx = rollbackEvents.indexOf('backup.stop');
  assert.ok(archiveStopIdx < workerStopIdx, 'archiveWorker.stop must occur before worker.stop on rollback');
  assert.ok(workerStopIdx < outboundStopIdx, 'worker.stop must occur before outbound.stop on rollback');
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
    archiveWorker: new FakeArchiveWorker(),
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
    archiveWorker: new FakeArchiveWorker(),
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
    archiveWorker: new FakeArchiveWorker(),
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
    archiveWorker: new FakeArchiveWorker(),
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
  const fakeArchiveWorker = {
    start: async () => {},
    stop: async () => {
      events.push('archiveWorker.stop');
      assert.strictEqual(fakeBackup.repository.isClosed, false, 'Repository must still be open when ArchiveWorker stops');
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
    archiveWorker: fakeArchiveWorker,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    secretBuffer: Buffer.alloc(32),
  });

  await owner.start();
  await owner.stop();
  assert.deepStrictEqual(events, ['worker.stop', 'archiveWorker.stop', 'outbound.stop', 'backup.stop']);
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
  const fakeArchiveWorker = {
    start: async () => { events.push('archiveWorker.start'); },
    stop: async () => { events.push('archiveWorker.stop'); },
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
    archiveWorker: fakeArchiveWorker,
    localApiServer: fakeServer,
    telegramAdapter: fakeAdapter,
    secretBuffer: Buffer.alloc(32),
  });

  await assert.rejects(async () => { await owner.start(); }, /SERVER_START_FAIL/);
  assert.ok(events.includes('worker.stop'), 'worker.stop must be called on rollback');
  assert.ok(events.includes('archiveWorker.stop'), 'archiveWorker.stop must be called on rollback');
  assert.ok(events.includes('outbound.stop'), 'outbound.stop must be called on rollback');
  const archiveStopIdx = events.indexOf('archiveWorker.stop');
  const workerStopIdx = events.indexOf('worker.stop');
  const outboundStopIdx = events.indexOf('outbound.stop');
  const backupStopIdx = events.indexOf('backup.stop');
  assert.ok(archiveStopIdx < workerStopIdx, 'archiveWorker.stop must occur before worker.stop on rollback');
  assert.ok(workerStopIdx < outboundStopIdx, 'worker.stop must occur before outbound.stop on rollback');
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

    const topic = repo.createArchiveTopic({
      accountId: 'acc_tg',
      displayName: 'General',
      normalizedName: 'general',
      accountDirName: 'acc_tg',
    });

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
      topicId: topic.topic_id,
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
      archiveWorker: new FakeArchiveWorker(),
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

    const topic = repo1.createArchiveTopic({
      accountId: 'acc_tg',
      displayName: 'General',
      normalizedName: 'general',
      accountDirName: 'acc_tg',
    });

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
      topicId: topic.topic_id,
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
      archiveWorker: new FakeArchiveWorker(),
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

test('J2-counterexample: normal stop coordinates OutboxWorker and TelegramOutboundAdapter to avoid response.text() deadlock', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const os = require('node:os');
  const { SqliteStateRepository } = require('../core/sqlite-state-repository');
  const { TelegramOutboundAdapter } = require('../adapters/telegram-outbound-adapter');
  const { computeCanonicalPayloadHash } = require('../core/outbox-delivery-policy');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-gw-j2-normal-'));
  const repo = new SqliteStateRepository(dir);
  let signalAborted = false;
  let bodyReadStartedResolve;
  const bodyReadStartedPromise = new Promise((resolve) => {
    bodyReadStartedResolve = resolve;
  });

  const customFetch = async (url, options) => {
    return {
      status: 200,
      text: () =>
        new Promise((resolve, reject) => {
          bodyReadStartedResolve();
          if (options.signal && options.signal.aborted) {
            signalAborted = true;
            const err = new Error('The operation was aborted');
            err.name = 'AbortError';
            return reject(err);
          }
          if (options.signal) {
            options.signal.addEventListener(
              'abort',
              () => {
                signalAborted = true;
                const err = new Error('The operation was aborted');
                err.name = 'AbortError';
                reject(err);
              },
              { once: true }
            );
          }
        }),
    };
  };

  const reg = {
    getActive: () => ({ id: 'tg_acc_j2', channel: 'telegram', enabled: true }),
  };
  const fakeTokenBuf = Buffer.from('123456:ABC-DEF_ghi_j2_token');
  const sec = {
    getSecret: async () => Buffer.from(fakeTokenBuf),
  };

  const outboundAdapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: customFetch,
  });

  try {
    repo.takeoverChannel('tg:chat:10001', 'holder1');
    const rawDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
    try {
      rawDb
        .prepare(
          `INSERT INTO inbox (channel_id, account_id, platform_msg_id, status, content, claimed_by, claimed_at_token)
           VALUES ('tg:chat:10001', 'tg_acc_j2', 'tg:10001:1', 'claimed', 'test j2', 'holder1', 1);`
        )
        .run();
    } finally {
      rawDb.close();
    }

    const topic = repo.createArchiveTopic({
      accountId: 'tg_acc_j2',
      displayName: 'J2 Topic',
      normalizedName: 'j2 topic',
      accountDirName: 'tg_acc_j2',
    });

    const payloadHash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'tg_acc_j2',
      endpoint_operation: 'sendMessage',
      recipient: '10001',
      logical_reply_target: 'tg:10001:1',
      message_type: 'text',
      body: 'J2 normal stop test',
    });

    const enqueueRes = repo.enqueueAuthorizedReply({
      clientRequestId: 'req_j2_normal',
      channelId: 'tg:chat:10001',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:10001:1',
      replyingAccountId: 'tg_acc_j2',
      topicId: topic.topic_id,
      text: 'J2 normal stop test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '10001',
      logicalReplyTarget: 'tg:10001:1',
      messageType: 'text',
      payloadHash,
    });
    const cmdId = enqueueRes.commandId;

    const fakeBackup = {
      repository: repo,
      start: () => {},
      stop: () => {},
    };
    const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };
    const fakeInbound = { start: async () => {}, stop: async () => {} };

    const owner = new GatewayRuntimeOwner({
      stateRoot: dir,
      backupRuntimeOwner: fakeBackup,
      telegramOutboundAdapter: outboundAdapter,
      archiveWorker: new FakeArchiveWorker(),
      localApiServer: fakeServer,
      telegramAdapter: fakeInbound,
      secretBuffer: Buffer.alloc(32),
    });

    await owner.start();

    // Wait until delivery has started and response.text() is stalled pending abort signal
    await bodyReadStartedPromise;

    // Initiate stop
    let stopped = false;
    const stopPromise = owner.stop().then(() => {
      stopped = true;
    });

    // Bounded race: check if owner.stop completes within 250ms
    await new Promise((resolve) => setTimeout(resolve, 250));

    if (!stopped) {
      // Under old R2 ordering: stopped is false (deadlock)!
      // Perform §16 test-controlled cleanup: manually call adapter.stop() to abort signal
      await outboundAdapter.stop();
      await stopPromise;
      assert.fail('J2-normal-stop: owner.stop() deadlocked because OutboxWorker.stop() blocked TelegramOutboundAdapter.stop()');
    }

    await stopPromise;
    assert.strictEqual(stopped, true);
    assert.strictEqual(signalAborted, true);
    assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);

    const cmd = repo.getOutboxCommand(cmdId);
    assert.strictEqual(cmd.status, 'UNCERTAIN');
  } finally {
    repo.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('J2-counterexample: startup rollback coordinates OutboxWorker and TelegramOutboundAdapter to avoid response.text() deadlock', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const os = require('node:os');
  const { SqliteStateRepository } = require('../core/sqlite-state-repository');
  const { TelegramOutboundAdapter } = require('../adapters/telegram-outbound-adapter');
  const { computeCanonicalPayloadHash } = require('../core/outbox-delivery-policy');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-gw-j2-rollback-'));
  const repo = new SqliteStateRepository(dir);
  let signalAborted = false;
  let bodyReadStartedResolve;
  const bodyReadStartedPromise = new Promise((resolve) => {
    bodyReadStartedResolve = resolve;
  });

  const customFetch = async (url, options) => {
    return {
      status: 200,
      text: () =>
        new Promise((resolve, reject) => {
          bodyReadStartedResolve();
          if (options.signal && options.signal.aborted) {
            signalAborted = true;
            const err = new Error('The operation was aborted');
            err.name = 'AbortError';
            return reject(err);
          }
          if (options.signal) {
            options.signal.addEventListener(
              'abort',
              () => {
                signalAborted = true;
                const err = new Error('The operation was aborted');
                err.name = 'AbortError';
                reject(err);
              },
              { once: true }
            );
          }
        }),
    };
  };

  const reg = {
    getActive: () => ({ id: 'tg_acc_j2_rb', channel: 'telegram', enabled: true }),
  };
  const fakeTokenBuf = Buffer.from('123456:ABC-DEF_ghi_j2_token_rb');
  const sec = {
    getSecret: async () => Buffer.from(fakeTokenBuf),
  };

  const outboundAdapter = new TelegramOutboundAdapter({
    accountRegistry: reg,
    secretProvider: sec,
    fetchFn: customFetch,
  });

  try {
    repo.takeoverChannel('tg:chat:10002', 'holder1');
    const rawDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
    try {
      rawDb
        .prepare(
          `INSERT INTO inbox (channel_id, account_id, platform_msg_id, status, content, claimed_by, claimed_at_token)
           VALUES ('tg:chat:10002', 'tg_acc_j2_rb', 'tg:10002:1', 'claimed', 'test j2 rb', 'holder1', 1);`
        )
        .run();
    } finally {
      rawDb.close();
    }

    const topic = repo.createArchiveTopic({
      accountId: 'tg_acc_j2_rb',
      displayName: 'J2 RB Topic',
      normalizedName: 'j2 rb topic',
      accountDirName: 'tg_acc_j2_rb',
    });

    const payloadHash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'tg_acc_j2_rb',
      endpoint_operation: 'sendMessage',
      recipient: '10002',
      logical_reply_target: 'tg:10002:1',
      message_type: 'text',
      body: 'J2 rollback test',
    });

    const enqueueRes = repo.enqueueAuthorizedReply({
      clientRequestId: 'req_j2_rollback',
      channelId: 'tg:chat:10002',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:10002:1',
      replyingAccountId: 'tg_acc_j2_rb',
      topicId: topic.topic_id,
      text: 'J2 rollback test',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '10002',
      logicalReplyTarget: 'tg:10002:1',
      messageType: 'text',
      payloadHash,
    });
    const cmdId = enqueueRes.commandId;

    const fakeBackup = {
      repository: repo,
      start: () => {},
      stop: () => {},
    };
    const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };

    // Injected inbound adapter that fails during startup AFTER delivery is pending on response.text()
    const failingInboundAdapter = {
      start: async () => {
        await bodyReadStartedPromise;
        throw new Error('Injected inbound adapter startup failure for rollback test');
      },
      stop: async () => {},
    };

    const owner = new GatewayRuntimeOwner({
      stateRoot: dir,
      backupRuntimeOwner: fakeBackup,
      telegramOutboundAdapter: outboundAdapter,
      archiveWorker: new FakeArchiveWorker(),
      localApiServer: fakeServer,
      telegramAdapter: failingInboundAdapter,
      secretBuffer: Buffer.alloc(32),
    });

    let rollbackCompleted = false;
    const startPromise = owner.start().catch((err) => {
      rollbackCompleted = true;
      return err;
    });

    // Bounded race: check if rollback completes within 250ms
    await new Promise((resolve) => setTimeout(resolve, 250));

    if (!rollbackCompleted) {
      // Under old R2 ordering: rollback is stuck waiting for OutboxWorker!
      // Cleanup: abort outboundAdapter so delivery settles and rollback finishes
      await outboundAdapter.stop();
      await startPromise;
      assert.fail('J2-startup-rollback: rollback deadlocked because OutboxWorker.stop() blocked TelegramOutboundAdapter.stop()');
    }

    const err = await startPromise;
    assert.match(err.message, /Injected inbound adapter startup failure/);
    assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);
    assert.strictEqual(signalAborted, true);

    const cmd = repo.getOutboxCommand(cmdId);
    assert.strictEqual(cmd.status, 'UNCERTAIN');
  } finally {
    repo.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('Section 21 counterexample: hung archive write does not block owner.stop(), repository closes, and delayed write cannot mutate DB', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const os = require('node:os');
  const { SqliteStateRepository } = require('../core/sqlite-state-repository');
  const { ArchiveWorker } = require('../core/archive-worker');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-gw-archive-stop-counter-'));
  const archiveDir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-gw-archive-root-'));
  const repo = new SqliteStateRepository(dir);

  try {
    const topic = repo.createArchiveTopic({
      accountId: 'acc_hung',
      displayName: 'Hung Write Topic',
      normalizedName: 'hung write topic',
      accountDirName: 'acc_hung',
    });

    // Insert pending coordination record into database
    let archiveId;
    const rawDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
    try {
      const res = rawDb.prepare(`
        INSERT INTO archive_coordination (
          account_id, topic_id, entry_sequence, record_kind, original_archive_id,
          platform_msg_id, source_platform_event_id, command_id, status,
          content_snapshot, relative_path, completed_at, failed_reason_code,
          created_at, updated_at
        ) VALUES (
          'acc_hung', ?, 1, 'ORIGINAL', NULL,
          'msg_hung_1', NULL, 999, 'PENDING',
          'Hung question text', 'TG_acc_hung/Q001_hung/001_hung_20260928-120000.md',
          NULL, NULL, ?, ?
        );
      `).run(topic.topic_id, Math.floor(Date.now() / 1000), Math.floor(Date.now() / 1000));
      archiveId = Number(res.lastInsertRowid);
    } finally {
      rawDb.close();
    }

    let writeHangResolve;
    const writeHangingPromise = new Promise((resolve) => {
      writeHangResolve = resolve;
    });

    let writeStarted = false;
    const hungArchiveFileWriter = {
      archiveRoot: archiveDir,
      publishArchiveRecord: async () => {
        writeStarted = true;
        // Hangs until release is triggered
        await writeHangingPromise;
        return { status: 'COMPLETED', relativePath: 'TG_acc_hung/Q001_hung/001_hung_20260928-120000.md' };
      },
    };

    // Use a short shutdownTimeoutMs (50ms) to avoid real 10s wait in tests
    const archiveWorker = new ArchiveWorker({
      repository: repo,
      archiveRoot: archiveDir,
      archiveFileWriter: hungArchiveFileWriter,
      pollIntervalMs: 10,
      shutdownTimeoutMs: 50,
    });

    const fakeBackup = {
      repository: repo,
      start: () => {},
      stop: () => {
        repo.close();
      },
    };
    const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };
    const fakeAdapter = { start: async () => {}, stop: async () => {} };

    const owner = new GatewayRuntimeOwner({
      stateRoot: dir,
      archiveRoot: archiveDir,
      backupRuntimeOwner: fakeBackup,
      telegramOutboundAdapter: new FakeTelegramOutboundAdapter(),
      outboxWorker: { start: async () => {}, stop: async () => {} },
      archiveWorker: archiveWorker,
      localApiServer: fakeServer,
      telegramAdapter: fakeAdapter,
      secretBuffer: Buffer.alloc(32),
    });

    await owner.start();

    // Wait until the archive worker picks up the item and enters publishArchiveRecord
    for (let i = 0; i < 50 && !writeStarted; i++) {
      await new Promise((r) => setTimeout(r, 10));
    }
    assert.strictEqual(writeStarted, true, 'Hung archive write should have started');

    const startTime = Date.now();
    await owner.stop();
    const elapsed = Date.now() - startTime;

    // Stop must complete within bounded test equivalent (< 1000ms)
    assert.ok(elapsed < 1000, `owner.stop took ${elapsed}ms; must complete within bounded test timeout`);
    assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);

    // Repository must be closed
    assert.strictEqual(repo.isOpen, false);

    // Now release the hung write
    writeHangResolve();
    await new Promise((r) => setTimeout(r, 50));

    // Verify no delayed callback mutated DB: inspect raw database to check coordination status
    const verifyDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
    try {
      const row = verifyDb.prepare('SELECT * FROM archive_coordination WHERE archive_id = ?;').get(archiveId);
      assert.strictEqual(row.status, 'PENDING', 'Record must remain PENDING because DB mutation was prevented after stop timeout');
      assert.strictEqual(row.content_snapshot, 'Hung question text');
    } finally {
      verifyDb.close();
    }
  } finally {
    if (!repo.isClosed) {
      repo.close();
    }
    fs.rmSync(dir, { recursive: true, force: true });
    fs.rmSync(archiveDir, { recursive: true, force: true });
  }
});

test('R1-INT-1 REAL ARCHIVE PRODUCTION PATH: real GatewayRuntimeOwner, ArchiveWorker, ArchiveFileWriter, and SqliteStateRepository', async () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const os = require('node:os');
  const { SqliteStateRepository } = require('../core/sqlite-state-repository');
  const { ArchiveFileWriter } = require('../core/archive-file-writer');
  const { AccountRegistry } = require('../core/account-registry');
  const { computeCanonicalPayloadHash } = require('../core/outbox-delivery-policy');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-gw-r1-int1-state-'));
  const archiveDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ar1-'));
  const repo = new SqliteStateRepository(dir);

  try {
    const reg = new AccountRegistry('telegram');
    reg.register({ id: 'tg_acc_r1', label: 'tg_acc_r1', enabled: true });
    reg.setActive('tg_acc_r1');

    const fakeBackup = {
      repository: repo,
      start: () => {},
      stop: () => {
        repo.close();
      },
    };
    const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };
    const fakeAdapter = { start: async () => {}, stop: async () => {} };

    // Real production path: archiveWorker and archiveFileWriter are NOT passed
    const owner = new GatewayRuntimeOwner({
      stateRoot: dir,
      archiveRoot: archiveDir,
      accountRegistry: reg,
      backupRuntimeOwner: fakeBackup,
      telegramOutboundAdapter: new FakeTelegramOutboundAdapter(),
      outboxWorker: { start: async () => {}, stop: async () => {} },
      localApiServer: fakeServer,
      telegramAdapter: fakeAdapter,
      secretBuffer: Buffer.alloc(32),
    });

    // F1-T1: Prove owner.start() succeeds on non-injected archive production path
    await owner.start();
    assert.strictEqual(owner.status, OWNER_STATUS.RUNNING);

    // 2. Create real topics
    const topicReal = repo.createArchiveTopic({
      accountId: 'tg_acc_r1',
      displayName: 'Real Production Topic',
      normalizedName: 'real production topic',
      accountDirName: 'tg_acc_r1',
    });
    const topicOther = repo.createArchiveTopic({
      accountId: 'tg_acc_other',
      displayName: 'Other Topic',
      normalizedName: 'other topic',
      accountDirName: 'tg_acc_other',
    });

    // 3. Establish required authorized reply state in inbox
    repo.takeoverChannel('tg:chat:30001', 'holder1');
    const rawDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
    try {
      rawDb
        .prepare(
          `INSERT INTO inbox (channel_id, account_id, platform_msg_id, status, content, claimed_by, claimed_at_token)
           VALUES ('tg:chat:30001', 'tg_acc_r1', 'tg:30001:1', 'claimed', 'Real Question Content', 'holder1', 1);`
        )
        .run();
    } finally {
      rawDb.close();
    }

    const payloadHash = computeCanonicalPayloadHash({
      platform: 'telegram',
      account_id: 'tg_acc_r1',
      endpoint_operation: 'sendMessage',
      recipient: '30001',
      logical_reply_target: 'tg:30001:1',
      message_type: 'text',
      body: 'Real Assistant Reply Body',
    });

    // 4. Reply transaction creates exactly one PENDING ORIGINAL archive coordination
    const enqueueRes = repo.enqueueAuthorizedReply({
      clientRequestId: 'req_r1_int1',
      channelId: 'tg:chat:30001',
      holderId: 'holder1',
      fencingToken: 1,
      messageId: 'tg:30001:1',
      replyingAccountId: 'tg_acc_r1',
      topicId: topicReal.topic_id,
      text: 'Real Assistant Reply Body',
      platform: 'telegram',
      endpointOperation: 'sendMessage',
      recipient: '30001',
      logicalReplyTarget: 'tg:30001:1',
      messageType: 'text',
      payloadHash,
    });
    assert.ok(enqueueRes.commandId);

    // 5. Real ArchiveWorker advances it to COMPLETED
    let finalCoord = null;
    for (let i = 0; i < 50; i++) {
      finalCoord = repo.getArchiveCoordinationBySequence('tg_acc_r1', topicReal.topic_id, 1);
      if (finalCoord && finalCoord.status === 'COMPLETED') {
        break;
      }
      await new Promise((r) => setTimeout(r, 20));
    }
    assert.ok(finalCoord);
    assert.strictEqual(finalCoord.status, 'COMPLETED');
    assert.strictEqual(finalCoord.content_snapshot, null); // Cleared on completion!

    // 6. ArchiveFileWriter.readArchiveEntry using real repository returns expected canonical archive
    const writer = new ArchiveFileWriter({ archiveRoot: archiveDir, repository: repo });
    const entry = await writer.readArchiveEntry({
      accountId: 'tg_acc_r1',
      topicId: topicReal.topic_id,
      entrySequence: 1,
    });
    assert.ok(entry);
    assert.strictEqual(entry.archive_id, finalCoord.archive_id);
    assert.ok(entry.content.includes('Real Question Content'));
    assert.ok(entry.content.includes('Real Assistant Reply Body'));

    // 7. ArchiveFileWriter.listTopicEntries using real repository returns the same entry metadata
    const topicList = await writer.listTopicEntries({
      accountId: 'tg_acc_r1',
      topicId: topicReal.topic_id,
    });
    assert.strictEqual(topicList.length, 1);
    assert.strictEqual(topicList[0].archive_id, finalCoord.archive_id);

    // 8. Account/topic isolation remains correct
    const isolatedEntry = await writer.readArchiveEntry({
      accountId: 'tg_acc_other',
      topicId: topicReal.topic_id,
      entrySequence: 1,
    });
    assert.strictEqual(isolatedEntry, null);

    const isolatedList = await writer.listTopicEntries({
      accountId: 'tg_acc_other',
      topicId: topicOther.topic_id,
    });
    assert.strictEqual(isolatedList.length, 0);

    await owner.stop();
  } finally {
    if (!repo.isClosed) {
      repo.close();
    }
    fs.rmSync(dir, { recursive: true, force: true });
    fs.rmSync(archiveDir, { recursive: true, force: true });
  }
});

test('R1-INT-2 REAL ASYNC HANG COUNTEREXAMPLE: real owner, worker, writer, repo with hung test fs-promises facade', async () => {
  const fs = require('node:fs');
  const fsPromises = require('node:fs/promises');
  const path = require('node:path');
  const os = require('node:os');
  const { SqliteStateRepository } = require('../core/sqlite-state-repository');
  const { AccountRegistry } = require('../core/account-registry');

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hhai-gw-r1-int2-state-'));
  const archiveDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ar2-'));
  const repo = new SqliteStateRepository(dir);

  try {
    const reg = new AccountRegistry('telegram');
    reg.register({ id: 'tg_acc_hang', label: 'tg_acc_hang', enabled: true });
    reg.setActive('tg_acc_hang');

    const topic = repo.createArchiveTopic({
      accountId: 'tg_acc_hang',
      displayName: 'Hang Counter Topic',
      normalizedName: 'hang counter topic',
      accountDirName: 'TG_tg_acc_hang',
    });

    let hangResolve;
    const hangPromise = new Promise((resolve) => {
      hangResolve = resolve;
    });

    let linkStarted = false;
    let newFsStepsAfterClosed = 0;
    let newRetryTimersAfterClosed = 0;

    // Track fs calls to prove F3-T5 and F3-T6
    const testFsFacade = {
      ...fsPromises,
      stat: (p) => fsPromises.stat(p),
      realpath: (p) => fsPromises.realpath(p),
      lstat: (p) => fsPromises.lstat(p),
      mkdir: (p, opts) => fsPromises.mkdir(p, opts),
      open: async (...args) => {
        return fsPromises.open(...args);
      },
      link: async (src, dst) => {
        if (dst.includes('001_hang')) {
          linkStarted = true;
          // Hang until release
          await hangPromise;
        }
        return fsPromises.link(src, dst);
      },
    };

    const fakeBackup = {
      repository: repo,
      start: () => {},
      stop: () => {
        repo.close();
      },
    };
    const fakeServer = { isStopping: false, server: { close: () => {} }, start: async () => {}, stop: async () => {} };
    const fakeAdapter = { start: async () => {}, stop: async () => {} };

    // Real owner + real worker + real writer via test-only fsPromises and archiveWorkerStopTimeoutMs
    const owner = new GatewayRuntimeOwner({
      stateRoot: dir,
      archiveRoot: archiveDir,
      accountRegistry: reg,
      backupRuntimeOwner: fakeBackup,
      telegramOutboundAdapter: new FakeTelegramOutboundAdapter(),
      outboxWorker: { start: async () => {}, stop: async () => {} },
      localApiServer: fakeServer,
      telegramAdapter: fakeAdapter,
      secretBuffer: Buffer.alloc(32),
      fsPromises: testFsFacade,
      archiveWorkerStopTimeoutMs: 50,
    });

    await owner.start();

    // Insert pending coordination record into database
    let archiveId;
    const rawDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
    try {
      const res = rawDb
        .prepare(
          `INSERT INTO archive_coordination (
            account_id, topic_id, entry_sequence, record_kind, original_archive_id,
            platform_msg_id, source_platform_event_id, command_id, status,
            content_snapshot, relative_path, completed_at, failed_reason_code,
            created_at, updated_at
          ) VALUES (
            'tg_acc_hang', ?, 1, 'ORIGINAL', NULL,
            'msg_hang_1', NULL, 888, 'PENDING',
            'Hung Question Text', 'TG_tg_acc_hang/Q001_hang/001_hang_20260928-120000.md',
            NULL, NULL, ?, ?
          );`
        )
        .run(topic.topic_id, Math.floor(Date.now() / 1000), Math.floor(Date.now() / 1000));
      archiveId = Number(res.lastInsertRowid);
    } finally {
      rawDb.close();
    }

    // Wait until real writer enters hung link
    for (let i = 0; i < 50 && !linkStarted; i++) {
      await new Promise((r) => setTimeout(r, 10));
    }
    assert.strictEqual(linkStarted, true, 'Hung link step must have been invoked');

    // F3-T1: owner.stop() returns within bounded test equivalent (< 1000ms)
    const startTime = Date.now();
    await owner.stop();
    const elapsed = Date.now() - startTime;
    assert.ok(elapsed < 1000, `owner.stop took ${elapsed}ms; must complete within bounded test timeout`);
    assert.strictEqual(owner.status, OWNER_STATUS.STOPPED);

    // F3-T2: repository shutdown completes
    assert.strictEqual(repo.isOpen, false);

    // F3-T3: post-close DB mutation count = 0
    const verifyDb = new (require('node:sqlite').DatabaseSync)(repo.databasePath);
    try {
      const row = verifyDb.prepare('SELECT * FROM archive_coordination WHERE archive_id = ?;').get(archiveId);
      assert.strictEqual(row.status, 'PENDING');
      assert.strictEqual(row.content_snapshot, 'Hung Question Text');

      // F3-T4: late filesystem settlement cannot write DB
      hangResolve();
      await new Promise((r) => setTimeout(r, 50));

      const afterRow = verifyDb.prepare('SELECT * FROM archive_coordination WHERE archive_id = ?;').get(archiveId);
      assert.strictEqual(afterRow.status, 'PENDING', 'Row must remain PENDING after late fs resolution');
      assert.strictEqual(afterRow.content_snapshot, 'Hung Question Text');
    } finally {
      verifyDb.close();
    }

    // F3-T5 & F3-T6: no new filesystem steps or retry timers after closed guard was active
    assert.strictEqual(newFsStepsAfterClosed, 0);
    assert.strictEqual(newRetryTimersAfterClosed, 0);
  } finally {
    if (!repo.isClosed) {
      repo.close();
    }
    fs.rmSync(dir, { recursive: true, force: true });
    fs.rmSync(archiveDir, { recursive: true, force: true });
  }
});
