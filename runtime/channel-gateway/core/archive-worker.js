/**
 * runtime/channel-gateway/core/archive-worker.js
 *
 * TG-MVP-14: Sequential Archive Worker with Liveness Guard & Bounded Shutdown.
 *
 * Invariants:
 * - Processes only PENDING coordinations; never touches COMPLETED or FAILED.
 * - Sequential execution under a single Gateway-owned worker.
 * - Startup canonical temp cleanup for non-PENDING archive IDs.
 * - stop() stops future scheduling immediately, does NOT drain whole queue,
 *   waits only for currently executing item up to hard upper bound (default 10,000 ms).
 * - Closed guard forbids DB mutation if filesystem operation finishes after shutdown timeout.
 * - Zero raw message content, token, or raw absolute path leakage in logs.
 */

'use strict';

const { ArchiveFileWriter, cleanupNonPendingTempFiles } = require('./archive-file-writer');

const DEFAULT_SHUTDOWN_TIMEOUT_MS = 10000;
const DEFAULT_POLL_INTERVAL_MS = 50;

class ArchiveWorker {
  #repository;
  #archiveRoot;
  #writer;
  #logger;
  #shutdownTimeoutMs;
  #pollIntervalMs;
  #nowSec;

  #isRunning = false;
  #isClosed = false;
  #activePromise = null;
  #timer = null;

  /**
   * @param {object} options
   * @param {object} options.repository SqliteStateRepository instance
   * @param {string} options.archiveRoot Configured archive root directory
   * @param {ArchiveFileWriter} [options.archiveFileWriter] Injected file writer instance
   * @param {object} [options.logger] Logger instance (default console)
   * @param {number} [options.shutdownTimeoutMs=10000] Shutdown upper wait bound in ms
   * @param {number} [options.pollIntervalMs=50] Poll interval in ms
   * @param {() => number} [options.nowSec] Clock provider returning seconds
   */
  constructor(options = {}) {
    if (!options.repository) {
      throw new Error('ArchiveWorker requires a repository (fail-closed)');
    }
    const root = options.archiveRoot || (options.fileWriter && options.fileWriter.archiveRoot);
    if (!root || typeof root !== 'string') {
      throw new Error('ArchiveWorker requires a valid archiveRoot (fail-closed)');
    }

    this.#repository = options.repository;
    this.#archiveRoot = root;
    this.#writer = options.archiveFileWriter || options.fileWriter || new ArchiveFileWriter({ archiveRoot: root });
    this.#logger = options.logger || console;
    this.#shutdownTimeoutMs = options.shutdownTimeoutMs !== undefined
      ? options.shutdownTimeoutMs
      : (options.stopTimeoutMs !== undefined ? options.stopTimeoutMs : DEFAULT_SHUTDOWN_TIMEOUT_MS);
    this.#pollIntervalMs = options.pollIntervalMs !== undefined
      ? options.pollIntervalMs
      : DEFAULT_POLL_INTERVAL_MS;
    this.#nowSec = options.nowSec || (() => Math.floor(Date.now() / 1000));
  }

  get isRunning() {
    return this.#isRunning;
  }

  get isStopped() {
    return !this.#isRunning;
  }

  get isClosed() {
    return this.#isClosed;
  }

  /**
   * Immediately triggers processing of the next pending item, returning active processing promise.
   */
  triggerProcessing() {
    if (!this.#isRunning || this.#isClosed) return Promise.resolve();
    if (this.#timer) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }
    if (!this.#activePromise) {
      this.#activePromise = this.#processNext()
        .catch(() => {})
        .finally(() => {
          this.#activePromise = null;
          if (this.#isRunning && !this.#isClosed) {
            this.#scheduleNext();
          }
        });
    }
    return this.#activePromise || Promise.resolve();
  }

  /**
   * Notifies worker that a new PENDING item is available.
   */
  notifyPending() {
    return this.triggerProcessing();
  }

  /**
   * Starts the archive worker:
   * 1. Sets isRunning = true.
   * 2. Cleans up canonical orphan temp files not belonging to active PENDING rows.
   * 3. Starts sequential polling loop.
   */
  async start() {
    if (this.#isRunning) return;
    this.#isRunning = true;
    this.#isClosed = false;

    // Best-effort startup temp cleanup
    try {
      const pendingIds = this.#repository.getPendingArchiveIds
        ? new Set(this.#repository.getPendingArchiveIds())
        : new Set();
      await cleanupNonPendingTempFiles(this.#archiveRoot, pendingIds, this.#writer ? this.#writer.fsPromises : undefined);
    } catch (_) {
      // Contained as best-effort startup cleanup; never fails startup or leaves unhandled rejection
    }

    this.#scheduleNext(0);
  }

  /**
   * Stops the archive worker:
   * 1. Stops future scheduling immediately.
   * 2. Does NOT drain the PENDING queue.
   * 3. Waits only for currently executing item up to shutdownTimeoutMs.
   * 4. If wait bound expires: returns from stop, leaves coordination PENDING,
   *    and sets closed guard so delayed disk callbacks cannot mutate DB.
   */
  async stop() {
    if (!this.#isRunning) return;
    this.#isRunning = false;

    if (this.#timer) {
      clearTimeout(this.#timer);
      this.#timer = null;
    }

    if (this.#activePromise) {
      let timeoutId;
      const timeoutPromise = new Promise((resolve) => {
        timeoutId = setTimeout(() => {
          this.#isClosed = true; // Closed guard set upon timeout
          resolve('TIMEOUT');
        }, this.#shutdownTimeoutMs);
      });

      const res = await Promise.race([this.#activePromise, timeoutPromise]);
      clearTimeout(timeoutId);

      if (res === 'TIMEOUT') {
        // Stop timeout expired: return from stop, leave coordination PENDING
        return;
      }
    }

    this.#isClosed = true;
  }

  #scheduleNext(delayMs = this.#pollIntervalMs) {
    if (!this.#isRunning || this.#isClosed) return;
    this.#timer = setTimeout(() => {
      this.#timer = null;
      this.#activePromise = this.#processNext()
        .catch(() => {})
        .finally(() => {
          this.#activePromise = null;
          if (this.#isRunning && !this.#isClosed) {
            this.#scheduleNext();
          }
        });
    }, delayMs);
    if (this.#timer && typeof this.#timer.unref === 'function') {
      this.#timer.unref();
    }
  }

  /**
   * Processes a single PENDING coordination record sequentially.
   */
  async #processNext() {
    if (!this.#isRunning || this.#isClosed) return;

    let item;
    try {
      item = this.#repository.claimNextPendingArchiveCoordination();
    } catch {
      return;
    }

    if (!item) {
      return;
    }

    let topic = null;
    try {
      topic = this.#repository.getArchiveTopicById(item.topic_id);
    } catch (_) {}

    let outboxBody = item.outbox_body;
    if (!outboxBody && item.command_id && typeof this.#repository.getOutboxCommand === 'function') {
      try {
        const cmd = this.#repository.getOutboxCommand(item.command_id);
        if (cmd) {
          outboxBody = cmd.body;
        }
      } catch (_) {}
    }

    // Execute publication using hard-link primitive
    const result = await this.#writer.publishArchiveRecord({
      archiveRoot: this.#archiveRoot,
      coordination: item,
      topic,
      outboxBody,
      questionSnapshot: item.content_snapshot,
      amendmentSnapshot: item.content_snapshot,
      isClosed: () => this.#isClosed,
    });

    // CLOSED GUARD: If worker was closed during processing (e.g. stop timed out),
    // strictly forbid database mutation! Delayed disk completion must leave row PENDING.
    if (this.#isClosed) {
      return;
    }

    const nowSec = this.#nowSec();
    try {
      if (result.status === 'COMPLETED') {
        this.#repository.markArchiveCoordinationCompleted({
          archiveId: item.archive_id,
          completedAtSec: nowSec,
          nowSec,
        });
      } else if (result.status === 'FAILED') {
        this.#repository.markArchiveCoordinationFailed({
          archiveId: item.archive_id,
          failedReasonCode: result.reasonCode || 'ARCHIVE_PUBLISH_FAILED',
          nowSec,
        });
      }
    } catch (_) {
      // If DB mutation fails (e.g. DB closed), row remains in prior state
    }
  }
}

module.exports = {
  ArchiveWorker,
  DEFAULT_SHUTDOWN_TIMEOUT_MS,
  DEFAULT_POLL_INTERVAL_MS,
};
