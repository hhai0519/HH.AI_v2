/**
 * runtime/channel-gateway/core/gateway-runtime-owner.js
 *
 * TG-MVP-11: Gateway In-Process Runtime Owner.
 * Coordinates ordered startup, graceful shutdown, reverse rollback,
 * loopback Local API server, TelegramInboundAdapter, BackupRuntimeOwner,
 * and signal handling inside a single process boundary.
 */

'use strict';

const { LocalApiServer } = require('./local-api-server');
const { LocalApiDispatcher } = require('./local-api-dispatcher');
const { BackupRuntimeOwner } = require('./backup-runtime-owner');
const { OutboxWorker } = require('./outbox-worker');
const { TelegramInboundAdapter } = require('../adapters/telegram-inbound-adapter');
const { SecretRef } = require('./secret-provider');
const { CANONICAL_PORT } = require('./local-api-codec');

const OWNER_STATUS = Object.freeze({
  INITIALIZED: 'INITIALIZED',
  STARTING: 'STARTING',
  RUNNING: 'RUNNING',
  STOPPING: 'STOPPING',
  STOPPED: 'STOPPED',
});

class GatewayRuntimeOwner {
  #status;
  #stateRoot;
  #config;
  #accountRegistry;
  #secretProvider;
  #port;
  #allowTestPort;
  #logger;
  #processEmitter;
  #platform;
  #nowSec;

  #injectedBackupOwner;
  #backupRuntimeOwnerFactory;
  #injectedTelegramAdapter;
  #telegramAdapterFactory;
  #injectedServer;
  #localApiServerFactory;
  #injectedDispatcher;
  #dispatcherFactory;
  #injectedSecretBuf;
  #injectedOutboxWorker;
  #outboxWorkerFactory;
  #outboxDeliveryExecutor;

  #backupRuntimeOwner;
  #outboxWorker;
  #telegramAdapter;
  #server;
  #secretBuf;
  #registeredSignals;
  #signalHandler;
  #signalTriggered;
  #stopPromise;

  /**
   * @param {object} [options={}]
   * @param {string} [options.stateRoot]
   * @param {object} [options.config]
   * @param {object} [options.accountRegistry]
   * @param {object} [options.secretProvider]
   * @param {number} [options.port=3003]
   * @param {boolean} [options.allowTestPort=false]
   * @param {object} [options.logger=console]
   * @param {object} [options.processEmitter=process]
   * @param {string} [options.platform=process.platform]
   * @param {() => number} [options.nowSec]
   * @param {object} [options.backupRuntimeOwner]
   * @param {function} [options.backupRuntimeOwnerFactory]
   * @param {object} [options.telegramAdapter]
   * @param {function} [options.telegramAdapterFactory]
   * @param {object} [options.localApiServer]
   * @param {function} [options.localApiServerFactory]
   * @param {object} [options.dispatcher]
   * @param {function} [options.dispatcherFactory]
   * @param {Buffer} [options.secretBuffer]
   * @param {object} [options.outboxWorker]
   * @param {function} [options.outboxWorkerFactory]
   * @param {function} [options.outboxDeliveryExecutor]
   */
  constructor(options = {}) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      throw new TypeError('GatewayRuntimeOwner options must be an object');
    }

    this.#status = OWNER_STATUS.INITIALIZED;
    this.#config = options.config || null;
    this.#stateRoot = options.stateRoot || (this.#config && this.#config.dataLocations && this.#config.dataLocations.stateRoot) || null;
    this.#accountRegistry = options.accountRegistry || null;
    this.#secretProvider = options.secretProvider || null;
    this.#port = options.port !== undefined ? options.port : CANONICAL_PORT;
    this.#allowTestPort = Boolean(options.allowTestPort);
    this.#logger = options.logger || console;
    this.#processEmitter = options.processEmitter || process;
    this.#platform = options.platform || process.platform;
    this.#nowSec = options.nowSec || null;

    this.#injectedBackupOwner = options.backupRuntimeOwner || null;
    this.#backupRuntimeOwnerFactory = options.backupRuntimeOwnerFactory || null;
    this.#injectedTelegramAdapter = options.telegramAdapter || null;
    this.#telegramAdapterFactory = options.telegramAdapterFactory || null;
    this.#injectedServer = options.localApiServer || null;
    this.#localApiServerFactory = options.localApiServerFactory || null;
    this.#injectedDispatcher = options.dispatcher || null;
    this.#dispatcherFactory = options.dispatcherFactory || null;
    this.#injectedSecretBuf = options.secretBuffer || null;
    this.#injectedOutboxWorker = options.outboxWorker || null;
    this.#outboxWorkerFactory = options.outboxWorkerFactory || null;
    this.#outboxDeliveryExecutor = options.outboxDeliveryExecutor || null;

    this.#backupRuntimeOwner = null;
    this.#outboxWorker = null;
    this.#telegramAdapter = null;
    this.#server = null;
    this.#secretBuf = null;
    this.#registeredSignals = [];
    this.#signalHandler = null;
    this.#signalTriggered = false;
    this.#stopPromise = null;
  }

  get status() {
    return this.#status;
  }

  get isRunning() {
    return this.#status === OWNER_STATUS.RUNNING;
  }

  get isStopping() {
    return this.#status === OWNER_STATUS.STOPPING;
  }

  get repository() {
    return this.#backupRuntimeOwner ? this.#backupRuntimeOwner.repository : null;
  }

  get server() {
    return this.#server;
  }

  get telegramAdapter() {
    return this.#telegramAdapter;
  }

  get backupRuntimeOwner() {
    return this.#backupRuntimeOwner;
  }

  get outboxWorker() {
    return this.#outboxWorker;
  }

  #installSignalHandlers() {
    if (!this.#processEmitter || typeof this.#processEmitter.on !== 'function') {
      return;
    }

    const signals = ['SIGINT', 'SIGTERM'];
    if (this.#platform === 'win32') {
      signals.push('SIGBREAK', 'SIGHUP');
    }

    this.#signalHandler = (sig) => {
      if (this.#signalTriggered) {
        return;
      }
      this.#signalTriggered = true;
      const signalName = typeof sig === 'string' ? sig : 'SIGNAL';
      if (this.#logger && typeof this.#logger.info === 'function') {
        this.#logger.info(`[GatewayRuntimeOwner] Received signal ${signalName}, stopping gateway...`);
      }
      this.stop().catch((_err) => {
        if (this.#logger && typeof this.#logger.error === 'function') {
          this.#logger.error('[GatewayRuntimeOwner] Error during signal-triggered stop');
        }
      });
    };

    for (const sig of signals) {
      this.#processEmitter.on(sig, this.#signalHandler);
      this.#registeredSignals.push(sig);
    }
  }

  #removeSignalHandlers() {
    if (!this.#processEmitter) {
      return;
    }
    const removeFn = this.#processEmitter.removeListener || this.#processEmitter.off;
    if (typeof removeFn !== 'function') {
      return;
    }

    for (const sig of this.#registeredSignals) {
      try {
        removeFn.call(this.#processEmitter, sig, this.#signalHandler);
      } catch (_) {}
    }
    this.#registeredSignals = [];
    this.#signalHandler = null;
  }

  async #rollbackOnStartupFailure() {
    this.#status = OWNER_STATUS.STOPPING;

    // 1. Rollback Telegram adapter if started
    if (this.#telegramAdapter) {
      try {
        await this.#telegramAdapter.stop();
      } catch (_) {}
      this.#telegramAdapter = null;
    }

    // 2. Rollback Local API server if started
    if (this.#server) {
      try {
        await this.#server.stop();
      } catch (_) {}
      this.#server = null;
    }

    // 3. Best-effort zeroize secret buffer
    if (this.#secretBuf) {
      try {
        this.#secretBuf.fill(0);
      } catch (_) {}
      this.#secretBuf = null;
    }

    // 4. Rollback OutboxWorker if started
    if (this.#outboxWorker) {
      try {
        await this.#outboxWorker.stop();
      } catch (_) {}
      this.#outboxWorker = null;
    }

    // 5. Rollback BackupRuntimeOwner
    if (this.#backupRuntimeOwner) {
      try {
        this.#backupRuntimeOwner.stop();
      } catch (_) {}
      this.#backupRuntimeOwner = null;
    }

    // 6. Remove signal handlers
    this.#removeSignalHandlers();

    this.#status = OWNER_STATUS.STOPPED;
  }

  /**
   * Starts the Gateway runtime owner:
   * 1. Opens repository and starts BackupRuntimeOwner.
   * 2. Starts OutboxWorker (runs in-flight startup recovery).
   * 3. Binds Local API loopback HTTP server.
   * 4. Starts TelegramInboundAdapter LAST.
   * On any failure, performs strict reverse-order rollback.
   *
   * @returns {Promise<GatewayRuntimeOwner>}
   */
  async start() {
    if (this.#status === OWNER_STATUS.STARTING || this.#status === OWNER_STATUS.RUNNING) {
      throw new Error('GatewayRuntimeOwner is already started or starting (fail-closed)');
    }

    this.#status = OWNER_STATUS.STARTING;
    this.#installSignalHandlers();

    // Step 1: BackupRuntimeOwner & Repository
    try {
      if (this.#injectedBackupOwner) {
        this.#backupRuntimeOwner = this.#injectedBackupOwner;
      } else if (this.#backupRuntimeOwnerFactory) {
        this.#backupRuntimeOwner = this.#backupRuntimeOwnerFactory(this.#stateRoot);
      } else {
        if (!this.#stateRoot) {
          throw new Error('stateRoot is required to initialize BackupRuntimeOwner');
        }
        this.#backupRuntimeOwner = new BackupRuntimeOwner({
          stateRoot: this.#stateRoot,
          logger: this.#logger,
        });
      }

      if (typeof this.#backupRuntimeOwner.start === 'function') {
        this.#backupRuntimeOwner.start();
      }
    } catch (err) {
      this.#removeSignalHandlers();
      this.#status = OWNER_STATUS.STOPPED;
      throw err;
    }

    // Step 2: OutboxWorker (startup recovery & lifecycle ownership)
    try {
      const repo = this.#backupRuntimeOwner.repository;
      let worker = this.#injectedOutboxWorker;
      if (!worker) {
        const workerOpts = {
          repository: repo,
          deliveryExecutor: this.#outboxDeliveryExecutor || null,
          logger: this.#logger,
          nowSec: this.#nowSec,
        };
        if (this.#outboxWorkerFactory) {
          worker = this.#outboxWorkerFactory(workerOpts);
        } else {
          worker = new OutboxWorker(workerOpts);
        }
      }
      this.#outboxWorker = worker;
      await this.#outboxWorker.start();
    } catch (err) {
      await this.#rollbackOnStartupFailure();
      throw err;
    }

    // Step 3: Local API Server & Dispatcher
    try {
      const repo = this.#backupRuntimeOwner.repository;
      let dispatcher = this.#injectedDispatcher;
      if (!dispatcher) {
        const dispatcherDeps = {
          repository: repo,
          accountRegistry: this.#accountRegistry,
          nowSec: this.#nowSec,
        };
        if (this.#dispatcherFactory) {
          dispatcher = this.#dispatcherFactory(dispatcherDeps);
        } else {
          dispatcher = new LocalApiDispatcher(dispatcherDeps);
        }
      }

      if (this.#injectedSecretBuf) {
        this.#secretBuf = this.#injectedSecretBuf;
      } else if (this.#secretProvider) {
        const secretRef = SecretRef.localApiHmac();
        this.#secretBuf = this.#secretProvider.getSecret(secretRef);
      }

      if (this.#secretBuf && !Buffer.isBuffer(this.#secretBuf)) {
        throw new TypeError('Local API HMAC secret must be a Buffer (fail-closed)');
      }

      let server = this.#injectedServer;
      if (!server) {
        if (!this.#secretBuf) {
          throw new Error('secretProvider or dedicated secretBuffer is required for Local API server');
        }

        const serverOpts = {
          secret: this.#secretBuf,
          dispatcher,
          port: this.#port,
          allowTestPort: this.#allowTestPort,
          nowSec: this.#nowSec,
        };

        if (this.#localApiServerFactory) {
          server = this.#localApiServerFactory(serverOpts);
        } else {
          server = new LocalApiServer(serverOpts);
        }
      }

      this.#server = server;
      await this.#server.start();
    } catch (err) {
      await this.#rollbackOnStartupFailure();
      throw err;
    }

    // Step 4: TelegramInboundAdapter (LAST)
    try {
      let adapter = this.#injectedTelegramAdapter;
      if (!adapter) {
        if (this.#telegramAdapterFactory) {
          adapter = this.#telegramAdapterFactory({
            accountRegistry: this.#accountRegistry,
            secretProvider: this.#secretProvider,
            stateRepository: this.#backupRuntimeOwner.repository,
            logger: this.#logger,
          });
        } else {
          adapter = new TelegramInboundAdapter({
            accountRegistry: this.#accountRegistry,
            secretProvider: this.#secretProvider,
            stateRepository: this.#backupRuntimeOwner.repository,
            logger: this.#logger,
          });
        }
      }

      this.#telegramAdapter = adapter;
      await this.#telegramAdapter.start();
    } catch (err) {
      await this.#rollbackOnStartupFailure();
      throw err;
    }

    this.#status = OWNER_STATUS.RUNNING;
    return this;
  }

  /**
   * Graceful stop sequence:
   * 1. Set status to STOPPING and close Local API listener to reject new accepts.
   * 2. Await TelegramInboundAdapter.stop() to full quiescence.
   * 3. Drain Local API connections (<= 2000ms) and stop LocalApiServer.
   * 4. Await OutboxWorker.stop() before repository close.
   * 5. Stop BackupRuntimeOwner (stops scheduler, closes repository).
   * 6. Best-effort zeroize server HMAC secret buffer.
   * 7. Remove installed signal handlers.
   *
   * @returns {Promise<void>}
   */
  async stop() {
    if (this.#status === OWNER_STATUS.STOPPING || this.#status === OWNER_STATUS.STOPPED) {
      if (this.#stopPromise) {
        return this.#stopPromise;
      }
      return;
    }

    this.#status = OWNER_STATUS.STOPPING;

    this.#stopPromise = (async () => {
      // 1. Signal stopping on Local API server immediately to reject new connections
      if (this.#server) {
        this.#server.isStopping = true;
        if (this.#server.server && typeof this.#server.server.close === 'function') {
          try {
            this.#server.server.close();
          } catch (_) {}
        }
      }

      // 2. Await TelegramInboundAdapter.stop() to full quiescence (Mutation T17 requirement)
      if (this.#telegramAdapter) {
        try {
          await this.#telegramAdapter.stop();
        } catch (err) {
          if (this.#logger && typeof this.#logger.error === 'function') {
            this.#logger.error('[GatewayRuntimeOwner] Error stopping Telegram adapter');
          }
        }
        this.#telegramAdapter = null;
      }

      // 3. Bounded drain and stop Local API server
      if (this.#server) {
        try {
          await this.#server.stop();
        } catch (err) {
          if (this.#logger && typeof this.#logger.error === 'function') {
            this.#logger.error('[GatewayRuntimeOwner] Error stopping Local API server');
          }
        }
        this.#server = null;
      }

      // 4. Await OutboxWorker.stop() before repository close
      if (this.#outboxWorker) {
        try {
          await this.#outboxWorker.stop();
        } catch (err) {
          if (this.#logger && typeof this.#logger.error === 'function') {
            this.#logger.error('[GatewayRuntimeOwner] Error stopping OutboxWorker');
          }
        }
        this.#outboxWorker = null;
      }

      // 5. Stop BackupRuntimeOwner (stops scheduler then closes repo)
      if (this.#backupRuntimeOwner) {
        try {
          this.#backupRuntimeOwner.stop();
        } catch (err) {
          if (this.#logger && typeof this.#logger.error === 'function') {
            this.#logger.error('[GatewayRuntimeOwner] Error stopping BackupRuntimeOwner');
          }
        }
        this.#backupRuntimeOwner = null;
      }

      // 6. Best-effort zeroize HMAC secret Buffer
      if (this.#secretBuf) {
        try {
          this.#secretBuf.fill(0);
        } catch (_) {}
        this.#secretBuf = null;
      }

      // 7. Remove installed signal handlers
      this.#removeSignalHandlers();

      this.#status = OWNER_STATUS.STOPPED;
    })();

    return this.#stopPromise;
  }
}

module.exports = {
  GatewayRuntimeOwner,
  OWNER_STATUS,
};
