'use strict';

/**
 * runtime/channel-gateway/core/backup-runtime-owner.js
 *
 * Provisional In-Process Backup Integration Runtime Owner (TG-MVP-09 / T11-main).
 *
 * Explicit Architectural Scope & Boundaries (ADR-0023 / TG-MVP-09):
 * 1. PROVISIONAL IN-PROCESS ONLY: This component provides a minimal lifecycle pairing
 *    (open repository -> start backup scheduler; stop scheduler -> close repository).
 * 2. NOT FINAL GATEWAY PROCESS ARCHITECTURE: Does NOT define the overall Gateway daemon,
 *    PM2 process, long-polling coordinator, or network listener architecture (retained for TG-MVP-10/11).
 * 3. NOT A DAEMON OR OS SERVICE: Does NOT daemonize, fork child processes, or register OS services.
 * 4. NO PROCESS SIGNAL HANDLERS: Does NOT install `process.on(...)`, `SIGINT`, or `SIGTERM` handlers.
 * 5. NO CONFIG / ENV READING: Does NOT read `process.env`, `process.argv`, or load Local Config.
 * 6. SINGLE IN-PROCESS CAPABILITY: Ensures backup scheduling runs strictly inside the single
 *    Channel Gateway process boundary; never creates a second background daemon.
 */

const path = require('node:path');
const { SqliteStateRepository } = require('./sqlite-state-repository');
const { BackupScheduler } = require('./backup-scheduler');

class BackupRuntimeOwner {
  #stateRoot;
  #repositoryFactory;
  #schedulerFactory;
  #logger;
  #schedulerOptions;
  #repository = null;
  #scheduler = null;
  #isStarted = false;

  /**
   * @param {object} options
   * @param {string} options.stateRoot Absolute path to canonical state root directory
   * @param {function(string): object} [options.repositoryFactory] Repository opener
   * @param {function(object, string, object): object} [options.schedulerFactory] Scheduler constructor
   * @param {object} [options.logger=console] Logger instance
   * @param {object} [options.schedulerOptions={}] Options forwarded to BackupScheduler
   */
  constructor(options = {}) {
    if (!options || typeof options !== 'object') {
      throw new TypeError('BackupRuntimeOwner options must be an object (fail-closed)');
    }

    const {
      stateRoot,
      repositoryFactory = (root) => SqliteStateRepository.open(root),
      schedulerFactory = (repo, root, opts) =>
        new BackupScheduler({ repository: repo, stateRoot: root, ...opts }),
      logger = console,
      schedulerOptions = {},
    } = options;

    if (typeof stateRoot !== 'string' || stateRoot.trim().length === 0) {
      throw new TypeError('BackupRuntimeOwner stateRoot must be a non-empty string (fail-closed)');
    }
    if (!path.isAbsolute(stateRoot)) {
      throw new Error(
        `BackupRuntimeOwner stateRoot must be an absolute path: '${stateRoot}' (fail-closed)`
      );
    }

    if (typeof repositoryFactory !== 'function') {
      throw new TypeError(
        'BackupRuntimeOwner repositoryFactory must be a function (fail-closed)'
      );
    }
    if (typeof schedulerFactory !== 'function') {
      throw new TypeError('BackupRuntimeOwner schedulerFactory must be a function (fail-closed)');
    }
    if (!logger || typeof logger !== 'object') {
      throw new TypeError('BackupRuntimeOwner logger must be an object (fail-closed)');
    }

    this.#stateRoot = stateRoot;
    this.#repositoryFactory = repositoryFactory;
    this.#schedulerFactory = schedulerFactory;
    this.#logger = logger;
    this.#schedulerOptions = schedulerOptions;
  }

  get isStarted() {
    return this.#isStarted;
  }

  get repository() {
    return this.#repository;
  }

  get scheduler() {
    return this.#scheduler;
  }

  /**
   * Starts the provisional backup runtime owner:
   * 1. Opens the repository using stateRoot.
   * 2. Instantiates and starts the BackupScheduler.
   * 3. If scheduler initialization or startup fails, closes the repository before re-throwing.
   */
  start() {
    if (this.#isStarted) {
      throw new Error(
        'BackupRuntimeOwner is already started (fail-closed: duplicate start rejected)'
      );
    }

    let repo = null;
    try {
      repo = this.#repositoryFactory(this.#stateRoot);
    } catch (err) {
      // Repository open failure: scheduler is never constructed
      throw err;
    }

    let sched = null;
    try {
      sched = this.#schedulerFactory(repo, this.#stateRoot, {
        logger: this.#logger,
        ...this.#schedulerOptions,
      });
      sched.start();
    } catch (err) {
      // Scheduler construction or startup failure: close opened repository before rethrowing
      try {
        if (repo && typeof repo.close === 'function') {
          repo.close();
        }
      } catch (_) {}
      throw err;
    }

    this.#repository = repo;
    this.#scheduler = sched;
    this.#isStarted = true;
  }

  /**
   * Stops the provisional backup runtime owner:
   * 1. Stops the BackupScheduler.
   * 2. Closes the repository.
   * Safe and idempotent on multiple or pre-start invocations.
   */
  stop() {
    if (!this.#isStarted) {
      return; // Safe idempotent no-op before start or after stop
    }

    this.#isStarted = false;

    // Strict order: scheduler stop -> repository close
    if (this.#scheduler) {
      try {
        this.#scheduler.stop();
      } catch (err) {
        if (this.#logger && typeof this.#logger.error === 'function') {
          this.#logger.error('[BackupRuntimeOwner] Error stopping scheduler:', err);
        }
      }
      this.#scheduler = null;
    }

    if (this.#repository) {
      try {
        this.#repository.close();
      } catch (err) {
        if (this.#logger && typeof this.#logger.error === 'function') {
          this.#logger.error('[BackupRuntimeOwner] Error closing repository:', err);
        }
      }
      this.#repository = null;
    }
  }
}

module.exports = {
  BackupRuntimeOwner,
};
