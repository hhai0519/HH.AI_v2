/**
 * runtime/channel-gateway/adapters/telegram-inbound-adapter.js
 *
 * ADR-0022 / ADR-0024 / ADR-0026 / TG-MVP-10 R2: Telegram Test-Bot Inbound Adapter.
 *
 * Invariants (M1–M15 & R2 Hardening):
 * - Composable inbound long-poll adapter component (NOT an OS process root).
 * - start() and async stop() lifecycle management.
 * - Does NOT close the state repository on stop (repository lifecycle owned externally).
 * - Depends on AccountRegistry for non-secret metadata; start() requires active, enabled account for channel 'telegram'.
 * - Looks up bot token secret via SecretProvider strictly ONCE on start().
 * - Adopts exact provider-returned Buffer directly (caller-exclusive contract); no authoritative Buffer.from() copy.
 * - Authoritative token Buffer zeroized via buf.fill(0) on stop or any terminal failure.
 * - Strict structural token grammar: ^[0-9]+:[A-Za-z0-9_-]+$ (digits:secret).
 *     Rejects: /, ?, #, \, %, whitespace, C0, DEL, non-ASCII, extra colon, missing colon, empty bot id, empty secret.
 *     Failure diagnostic is bounded stable code only (INVALID_TELEGRAM_TOKEN_SYNTAX) without token material, byte, or index.
 * - Protocol-boundary exception: creates unavoidable ephemeral UTF-8 URL strictly inside request-construction boundary.
 *     Ephemeral URL is never stored, cached, returned, logged, or reflected in diagnostics.
 * - Node built-ins only (fetch, AbortController, URL, timers); zero new npm dependencies.
 * - Fixed production constants:
 *     TELEGRAM_API_ORIGIN = 'https://api.telegram.org'
 *     TELEGRAM_POLL_TIMEOUT_SECONDS = 30
 *     TELEGRAM_CLIENT_TIMEOUT_MS = 40_000
 *     TELEGRAM_WEEK_REBASE_MS = 604_800_000
 * - Strict constructor options allowlist: unknown options rejected with TypeError.
 * - Active-account hot-switch guards before request and after response before update processing.
 * - Inbound update classification:
 *     valid update_id + valid message.text -> MESSAGE (ingestMessage)
 *     valid update_id + valid edited_message.text -> EDIT (ingestEdit)
 *     valid update_id + unsupported/malformed payload -> IGNORED (recordIgnoredEvent + cursor advance, prevents poison loop)
 *     invalid update_id -> zero mutation, no cursor advance, no event
 * - Identity:
 *     platform_event_id: String(update.update_id)
 *     cursor_value: String(update.update_id + 1)
 *     platform_msg_id: tg:<chat_id>:<message_id>
 * - Week-rebase (M8):
 *     If nowMs - updatedAtMs >= 604800000, calls resetIngestCursorForTransportRebase and omits offset.
 * - Error & retry contract:
 *     Strict retry allowlist: network transport rejection, client timeout, HTTP 5xx, malformed JSON,
 *     ok=true missing/non-array result, Telegram ok=false error_code >= 500, 429 with valid retry_after.
 *     Repository errors, HTTP 409, 401, 403, other 4xx, invalid 429, active account change are TERMINAL fail-closed.
 *     Terminal paths stop loop, set bounded status, and zeroize token Buffer.
 */

'use strict';

const { SecretRef } = require('../core/secret-provider');

const TELEGRAM_CHANNEL_ID = 'telegram';
const TELEGRAM_API_ORIGIN = 'https://api.telegram.org';
const TELEGRAM_WEEK_REBASE_MS = 604_800_000; // 7 days in milliseconds
const TELEGRAM_CLIENT_TIMEOUT_MS = 40_000;
const TELEGRAM_POLL_TIMEOUT_SECONDS = 30;
const GENERIC_BACKOFF_MS = Object.freeze([1000, 2000, 4000, 8000, 16000, 30000]);

const ALLOWED_CONSTRUCTOR_KEYS = new Set([
  'accountRegistry',
  'secretProvider',
  'stateRepository',
  'fetchFn',
  'now',
  'setTimeoutFn',
  'clearTimeoutFn',
  'abortControllerFactory',
  'logger',
]);

/**
 * Validates raw Buffer bytes against strict structural grammar:
 * ^[0-9]+:[A-Za-z0-9_-]+$
 *
 * Requirements:
 * - One or more ASCII decimal digits before structural colon.
 * - Exactly one structural colon.
 * - One or more characters after colon from: A-Z, a-z, 0-9, _, -
 * - Diagnostic: INVALID_TELEGRAM_TOKEN_SYNTAX only (no token material, bad byte, or byte index).
 *
 * @param {Buffer} tokenBuf
 * @throws {TypeError|Error}
 */
function validateTelegramTokenBuffer(tokenBuf) {
  if (!Buffer.isBuffer(tokenBuf)) {
    throw new TypeError('token must be a Buffer (fail-closed)');
  }
  if (tokenBuf.length < 3) {
    throw new Error('INVALID_TELEGRAM_TOKEN_SYNTAX');
  }

  let colonIndex = -1;
  for (let i = 0; i < tokenBuf.length; i++) {
    const b = tokenBuf[i];
    if (b === 0x3a) { // ':'
      if (colonIndex !== -1) {
        // multiple colons rejected
        throw new Error('INVALID_TELEGRAM_TOKEN_SYNTAX');
      }
      colonIndex = i;
    } else if (colonIndex === -1) {
      // Before colon: digits 0-9 only (0x30 - 0x39)
      if (b < 0x30 || b > 0x39) {
        throw new Error('INVALID_TELEGRAM_TOKEN_SYNTAX');
      }
    } else {
      // After colon: A-Z, a-z, 0-9, _, -
      const isUpper = b >= 0x41 && b <= 0x5a;
      const isLower = b >= 0x61 && b <= 0x7a;
      const isDigit = b >= 0x30 && b <= 0x39;
      const isUnderscore = b === 0x5f;
      const isDash = b === 0x2d;
      if (!isUpper && !isLower && !isDigit && !isUnderscore && !isDash) {
        throw new Error('INVALID_TELEGRAM_TOKEN_SYNTAX');
      }
    }
  }

  // Must have at least 1 digit before colon and at least 1 char after colon
  if (colonIndex <= 0 || colonIndex === tokenBuf.length - 1) {
    throw new Error('INVALID_TELEGRAM_TOKEN_SYNTAX');
  }
}

class TelegramInboundAdapter {
  #accountRegistry;
  #secretProvider;
  #stateRepository;
  #fetchFn;
  #now;
  #setTimeoutFn;
  #clearTimeoutFn;
  #abortControllerFactory;
  #logger;

  #running = false;
  #activeAccountId = null;
  #botTokenBuffer = null;
  #abortController = null;
  #pollLoopPromise = null;
  #activeTimer = null;
  #timerResolve = null;
  #backoffIndex = 0;
  #terminalReason = null;

  /**
   * @param {object} options
   * @param {object} options.accountRegistry - AccountRegistry instance
   * @param {object} options.secretProvider - SecretProvider instance
   * @param {object} options.stateRepository - SqliteStateRepository instance
   * @param {function} [options.fetchFn] - Custom fetch implementation
   * @param {function} [options.now] - Timestamp generator (defaults to Date.now)
   * @param {function} [options.setTimeoutFn] - Custom setTimeout implementation
   * @param {function} [options.clearTimeoutFn] - Custom clearTimeout implementation
   * @param {function} [options.abortControllerFactory] - Custom AbortController factory
   * @param {object} [options.logger] - Optional logger
   */
  constructor(options = {}) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      throw new TypeError('TelegramInboundAdapter options must be a non-null object');
    }

    // Strict constructor options allowlist
    for (const key of Object.keys(options)) {
      if (!ALLOWED_CONSTRUCTOR_KEYS.has(key)) {
        throw new TypeError(`Unknown constructor option: '${key}' (fail-closed)`);
      }
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

    this.#now = typeof options.now === 'function' ? options.now : () => Date.now();
    this.#setTimeoutFn = typeof options.setTimeoutFn === 'function' ? options.setTimeoutFn : setTimeout;
    this.#clearTimeoutFn = typeof options.clearTimeoutFn === 'function' ? options.clearTimeoutFn : clearTimeout;
    this.#abortControllerFactory =
      typeof options.abortControllerFactory === 'function'
        ? options.abortControllerFactory
        : () => new AbortController();
    this.#logger = options.logger || null;
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
   * @returns {string|null} Bounded stable diagnostic status/reason if stopped/terminated
   */
  get terminalReason() {
    return this.#terminalReason;
  }

  /**
   * Zeroizes authoritative token Buffer.
   * Single idempotent cleanup primitive.
   */
  #zeroizeToken() {
    if (this.#botTokenBuffer) {
      try {
        this.#botTokenBuffer.fill(0);
      } catch (_) {}
      this.#botTokenBuffer = null;
    }
  }

  /**
   * Validates active account status against captured account ID.
   *
   * @returns {boolean}
   */
  #verifyActiveAccount() {
    try {
      const active = this.#accountRegistry.getActive();
      if (
        !active ||
        active.channel !== TELEGRAM_CHANNEL_ID ||
        active.enabled !== true ||
        active.id !== this.#activeAccountId
      ) {
        return false;
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  /**
   * Starts the inbound adapter lifecycle.
   *
   * Invariants (M4, M13, M14, R2):
   * - Validates active account in registry (must be channel='telegram', enabled=true).
   * - Retrieves bot token secret exactly once per start lifecycle.
   * - Adopts exact provider-returned Buffer directly.
   * - Validates token grammar; on validation failure, immediately zeroizes Buffer and fails.
   * - Starts asynchronous long-polling loop in the background.
   */
  start() {
    if (this.#running) {
      throw new Error('TelegramInboundAdapter is already running');
    }

    this.#terminalReason = null;

    // 1. Account verification
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

    // 2. Secret lookup: exactly once per start lifecycle
    const secretRef = SecretRef.telegramBotToken(this.#activeAccountId);
    const tokenBuffer = this.#secretProvider.getSecret(secretRef);
    if (!Buffer.isBuffer(tokenBuffer)) {
      throw new TypeError('SecretProvider must return a Buffer (fail-closed)');
    }

    // 3. Adopt exact provider-returned Buffer directly; zeroize on validation failure
    this.#botTokenBuffer = tokenBuffer;
    try {
      validateTelegramTokenBuffer(this.#botTokenBuffer);
    } catch (err) {
      this.#zeroizeToken();
      this.#running = false;
      this.#terminalReason = 'INVALID_TELEGRAM_TOKEN_SYNTAX';
      throw err;
    }

    this.#running = true;
    this.#backoffIndex = 0;

    // 4. Launch polling loop
    this.#pollLoopPromise = this.#runPollLoop().catch((_err) => {
      this.#running = false;
      this.#zeroizeToken();
      if (!this.#terminalReason) {
        this.#terminalReason = 'INTERNAL_TERMINAL';
      }
    });

    return this;
  }

  /**
   * Stops the adapter and cancels any active polling requests or retry timers.
   *
   * Invariants (M2, M13, R2):
   * - Aborts any active HTTP fetch request and pending response body parse.
   * - Cancels any pending backoff timer.
   * - Awaits loop quiescence.
   * - Zeroizes authoritative token Buffer.
   * - Does NOT close the repository.
   */
  async stop() {
    this.#running = false;

    // Cancel active retry timer if waiting
    if (this.#activeTimer) {
      this.#clearTimeoutFn(this.#activeTimer);
      this.#activeTimer = null;
    }
    if (this.#timerResolve) {
      this.#timerResolve();
      this.#timerResolve = null;
    }

    // Abort active fetch or response body parse if in flight
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
    this.#zeroizeToken();
  }

  /**
   * Main polling loop.
   */
  async #runPollLoop() {
    while (this.#running) {
      // Pre-request hot-switch check (§15)
      if (!this.#verifyActiveAccount()) {
        this.#running = false;
        this.#terminalReason = 'ACTIVE_ACCOUNT_CHANGED';
        this.#zeroizeToken();
        break;
      }

      // 1. Check week rebase and read durable cursor state (§18: repository errors terminal)
      let offset = undefined;
      const nowMs = this.#now();
      let cursorState;
      try {
        cursorState = this.#stateRepository.getIngestCursorState(this.#activeAccountId);
      } catch (_repoErr) {
        this.#running = false;
        this.#terminalReason = 'REPOSITORY_TERMINAL';
        this.#zeroizeToken();
        break;
      }

      if (cursorState) {
        const { cursorValue, updatedAtMs } = cursorState;
        if (
          typeof updatedAtMs !== 'number' ||
          !Number.isSafeInteger(updatedAtMs) ||
          updatedAtMs < 0 ||
          updatedAtMs > nowMs
        ) {
          this.#running = false;
          this.#terminalReason = 'INVALID_CURSOR_TIMESTAMP';
          this.#zeroizeToken();
          break;
        }

        if (nowMs - updatedAtMs >= TELEGRAM_WEEK_REBASE_MS) {
          // Week rebase condition met (M8): reset stale cursor via exact-state match and omit offset
          try {
            this.#stateRepository.resetIngestCursorForTransportRebase({
              accountId: this.#activeAccountId,
              expectedCursorValue: cursorValue,
              expectedUpdatedAtMs: updatedAtMs,
            });
          } catch (_rebaseErr) {
            this.#running = false;
            this.#terminalReason = 'REPOSITORY_TERMINAL';
            this.#zeroizeToken();
            break;
          }
          offset = undefined;
        } else {
          // Safe cursor exists: pass numeric offset to Telegram getUpdates
          offset = Number(cursorValue);
        }
      }

      if (!this.#running) {
        break;
      }

      // 2. Protocol-boundary request construction (§24)
      const tokenString = this.#botTokenBuffer.toString('utf8');
      const url = `${TELEGRAM_API_ORIGIN}/bot${tokenString}/getUpdates`;

      const requestBody = {
        timeout: TELEGRAM_POLL_TIMEOUT_SECONDS,
        allowed_updates: [],
      };
      if (offset !== undefined) {
        requestBody.offset = offset;
      }

      // 3. Issue HTTP request with client-side timeout covering fetch & body parse (§19, §20)
      const ac = this.#abortControllerFactory();
      this.#abortController = ac;
      let isClientTimeout = false;
      const timerId = this.#setTimeoutFn(() => {
        isClientTimeout = true;
        try {
          ac.abort();
        } catch (_) {}
      }, TELEGRAM_CLIENT_TIMEOUT_MS);
      if (typeof timerId?.unref === 'function') {
        timerId.unref();
      }

      let response;
      let responseBodyParseFailed = false;
      let payload = null;
      let isRateLimited = false;
      let retrySeconds = null;

      try {
        response = await this.#fetchFn(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
          signal: ac.signal,
        });

        // 4. Response handling with AbortController still covering body parsing
        if (response.status === 409) {
          this.#running = false;
          this.#terminalReason = 'TELEGRAM_RECEIVER_CONFLICT';
          this.#zeroizeToken();
          break;
        }

        if (response.status === 429) {
          isRateLimited = true;
          try {
            const body429 = await response.json();
            if (
              body429 &&
              body429.parameters &&
              typeof body429.parameters.retry_after === 'number'
            ) {
              const r = body429.parameters.retry_after;
              if (Number.isSafeInteger(r) && r > 0 && r * 1000 <= 2147483647) {
                retrySeconds = r;
              }
            }
          } catch (_) {
            // Malformed 429 body
          }
        } else if (response.status >= 500) {
          // Retryable server error (5xx)
          // Body parse not strictly needed, but let's safely consume or ignore
        } else if (!response.ok) {
          // Other 4xx (401, 403, 400, etc.) are terminal fail-closed
          this.#running = false;
          this.#terminalReason = 'HTTP_CLIENT_ERROR';
          this.#zeroizeToken();
          break;
        } else {
          // 2xx response: parse JSON payload while controller & timer active
          try {
            payload = await response.json();
          } catch (_) {
            responseBodyParseFailed = true;
          }
        }
      } catch (transportErr) {
        if (!this.#running) {
          // Manual stop() abort: terminate quietly without retrying (§19)
          break;
        }
        if (isClientTimeout) {
          // Client timeout fired while running: retryable transport timeout (§19)
          await this.#waitDelay(this.#getBackoffDelay());
          continue;
        }
        // Network / fetch rejection while running: retryable (§17)
        await this.#waitDelay(this.#getBackoffDelay());
        continue;
      } finally {
        this.#clearTimeoutFn(timerId);
        this.#abortController = null;
      }

      if (!this.#running) {
        break;
      }

      // Handle 429 outcome
      if (isRateLimited) {
        if (retrySeconds === null) {
          this.#running = false;
          this.#terminalReason = 'TELEGRAM_API_ERROR';
          this.#zeroizeToken();
          break;
        }
        // Valid 429 retry_after: uses exact delay and does NOT advance generic backoff (§27)
        await this.#waitDelay(retrySeconds * 1000);
        continue;
      }

      // Handle 5xx
      if (response && response.status >= 500) {
        await this.#waitDelay(this.#getBackoffDelay());
        continue;
      }

      // Handle malformed JSON body
      if (responseBodyParseFailed) {
        await this.#waitDelay(this.#getBackoffDelay());
        continue;
      }

      // Handle payload structure & Telegram API error
      if (!payload || typeof payload !== 'object' || payload.ok !== true || !Array.isArray(payload.result)) {
        if (payload && payload.ok === false) {
          if (payload.error_code === 409) {
            this.#running = false;
            this.#terminalReason = 'TELEGRAM_RECEIVER_CONFLICT';
            this.#zeroizeToken();
            break;
          }
          if (
            payload.error_code === 429 &&
            payload.parameters &&
            typeof payload.parameters.retry_after === 'number'
          ) {
            const r = payload.parameters.retry_after;
            if (Number.isSafeInteger(r) && r > 0 && r * 1000 <= 2147483647) {
              await this.#waitDelay(r * 1000);
              continue;
            }
            this.#running = false;
            this.#terminalReason = 'TELEGRAM_API_ERROR';
            this.#zeroizeToken();
            break;
          }
          if (typeof payload.error_code === 'number' && payload.error_code >= 500) {
            // Telegram server-side error code >= 500: retryable
            await this.#waitDelay(this.#getBackoffDelay());
            continue;
          }
          // Non-5xx Telegram API error is terminal; description NEVER exposed (§16)
          this.#running = false;
          this.#terminalReason = 'TELEGRAM_API_ERROR';
          this.#zeroizeToken();
          break;
        }
        // Result missing or non-array: retryable protocol failure (§17)
        await this.#waitDelay(this.#getBackoffDelay());
        continue;
      }

      // Post-response hot-switch check BEFORE processing any update (§15)
      if (!this.#verifyActiveAccount()) {
        this.#running = false;
        this.#terminalReason = 'ACTIVE_ACCOUNT_CHANGED';
        this.#zeroizeToken();
        break;
      }

      // 5. Valid successful response: reset generic backoff (§27)
      this.#backoffIndex = 0;

      // 6. Process updates in order (§18: repository errors terminal)
      let repositoryError = false;
      for (const update of payload.result) {
        if (!this.#running) {
          break;
        }
        try {
          this.#processUpdate(update);
        } catch (_repoErr) {
          repositoryError = true;
          this.#running = false;
          this.#terminalReason = 'REPOSITORY_TERMINAL';
          this.#zeroizeToken();
          break;
        }
      }

      if (repositoryError) {
        break;
      }
    }
  }

  /**
   * Processes a single Telegram Update item according to classification rules (§26).
   *
   * @param {object} update
   */
  #processUpdate(update) {
    const classification = classifyTelegramUpdate(update);
    if (classification.type === 'INVALID') {
      // Invalid/non-safe update_id: zero mutation, no fabricated event, no cursor advance
      return;
    }

    const platformEventId = String(update.update_id);
    const cursorValue = String(update.update_id + 1);
    const cursorObservedAtMs = this.#now();

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
      // Valid update_id but unsupported type OR malformed message/edit payload
      // Durably records IGNORED event and advances cursor, preventing poison loops (§26)
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
      this.#activeTimer = this.#setTimeoutFn(() => {
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
 * Classifies an inbound Telegram Update object (§26).
 *
 * Requirements:
 * - invalid / absent / non-safe update_id -> INVALID (zero mutation)
 * - valid update_id + valid message.text identity -> MESSAGE
 * - valid update_id + valid edited_message.text identity -> EDIT
 * - valid update_id + malformed/unsupported payload/identity -> IGNORED (durable ignore + cursor advance)
 * Never silent-return for a valid update_id.
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

  // At this point, update_id is a valid non-negative safe integer.
  // Check for valid MESSAGE identity
  if (
    update.message &&
    typeof update.message === 'object' &&
    typeof update.message.text === 'string' &&
    update.message.chat &&
    typeof update.message.chat.id === 'number' &&
    Number.isSafeInteger(update.message.chat.id) &&
    typeof update.message.message_id === 'number' &&
    Number.isSafeInteger(update.message.message_id)
  ) {
    return {
      type: 'MESSAGE',
      platformMsgId: `tg:${update.message.chat.id}:${update.message.message_id}`,
      content: update.message.text,
    };
  }

  // Check for valid EDIT identity
  if (
    update.edited_message &&
    typeof update.edited_message === 'object' &&
    typeof update.edited_message.text === 'string' &&
    update.edited_message.chat &&
    typeof update.edited_message.chat.id === 'number' &&
    Number.isSafeInteger(update.edited_message.chat.id) &&
    typeof update.edited_message.message_id === 'number' &&
    Number.isSafeInteger(update.edited_message.message_id)
  ) {
    return {
      type: 'EDIT',
      platformMsgId: `tg:${update.edited_message.chat.id}:${update.edited_message.message_id}`,
      content: update.edited_message.text,
    };
  }

  // Valid update_id with unsupported type OR malformed message/edit payload -> IGNORED
  return {
    type: 'IGNORED',
    reason: 'UNSUPPORTED_OR_MALFORMED_PAYLOAD',
  };
}

module.exports = {
  TelegramInboundAdapter,
  TELEGRAM_CHANNEL_ID,
  TELEGRAM_API_ORIGIN,
  TELEGRAM_WEEK_REBASE_MS,
  TELEGRAM_CLIENT_TIMEOUT_MS,
  TELEGRAM_POLL_TIMEOUT_SECONDS,
  GENERIC_BACKOFF_MS,
  validateTelegramTokenBuffer,
  classifyTelegramUpdate,
};
