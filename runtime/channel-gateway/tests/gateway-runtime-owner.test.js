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
const { runGateway } = require('../bin/gateway');

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
