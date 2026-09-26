/**
 * runtime/channel-gateway/core/outbox-worker.js
 *
 * TG-MVP-12: Transport-Neutral In-Process Durable Outbox Worker & Lifecycle Engine.
 *
 * Invariants:
 * - In-process single-component boundary (NO daemon, NO second process, NO PM2).
 * - Injectable delivery executor for deterministic fake transport testing.
 * - Startup crash recovery: evaluates all IN_FLIGHT commands on start.
 * - Atomically claims due QUEUED -> IN_FLIGHT before delivery attempt.
 * - Single-command bounded scheduler: no overlapping execution of same command.
 * - Applies pure capability-aware delivery policy without side effects.
 * - Safe retry scheduling via next_attempt_at timestamp.
 * - Graceful shutdown with zero timer leak.
 * - Boundary invariant: with NO delivery executor injected, never consumes or alters QUEUED commands.
 */

'use strict';

const {
  TRANSPORT_PHASE,
  OUTBOX_STATUS,
  POLICY_DECISION,
  evaluateDeliveryAttempt,
} = require('./outbox-delivery-policy');

class OutboxWorker {
  #repository;
  #deliveryExecutor;
  #pollIntervalMs;
  #nowSec;
  #logger;
  #isRunning;
  #timer;
  #isProcessing;

  /**
   * @param {object} options
   * @param {object} options.repository SqliteStateRepository instance
   * @param {function} [options.deliveryExecutor] Async delivery function (command) => Promise<{ phase, success, http_status, retry_after, error_code }>
   * @param {number} [options.pollIntervalMs=1000]
   * @param {() => number} [options.nowSec]
   * @param {object} [options.logger=console]
   */
  constructor(options = {}) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      throw new TypeError('OutboxWorker options must be an object');
    }
    if (!options.repository) {
      throw new Error('OutboxWorker requires a repository dependency (fail-closed)');
    }
    this.#repository = options.repository;
    this.#deliveryExecutor =
      typeof options.deliveryExecutor === 'function' ? options.deliveryExecutor : null;
    this.#pollIntervalMs =
      Number.isSafeInteger(options.pollIntervalMs) && options.pollIntervalMs > 0
        ? options.pollIntervalMs
        : 1000;
    this.#nowSec =
      typeof options.nowSec === 'function'
        ? options.nowSec
        : () => Math.floor(Date.now() / 1000);
    this.#logger = options.logger || console;
    this.#isRunning = false;
    this.#timer = null;
    this.#isProcessing = false;
  }

  get isRunning() {
    return this.#isRunning;
  }

  get isProcessing() {
    return this.#isProcessing;
  }

  get hasActiveTimer() {
    return this.#timer !== null;
  }

  /**
   * Starts the Outbox worker:
   * 1. Runs startup crash recovery on any leftover IN_FLIGHT commands.
   * 2. Starts periodic polling timer.
   */
  async start() {
    if (this.#isRunning) {
      return;
    }
    this.#isRunning = true;

    // 1. Startup crash recovery
    const nowSec = this.#nowSec();
    this.#repository.recoverInFlightCommands(nowSec);

    // 2. Schedule polling only if deliveryExecutor is present (F3)
    if (this.#deliveryExecutor) {
      this.#scheduleNextTick(0);
    }
  }

  #scheduleNextTick(delayMs) {
    if (!this.#isRunning) {
      return;
    }
    if (this.#timer) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
    this.#timer = setTimeout(async () => {
      this.#timer = null;
      if (!this.#isRunning) {
        return;
      }
      try {
        await this.processNext();
      } catch (err) {
        if (this.#logger && typeof this.#logger.error === 'function') {
          this.#logger.error('OutboxWorker process error', err);
        }
      } finally {
        if (this.#isRunning) {
          this.#scheduleNextTick(this.#pollIntervalMs);
        }
      }
    }, delayMs);

    if (this.#timer && typeof this.#timer.unref === 'function') {
      this.#timer.unref();
    }
  }

  /**
   * Stops the worker cleanly without timer leak.
   */
  async stop() {
    this.#isRunning = false;
    if (this.#timer) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }

    // Await any in-progress delivery attempt
    while (this.#isProcessing) {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
  }

  /**
   * Atomically claims and processes the next due QUEUED command.
   * Returns summary of action taken or null if no command was processed.
   *
   * @returns {Promise<object|null>}
   */
  async processNext() {
    if (this.#isProcessing) {
      return null;
    }

    // Boundary invariant: Without an injected delivery executor,
    // do NOT claim, consume, or drop any QUEUED command.
    if (!this.#deliveryExecutor) {
      return null;
    }

    this.#isProcessing = true;
    try {
      const nowSec = this.#nowSec();
      // Atomically transitions due command: QUEUED -> IN_FLIGHT, attempt_count++
      const command = this.#repository.claimNextQueuedOutboxCommand(nowSec);
      if (!command) {
        return null;
      }

      // Execute delivery attempt via injected executor
      let attemptContext;
      try {
        const execRes = await this.#deliveryExecutor(command);
        const rawPhase = execRes && (execRes.phase || execRes.transport_phase);
        // F2: Only explicit NOT_SENT can be treated as NOT_SENT.
        // Missing, null, empty string, or unknown value must default conservatively to MAY_HAVE_BEEN_SENT.
        const transportPhase =
          rawPhase === TRANSPORT_PHASE.NOT_SENT
            ? TRANSPORT_PHASE.NOT_SENT
            : TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT;

        attemptContext = {
          transport_phase: transportPhase,
          raw_phase: rawPhase,
          success: Boolean(execRes && execRes.success),
          http_status: execRes ? execRes.http_status : undefined,
          retry_after: execRes ? execRes.retry_after : undefined,
          error_code: execRes ? execRes.error_code : undefined,
          nowSec: this.#nowSec(),
        };
      } catch (err) {
        const rawPhase = err && (err.phase || err.transport_phase);
        const transportPhase =
          rawPhase === TRANSPORT_PHASE.NOT_SENT
            ? TRANSPORT_PHASE.NOT_SENT
            : TRANSPORT_PHASE.MAY_HAVE_BEEN_SENT;

        attemptContext = {
          transport_phase: transportPhase,
          raw_phase: rawPhase,
          success: false,
          http_status: err ? err.http_status : undefined,
          retry_after: err ? err.retry_after : undefined,
          error_code: (err && (err.code || err.message)) || 'UNKNOWN_ERROR',
          nowSec: this.#nowSec(),
        };
      }

      // Apply pure capability-aware delivery policy
      const policyResult = evaluateDeliveryAttempt(command, attemptContext);
      const currentNow = this.#nowSec();

      switch (policyResult.decision) {
        case POLICY_DECISION.ACCEPTED_BY_PLATFORM:
          this.#repository.updateOutboxCommandResult(command.command_id, {
            status: OUTBOX_STATUS.ACCEPTED_BY_PLATFORM,
            nowSec: currentNow,
          });
          break;

        case POLICY_DECISION.RETRY: {
          const delaySec = policyResult.next_attempt_delay_sec || 5;
          const nextAttemptAt = currentNow + delaySec;
          this.#repository.updateOutboxCommandResult(command.command_id, {
            status: OUTBOX_STATUS.QUEUED,
            nextAttemptAt,
            nowSec: currentNow,
          });
          break;
        }

        case POLICY_DECISION.UNCERTAIN:
          this.#repository.updateOutboxCommandResult(command.command_id, {
            status: OUTBOX_STATUS.UNCERTAIN,
            nowSec: currentNow,
          });
          break;

        case POLICY_DECISION.FAILED_TERMINAL:
        default:
          this.#repository.updateOutboxCommandResult(command.command_id, {
            status: OUTBOX_STATUS.FAILED_TERMINAL,
            terminalReasonCode: policyResult.terminal_reason_code || policyResult.reason,
            nowSec: currentNow,
          });
          break;
      }

      return {
        command_id: command.command_id,
        decision: policyResult.decision,
        attempt_count: command.attempt_count,
      };
    } finally {
      this.#isProcessing = false;
    }
  }
}

module.exports = {
  OutboxWorker,
};
