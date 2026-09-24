/**
 * runtime/channel-gateway/adapters/telegram-inbound-adapter.js
 *
 * ADR-0022 / ADR-0024 / ADR-0026 / TG-MVP-10: Telegram Test-Bot Inbound Adapter.
 *
 * Invariants (M1–M15):
 * - Composable inbound long-poll adapter component (NOT an OS process root).
 * - start() and async stop() lifecycle management.
 * - Does NOT close the state repository on stop (repository lifecycle owned externally).
 * - Depends on AccountRegistry for non-secret metadata; start() requires active, enabled account for channel 'telegram'.
 * - Looks up bot token secret via SecretProvider strictly ONCE on start().
 * - Authoritative token retained in Buffer; validated against bounded ASCII grammar (no /, ?, whitespace, control chars).
 * - Protocol-boundary exception: creates unavoidable ephemeral UTF-8 URL strictly inside request-construction boundary.
 * - Ephemeral URL is never stored, cached, returned, logged, or reflected in diagnostics.
 * - Authoritative Buffer zeroized via buf.fill(0) on stop or termination.
 * - Node built-ins only (fetch, AbortController, URL, timers); zero new npm dependencies.
 * - Inbound update classification:
 *     message.text -> MESSAGE (ingestMessage)
 *     edited_message.text -> EDIT (ingestEdit)
 *     other valid update_id updates -> IGNORED (recordIgnoredEvent)
 *     protocol-invalid update_id -> no cursor mutation, no fabricated event
 * - Identity:
 *     platform_event_id: String(update.update_id)
 *     cursor_value: String(update.update_id + 1)
 *     platform_msg_id: tg:<chat_id>:<message_id>
 * - Week-rebase (M8):
 *     TELEGRAM_WEEK_REBASE_MS = 604800000 (7 days).
 *     If nowMs - updatedAtMs >= 604800000, calls resetIngestCursorForTransportRebase and omits offset.
 * - Error & retry contract:
 *     HTTP 409 -> TELEGRAM_RECEIVER_CONFLICT terminal (no retry)
 *     HTTP 429 -> waits retry_after seconds
 *     5xx / network / client-timeout / malformed JSON -> generic backoff (1s, 2s, 4s, 8s, 16s, 30s cap)
 *     Valid successful response resets backoff.
 */

'use strict';

const { SecretRef } = require('../core/secret-provider');

const TELEGRAM_CHANNEL_ID = 'telegram';
const TELEGRAM_WEEK_REBASE_MS = 604_800_000; // 7 days in milliseconds
const TELEGRAM_CLIENT_TIMEOUT_MS = 40_000;
const TELEGRAM_POLL_TIMEOUT_SECONDS = 30;
const GENERIC_BACKOFF_MS = Object.freeze([1000, 2000, 4000, 8000, 16000, 30000]);

/**
 * Validates bounded ASCII token grammar to reject path/query/control injection.
 * Rejects: /, ?, whitespace, C0 controls (< 0x21), DEL (0x7F), and non-ASCII (> 0x7E).
 *
 * @param {Buffer} tokenBuf
 * @throws {Error} If token is invalid or empty
 */
function validateTelegramTokenBuffer(tokenBuf) {
  if (!Buffer.isBuffer(tokenBuf)) {
    throw new TypeError('token must be a Buffer (fail-closed)');
  }
  if (tokenBuf.length === 0) {
    throw new Error('INVALID_TELEGRAM_TOKEN_SYNTAX: Token Buffer is empty (fail-closed)');
  }
  for (let i = 0; i < tokenBuf.length; i++) {
    const byte = tokenBuf[i];
    if (byte < 0x21 || byte > 0x7E || byte === 0x2F || byte === 0x3F) {
      throw new Error(
        `INVALID_TELEGRAM_TOKEN_SYNTAX: Token contains forbidden byte 0x${byte.toString(16)} at index ${i} (fail-closed)`
      );
    }
  }
}

class TelegramInboundAdapter {
  #accountRegistry;
  #secretProvider;
  #stateRepository;
  #fetchFn;
  #apiBaseUrl;
  #pollTimeoutSeconds;
  #clientTimeoutMs;
  #weekRebaseMs;
  #clock;

  #running = false;
  #activeAccountId = null;
  #botTokenBuffer = null;
  #abortController = null;
  #pollLoopPromise = null;
  #activeTimer = null;
  #timerResolve = null;
  #backoffIndex = 0;
  #lastError = null;

  /**
   * @param {object} options
   * @param {object} options.accountRegistry - AccountRegistry instance
   * @param {object} options.secretProvider - SecretProvider instance
   * @param {object} options.stateRepository - SqliteStateRepository instance
   * @param {function} [options.fetchFn] - Custom fetch implementation (defaults to globalThis.fetch)
   * @param {string} [options.apiBaseUrl] - Telegram API base URL (defaults to 'https://api.telegram.org')
   * @param {number} [options.pollTimeoutSeconds] - Long poll timeout in seconds (defaults to 30)
   * @param {number} [options.clientTimeoutMs] - Client-side request timeout in ms (defaults to 40_000)
   * @param {number} [options.weekRebaseMs] - Stale cursor rebase threshold (defaults to 604_800_000)
   * @param {function} [options.clock] - Timestamp generator (defaults to Date.now)
   */
  constructor(options = {}) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      throw new TypeError('TelegramInboundAdapter options must be a non-null object');
    }

    if (!options.accountRegistry || typeof options.accountRegistry.getActive !== 'function') {
      throw new TypeError('accountRegistry with getActive() is required');
    }
    if (!options.secretProvider || typeof options.secretProvider.getSecret !== 'function') {
      throw new TypeError('secretProvider with getSecret() is required');
    }
    if (!options.stateRepository || typeof options.stateRepository.ingestMessage !== 'function') {
      throw new TypeError('stateRepository with ingestMessage() is required');
    }

    this.#accountRegistry = options.accountRegistry;
    this.#secretProvider = options.secretProvider;
    this.#stateRepository = options.stateRepository;
    this.#fetchFn = options.fetchFn || globalThis.fetch;
    if (typeof this.#fetchFn !== 'function') {
      throw new TypeError('fetchFn must be a function');
    }

    this.#apiBaseUrl = (options.apiBaseUrl || 'https://api.telegram.org').replace(/\/+$/, '');
    this.#pollTimeoutSeconds =
      typeof options.pollTimeoutSeconds === 'number' && options.pollTimeoutSeconds >= 0
        ? options.pollTimeoutSeconds
        : typeof options.pollTimeoutSec === 'number' && options.pollTimeoutSec >= 0
          ? options.pollTimeoutSec
          : TELEGRAM_POLL_TIMEOUT_SECONDS;
    this.#clientTimeoutMs =
      typeof options.clientTimeoutMs === 'number' && options.clientTimeoutMs > 0
        ? options.clientTimeoutMs
        : TELEGRAM_CLIENT_TIMEOUT_MS;
    this.#weekRebaseMs =
      typeof options.weekRebaseMs === 'number' && options.weekRebaseMs > 0
        ? options.weekRebaseMs
        : TELEGRAM_WEEK_REBASE_MS;
    this.#clock = typeof options.clock === 'function' ? options.clock : () => Date.now();
  }

  /**
   * @returns {boolean}
   */
  get isRunning() {
    return this.#running;
  }

  /**
   * @returns {string|null}
   */
  get activeAccountId() {
    return this.#activeAccountId;
  }

  /**
   * @returns {string|null}
   */
  get activeChannelId() {
    return this.#activeAccountId ? TELEGRAM_CHANNEL_ID : null;
  }

  /**
   * Starts the inbound adapter lifecycle.
   *
   * Invariants (M4, M13, M14):
   * - Validates active account in registry (must be channel='telegram', enabled=true).
   * - Retrieves bot token secret exactly once per start lifecycle.
   * - Validates token grammar and initializes authoritative buffer.
   * - Starts asynchronous long-polling loop in the background.
   */
  start() {
    if (this.#running) {
      throw new Error('TelegramInboundAdapter is already running');
    }

    // 1. Account verification (M4 / M5)
    const activeAccount = this.#accountRegistry.getActive();
    if (!activeAccount) {
      throw new Error('NO_ACTIVE_TELEGRAM_ACCOUNT: No active account found in AccountRegistry (fail-closed)');
    }
    if (activeAccount.channel !== TELEGRAM_CHANNEL_ID) {
      throw new Error(
        `NO_ACTIVE_TELEGRAM_ACCOUNT: Active account channel is '${activeAccount.channel}', expected '${TELEGRAM_CHANNEL_ID}' (fail-closed)`
      );
    }
    if (activeAccount.enabled !== true) {
      throw new Error('NO_ACTIVE_TELEGRAM_ACCOUNT: Active account is disabled (fail-closed)');
    }

    this.#activeAccountId = activeAccount.id;

    // 2. Secret lookup: exactly once per start lifecycle (M13)
    const secretRef = SecretRef.telegramBotToken(this.#activeAccountId);
    const tokenBuffer = this.#secretProvider.getSecret(secretRef);
    if (!Buffer.isBuffer(tokenBuffer)) {
      throw new Error('SecretProvider must return a Buffer (fail-closed)');
    }

    // 3. Token ASCII grammar validation (M14)
    validateTelegramTokenBuffer(tokenBuffer);
    this.#botTokenBuffer = Buffer.from(tokenBuffer);

    this.#running = true;
    this.#backoffIndex = 0;

    // 4. Launch polling loop
    this.#pollLoopPromise = this.#runPollLoop().catch((err) => {
      this.#running = false;
      this.#lastError = err;
    });

    return this;
  }

  /**
   * Stops the adapter and cancels any active polling requests or retry timers.
   *
   * Invariants (M2, M13):
   * - Aborts any active HTTP fetch request.
   * - Cancels any pending backoff timer.
   * - Awaits loop quiescence.
   * - Zeroizes authoritative token buffer.
   * - Does NOT close the repository.
   */
  async stop() {
    this.#running = false;

    // Cancel active timer if waiting
    if (this.#activeTimer) {
      clearTimeout(this.#activeTimer);
      this.#activeTimer = null;
    }
    if (this.#timerResolve) {
      this.#timerResolve();
      this.#timerResolve = null;
    }

    // Abort active fetch if pending
    if (this.#abortController) {
      try {
        this.#abortController.abort();
      } catch (_) {}
      this.#abortController = null;
    }

    // Await background poll loop termination
    if (this.#pollLoopPromise) {
      try {
        await this.#pollLoopPromise;
      } catch (_) {}
      this.#pollLoopPromise = null;
    }

    // Zeroize authoritative token Buffer
    if (this.#botTokenBuffer) {
      try {
        this.#botTokenBuffer.fill(0);
      } catch (_) {}
      this.#botTokenBuffer = null;
    }
  }

  /**
   * Main polling loop.
   */
  async #runPollLoop() {
    while (this.#running) {
      try {
        // 1. Check week rebase and read durable cursor state (M8)
        let offset = undefined;
        const nowMs = this.#clock();
        const cursorState = this.#stateRepository.getIngestCursorState(this.#activeAccountId);

        if (cursorState) {
          const { cursorValue, updatedAtMs } = cursorState;
          if (
            typeof updatedAtMs !== 'number' ||
            !Number.isSafeInteger(updatedAtMs) ||
            updatedAtMs < 0 ||
            updatedAtMs > nowMs
          ) {
            throw new Error(
              `INVALID_CURSOR_TIMESTAMP: Stored cursor timestamp (${updatedAtMs}) is invalid or in the future compared to clock (${nowMs}) (fail-closed)`
            );
          }

          if (nowMs - updatedAtMs >= this.#weekRebaseMs) {
            // Week rebase condition met (M8): reset stale cursor via exact-state match and omit offset
            this.#stateRepository.resetIngestCursorForTransportRebase({
              accountId: this.#activeAccountId,
              expectedCursorValue: cursorValue,
              expectedUpdatedAtMs: updatedAtMs,
            });
            offset = undefined;
          } else {
            // Safe cursor exists: pass numeric offset to Telegram getUpdates
            offset = Number(cursorValue);
          }
        }

        // 2. Protocol-boundary request construction (M14)
        // Construct ephemeral URL without storing token string in instance fields
        const tokenString = this.#botTokenBuffer.toString('utf8');
        const url = `${this.#apiBaseUrl}/bot${tokenString}/getUpdates`;

        const requestBody = {
          timeout: this.#pollTimeoutSeconds,
          allowed_updates: [],
        };
        if (offset !== undefined) {
          requestBody.offset = offset;
        }

        // 3. Issue HTTP request with client-side timeout (M11)
        const ac = new AbortController();
        this.#abortController = ac;
        const timerId = setTimeout(() => {
          ac.abort(new Error('CLIENT_TIMEOUT'));
        }, this.#clientTimeoutMs);
        if (typeof timerId?.unref === 'function') {
          timerId.unref();
        }

        let response;
        try {
          response = await this.#fetchFn(url, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
            signal: ac.signal,
          });
        } finally {
          clearTimeout(timerId);
          this.#abortController = null;
        }

        if (!this.#running) {
          break;
        }

        // 4. Response handling & error contract (M12)
        if (response.status === 409) {
          throw new Error('TELEGRAM_RECEIVER_CONFLICT: HTTP 409 Conflict received from Telegram API (fail-closed)');
        }

        if (response.status === 429) {
          // Parse retry_after
          let retrySeconds = null;
          try {
            const body429 = await response.json();
            if (body429 && body429.parameters && typeof body429.parameters.retry_after === 'number') {
              const r = body429.parameters.retry_after;
              if (Number.isSafeInteger(r) && r > 0 && r * 1000 <= 2147483647) {
                retrySeconds = r;
              }
            }
          } catch (_) {}

          if (retrySeconds === null) {
            throw new Error('RATE_LIMITED_TERMINAL: Invalid or missing retry_after in 429 response (fail-closed)');
          }
          await this.#waitDelay(retrySeconds * 1000);
          continue;
        }

        if (response.status >= 500) {
          // Retryable server error
          await this.#waitDelay(this.#getBackoffDelay());
          continue;
        }

        if (!response.ok) {
          throw new Error(`HTTP_CLIENT_ERROR: Telegram API returned HTTP status ${response.status} (fail-closed)`);
        }

        // Parse JSON payload
        let payload;
        try {
          payload = await response.json();
        } catch (_) {
          // Malformed JSON is a retryable protocol failure (M12)
          await this.#waitDelay(this.#getBackoffDelay());
          continue;
        }

        if (!payload || typeof payload !== 'object' || payload.ok !== true || !Array.isArray(payload.result)) {
          if (payload && payload.ok === false) {
            if (payload.error_code === 409) {
              throw new Error('TELEGRAM_RECEIVER_CONFLICT: Telegram API returned error 409 (fail-closed)');
            }
            if (payload.error_code === 429 && payload.parameters && typeof payload.parameters.retry_after === 'number') {
              const r = payload.parameters.retry_after;
              if (Number.isSafeInteger(r) && r > 0 && r * 1000 <= 2147483647) {
                await this.#waitDelay(r * 1000);
                continue;
              }
            }
            if (typeof payload.error_code === 'number' && payload.error_code >= 500) {
              await this.#waitDelay(this.#getBackoffDelay());
              continue;
            }
            throw new Error(
              `TELEGRAM_API_ERROR: Telegram API returned ok=false: ${payload.description || 'unknown error'} (fail-closed)`
            );
          }
          // Result not array or malformed response
          await this.#waitDelay(this.#getBackoffDelay());
          continue;
        }

        // 5. Valid successful response: reset generic backoff (M12)
        this.#backoffIndex = 0;

        // 6. Process updates in order (M9, M10)
        for (const update of payload.result) {
          if (!this.#running) {
            break;
          }
          this.#processUpdate(update);
        }

        if (this.#pollTimeoutSeconds === 0) {
          await this.#waitDelay(10);
        }
      } catch (err) {
        if (!this.#running) {
          break;
        }

        // Check if error is terminal
        if (
          err.message &&
          (err.message.includes('TELEGRAM_RECEIVER_CONFLICT') ||
            err.message.includes('RATE_LIMITED_TERMINAL') ||
            err.message.includes('HTTP_CLIENT_ERROR') ||
            err.message.includes('TELEGRAM_API_ERROR') ||
            err.message.includes('INVALID_CURSOR_TIMESTAMP'))
        ) {
          this.#running = false;
          this.#lastError = err;
          break;
        }

        // Retryable network or timeout exception: apply generic backoff
        await this.#waitDelay(this.#getBackoffDelay());
      }
    }
  }

  /**
   * Processes a single Telegram Update item according to classification rules (M9, M10).
   *
   * @param {object} update
   */
  #processUpdate(update) {
    const classification = classifyTelegramUpdate(update);
    if (classification.type === 'INVALID') {
      return;
    }

    const platformEventId = String(update.update_id);
    const cursorValue = String(update.update_id + 1);
    const cursorObservedAtMs = this.#clock();

    if (classification.type === 'MESSAGE') {
      this.#stateRepository.ingestMessage({
        accountId: this.#activeAccountId,
        platformEventId,
        platformMsgId: classification.platformMsgId,
        channelId: TELEGRAM_CHANNEL_ID,
        content: classification.content,
        cursorValue,
        cursorObservedAtMs,
      });
    } else if (classification.type === 'EDIT') {
      this.#stateRepository.ingestEdit({
        accountId: this.#activeAccountId,
        platformEventId,
        platformMsgId: classification.platformMsgId,
        channelId: TELEGRAM_CHANNEL_ID,
        content: classification.content,
        cursorValue,
        cursorObservedAtMs,
      });
    } else {
      this.#stateRepository.recordIgnoredEvent({
        accountId: this.#activeAccountId,
        platformEventId,
        cursorValue,
        cursorObservedAtMs,
      });
    }
  }

  /**
   * Calculates next generic retry backoff delay.
   *
   * @returns {number} Delay in milliseconds
   */
  #getBackoffDelay() {
    const delay = GENERIC_BACKOFF_MS[this.#backoffIndex];
    if (this.#backoffIndex < GENERIC_BACKOFF_MS.length - 1) {
      this.#backoffIndex++;
    }
    return delay;
  }

  /**
   * Cancellable delay helper.
   *
   * @param {number} ms
   * @returns {Promise<void>}
   */
  #waitDelay(ms) {
    if (!this.#running || ms <= 0) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      this.#timerResolve = resolve;
      this.#activeTimer = setTimeout(() => {
        this.#activeTimer = null;
        this.#timerResolve = null;
        resolve();
      }, ms);
      if (typeof this.#activeTimer?.unref === 'function') {
        this.#activeTimer.unref();
      }
    });
  }
}

/**
 * Classifies an inbound Telegram Update object (M10).
 *
 * @param {object} update
 * @returns {{
 *   type: 'MESSAGE' | 'EDIT' | 'IGNORED' | 'INVALID',
 *   platformMsgId?: string,
 *   content?: string,
 *   reason?: string
 * }}
 */
function classifyTelegramUpdate(update) {
  if (!update || typeof update !== 'object') {
    return { type: 'INVALID', reason: 'NON_OBJECT_UPDATE' };
  }
  const updateId = update.update_id;
  if (
    typeof updateId !== 'number' ||
    !Number.isSafeInteger(updateId) ||
    updateId < 0 ||
    !Number.isSafeInteger(updateId + 1)
  ) {
    return { type: 'INVALID', reason: 'INVALID_UPDATE_ID' };
  }

  if (update.message && typeof update.message === 'object' && typeof update.message.text === 'string') {
    const msg = update.message;
    const chat = msg.chat;
    const msgId = msg.message_id;
    if (!chat || typeof chat.id !== 'number' || !Number.isSafeInteger(chat.id) || typeof msgId !== 'number' || !Number.isSafeInteger(msgId)) {
      return { type: 'INVALID', reason: 'MALFORMED_MESSAGE_IDENTITY' };
    }
    return {
      type: 'MESSAGE',
      platformMsgId: `tg:${chat.id}:${msgId}`,
      content: msg.text,
    };
  }

  if (update.edited_message && typeof update.edited_message === 'object' && typeof update.edited_message.text === 'string') {
    const msg = update.edited_message;
    const chat = msg.chat;
    const msgId = msg.message_id;
    if (!chat || typeof chat.id !== 'number' || !Number.isSafeInteger(chat.id) || typeof msgId !== 'number' || !Number.isSafeInteger(msgId)) {
      return { type: 'INVALID', reason: 'MALFORMED_EDIT_IDENTITY' };
    }
    return {
      type: 'EDIT',
      platformMsgId: `tg:${chat.id}:${msgId}`,
      content: msg.text,
    };
  }

  return {
    type: 'IGNORED',
    reason: 'UNSUPPORTED_UPDATE_TYPE',
  };
}

module.exports = {
  TelegramInboundAdapter,
  TELEGRAM_CHANNEL_ID,
  TELEGRAM_WEEK_REBASE_MS,
  TELEGRAM_CLIENT_TIMEOUT_MS,
  TELEGRAM_POLL_TIMEOUT_SECONDS,
  GENERIC_BACKOFF_MS,
  validateTelegramTokenBuffer,
  classifyTelegramUpdate,
};
