/**
 * runtime/channel-gateway/adapters/telegram-outbound-adapter.js
 *
 * TG-MVP-13: Telegram Outbound Text Delivery Adapter.
 *
 * Invariants:
 * - Composable outbound adapter component (no new daemon/process, zero new npm dependencies).
 * - Depends on AccountRegistry for non-secret metadata; rejects non-matching accounts pre-network.
 * - Looks up bot token secret via SecretProvider lazily strictly ONCE per active account lifecycle.
 * - Adopts exact provider-returned Buffer directly (caller-exclusive contract).
 * - Authoritative token Buffer zeroized via buf.fill(0) on account switch, stop, or terminal syntax error.
 * - Strict structural token grammar validation via validateTelegramTokenBuffer.
 * - Strict Native Reply (D-R3-REPLY-A): reply_parameters.message_id required from logical_reply_target;
 *     grammar ^tg:(-?\d+):(\d+)$; parsed chat_id must match recipient; no parse_mode; no allow_sending_without_reply.
 * - Ephemeral token URL created strictly at request boundary; never logged, returned, or persisted.
 * - Transport phase classification (D-R3-A+ / §12):
 *     NOT_SENT only for pre-fetch local failure or cause.code in ('ENOTFOUND', 'EAI_AGAIN', 'ECONNREFUSED').
 *     All other failures after fetch invocation (ECONNRESET, UND_ERR_*, timeout, 5xx) -> MAY_HAVE_BEEN_SENT.
 * - Active account guard before request, after response, after body parse, and after exception classification.
 * - Fixed production constants:
 *     TELEGRAM_API_ORIGIN = 'https://api.telegram.org'
 *     TELEGRAM_CLIENT_TIMEOUT_MS = 40_000
 * - Text defensive validation: 1..4096 UTF-16 code units.
 * - Strict constructor options allowlist: unknown options rejected with TypeError.
 */

'use strict';

const { SecretRef } = require('../core/secret-provider');
const {
  TELEGRAM_API_ORIGIN,
  TELEGRAM_CLIENT_TIMEOUT_MS,
  validateTelegramTokenBuffer,
} = require('./telegram-inbound-adapter');

const TELEGRAM_CHANNEL_ID = 'telegram';
const TEXT_MAX_UTF16 = 4096;
const LOGICAL_REPLY_TARGET_REGEX = /^tg:(-?\d+):(\d+)$/;

const NOT_SENT_CAUSE_CODES = new Set(['ENOTFOUND', 'EAI_AGAIN', 'ECONNREFUSED']);

const ALLOWED_CONSTRUCTOR_KEYS = new Set([
  'accountRegistry',
  'secretProvider',
  'fetchFn',
  'abortControllerFactory',
  'logger',
]);

class TelegramOutboundAdapter {
  #accountRegistry;
  #secretProvider;
  #fetchFn;
  #abortControllerFactory;
  #logger;

  #running = false;
  #cachedAccountId = null;
  #cachedTokenBuffer = null;
  #inFlightAbortControllers = new Set();
  #activeDeliveriesCount = 0;
  #quiesceResolvers = [];

  /**
   * @param {object} options
   * @param {object} options.accountRegistry
   * @param {object} options.secretProvider
   * @param {function} [options.fetchFn]
   * @param {function} [options.abortControllerFactory]
   * @param {object} [options.logger]
   */
  constructor(options = {}) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      throw new TypeError('TelegramOutboundAdapter options must be a non-null object');
    }

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

    this.#accountRegistry = options.accountRegistry;
    this.#secretProvider = options.secretProvider;
    this.#fetchFn = options.fetchFn || globalThis.fetch;
    this.#abortControllerFactory =
      options.abortControllerFactory || (() => new AbortController());
    this.#logger = options.logger || null;
  }

  get isRunning() {
    return this.#running;
  }

  get cachedAccountId() {
    return this.#cachedAccountId;
  }

  #zeroizeToken() {
    if (this.#cachedTokenBuffer) {
      try {
        this.#cachedTokenBuffer.fill(0);
      } catch (_) {}
      this.#cachedTokenBuffer = null;
    }
    this.#cachedAccountId = null;
  }

  /**
   * Starts the adapter. Marks ready/running; does NOT eagerly fetch bot token.
   * Idempotent.
   */
  start() {
    this.#running = true;
  }

  /**
   * Stops the adapter. Prevents new sends, aborts in-flight requests,
   * quiesces active deliveries, zeroizes token buffer.
   * Idempotent.
   *
   * @returns {Promise<void>}
   */
  async stop() {
    this.#running = false;

    for (const ac of this.#inFlightAbortControllers) {
      try {
        ac.abort();
      } catch (_) {}
    }
    this.#inFlightAbortControllers.clear();

    if (this.#activeDeliveriesCount > 0) {
      await new Promise((resolve) => {
        this.#quiesceResolvers.push(resolve);
      });
    }

    this.#zeroizeToken();
  }

  /**
   * Delivers an outbox command via Telegram sendMessage API.
   *
   * @param {object} command
   * @returns {Promise<{
   *   transport_phase: 'NOT_SENT' | 'MAY_HAVE_BEEN_SENT',
   *   success: boolean,
   *   http_status?: number,
   *   retry_after?: number,
   *   error_code?: string
   * }>}
   */
  async deliver(command) {
    if (!this.#running) {
      return {
        transport_phase: 'NOT_SENT',
        success: false,
        error_code: 'ADAPTER_NOT_RUNNING',
      };
    }

    if (!command || typeof command !== 'object') {
      return {
        transport_phase: 'NOT_SENT',
        success: false,
        error_code: 'INVALID_COMMAND_BOUNDARY',
      };
    }

    // F3: Fail-closed adapter command boundary validation
    if (
      command.platform !== 'telegram' ||
      command.endpoint_operation !== 'sendMessage' ||
      command.message_type !== 'text'
    ) {
      return {
        transport_phase: 'NOT_SENT',
        success: false,
        error_code: 'TELEGRAM_CLIENT_ERROR_400',
        http_status: 400,
      };
    }

    const recipient = String(command.recipient || '').trim();
    if (!recipient) {
      return {
        transport_phase: 'NOT_SENT',
        success: false,
        error_code: 'TELEGRAM_CLIENT_ERROR_400',
        http_status: 400,
      };
    }

    const text = typeof command.body === 'string' ? command.body : '';
    if (text.length < 1 || text.length > TEXT_MAX_UTF16) {
      return {
        transport_phase: 'NOT_SENT',
        success: false,
        error_code: 'TELEGRAM_CLIENT_ERROR_400',
        http_status: 400,
      };
    }

    // Strict Native Reply (D-R3-REPLY-A)
    let replyParameters = undefined;
    if (command.logical_reply_target !== null && command.logical_reply_target !== undefined) {
      const lrt = String(command.logical_reply_target).trim();
      const match = LOGICAL_REPLY_TARGET_REGEX.exec(lrt);
      if (!match) {
        return {
          transport_phase: 'NOT_SENT',
          success: false,
          error_code: 'TELEGRAM_REPLY_TARGET_INVALID',
        };
      }

      const parsedChatId = match[1];
      const parsedMsgIdStr = match[2];

      if (parsedChatId !== recipient) {
        return {
          transport_phase: 'NOT_SENT',
          success: false,
          error_code: 'TELEGRAM_REPLY_TARGET_INVALID',
        };
      }

      const parsedMsgId = Number(parsedMsgIdStr);
      if (
        !Number.isSafeInteger(parsedMsgId) ||
        parsedMsgId <= 0 ||
        String(parsedMsgId) !== parsedMsgIdStr
      ) {
        return {
          transport_phase: 'NOT_SENT',
          success: false,
          error_code: 'TELEGRAM_REPLY_TARGET_INVALID',
        };
      }

      replyParameters = {
        message_id: parsedMsgId,
      };
    }

    // Active account validation pre-network
    const active = this.#accountRegistry.getActive();

    // F1: Zeroize cached token if current active account observation changed
    if (
      this.#cachedAccountId !== null &&
      (!active ||
        active.channel !== TELEGRAM_CHANNEL_ID ||
        active.enabled !== true ||
        active.id !== this.#cachedAccountId)
    ) {
      this.#zeroizeToken();
    }

    if (
      !active ||
      active.channel !== TELEGRAM_CHANNEL_ID ||
      active.enabled !== true ||
      active.id !== command.account_id
    ) {
      return {
        transport_phase: 'NOT_SENT',
        success: false,
        error_code: 'ACCOUNT_MISMATCH_PRE_REQUEST',
      };
    }

    // Lazy load token buffer once per active lifecycle
    if (!this.#cachedTokenBuffer) {
      this.#cachedAccountId = active.id;
      let tokenBuf = null;
      try {
        tokenBuf = await this.#secretProvider.getSecret(SecretRef.telegramBotToken(active.id));
      } catch (_) {
        return {
          transport_phase: 'NOT_SENT',
          success: false,
          error_code: 'TELEGRAM_SECRET_UNAVAILABLE',
        };
      }

      if (!tokenBuf || !Buffer.isBuffer(tokenBuf)) {
        return {
          transport_phase: 'NOT_SENT',
          success: false,
          error_code: 'TELEGRAM_SECRET_UNAVAILABLE',
        };
      }

      try {
        validateTelegramTokenBuffer(tokenBuf);
      } catch (_) {
        try {
          tokenBuf.fill(0);
        } catch (_) {}
        this.#cachedTokenBuffer = null;
        this.#cachedAccountId = null;
        return {
          transport_phase: 'NOT_SENT',
          success: false,
          error_code: 'INVALID_TELEGRAM_TOKEN_SYNTAX',
        };
      }

      this.#cachedTokenBuffer = tokenBuf;
    }

    // Construct payload
    const requestPayload = {
      chat_id: recipient,
      text,
    };
    if (replyParameters) {
      requestPayload.reply_parameters = replyParameters;
    }
    const bodyStr = JSON.stringify(requestPayload);

    // Ephemeral URL only at request boundary
    const tokenStr = this.#cachedTokenBuffer.toString('utf8');
    const endpointUrl = `${TELEGRAM_API_ORIGIN}/bot${tokenStr}/sendMessage`;

    const ac = this.#abortControllerFactory ? this.#abortControllerFactory() : new AbortController();
    this.#inFlightAbortControllers.add(ac);
    this.#activeDeliveriesCount++;

    let timeoutTimer = null;
    let fetchInvoked = false;
    let response = null;

    try {
      const timeoutPromise = new Promise((_, reject) => {
        timeoutTimer = setTimeout(() => {
          try {
            ac.abort();
          } catch (_) {}
          const err = new Error('Telegram client timeout');
          err.name = 'AbortError';
          reject(err);
        }, TELEGRAM_CLIENT_TIMEOUT_MS);
      });

      fetchInvoked = true;
      response = await Promise.race([
        this.#fetchFn(endpointUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: bodyStr,
          signal: ac.signal,
        }),
        timeoutPromise,
      ]);
    } catch (fetchErr) {
      let phase = 'MAY_HAVE_BEEN_SENT';
      if (!fetchInvoked) {
        phase = 'NOT_SENT';
      } else {
        const causeCode =
          fetchErr && fetchErr.cause && typeof fetchErr.cause.code === 'string'
            ? fetchErr.cause.code
            : null;
        if (NOT_SENT_CAUSE_CODES.has(causeCode)) {
          phase = 'NOT_SENT';
        }
      }

      // Active account guard after exception
      const activeAfterErr = this.#accountRegistry.getActive();
      const isStillActive =
        activeAfterErr &&
        activeAfterErr.channel === TELEGRAM_CHANNEL_ID &&
        activeAfterErr.enabled === true &&
        activeAfterErr.id === command.account_id;

      if (!isStillActive) {
        if (this.#cachedAccountId !== null) {
          this.#zeroizeToken();
        }
        if (phase === 'NOT_SENT') {
          return {
            transport_phase: 'NOT_SENT',
            success: false,
            error_code: 'ACCOUNT_MISMATCH_PRE_REQUEST',
          };
        }
        return {
          transport_phase: 'MAY_HAVE_BEEN_SENT',
          success: false,
        };
      }

      return {
        transport_phase: phase,
        success: false,
      };
    } finally {
      if (timeoutTimer) {
        clearTimeout(timeoutTimer);
      }
      this.#inFlightAbortControllers.delete(ac);
      this.#activeDeliveriesCount--;
      if (this.#activeDeliveriesCount === 0 && this.#quiesceResolvers.length > 0) {
        for (const r of this.#quiesceResolvers) r();
        this.#quiesceResolvers = [];
      }
    }

    // Active account guard after response
    const activeAfterRes = this.#accountRegistry.getActive();
    if (
      !activeAfterRes ||
      activeAfterRes.channel !== TELEGRAM_CHANNEL_ID ||
      activeAfterRes.enabled !== true ||
      activeAfterRes.id !== command.account_id
    ) {
      if (this.#cachedAccountId !== null) {
        this.#zeroizeToken();
      }
      return {
        transport_phase: 'MAY_HAVE_BEEN_SENT',
        success: false,
        http_status: response.status,
      };
    }

    // Read response text
    let responseText = null;
    try {
      responseText = await response.text();
    } catch (_) {
      return {
        transport_phase: 'MAY_HAVE_BEEN_SENT',
        success: false,
        http_status: response.status,
      };
    }

    // Parse response JSON
    let parsedJson = null;
    try {
      parsedJson = JSON.parse(responseText);
    } catch (_) {
      parsedJson = null;
    }

    // Active account guard after body parse
    const activeAfterParse = this.#accountRegistry.getActive();
    if (
      !activeAfterParse ||
      activeAfterParse.channel !== TELEGRAM_CHANNEL_ID ||
      activeAfterParse.enabled !== true ||
      activeAfterParse.id !== command.account_id
    ) {
      if (this.#cachedAccountId !== null) {
        this.#zeroizeToken();
      }
      return {
        transport_phase: 'MAY_HAVE_BEEN_SENT',
        success: false,
        http_status: response.status,
      };
    }

    const status = response.status;

    // HTTP 2xx
    if (status >= 200 && status < 300) {
      if (
        parsedJson &&
        typeof parsedJson === 'object' &&
        parsedJson.ok === true &&
        parsedJson.result &&
        typeof parsedJson.result === 'object'
      ) {
        return {
          transport_phase: 'MAY_HAVE_BEEN_SENT',
          success: true,
          http_status: status,
        };
      }
      // Malformed / ambiguous 2xx payload
      return {
        transport_phase: 'MAY_HAVE_BEEN_SENT',
        success: false,
        http_status: status,
      };
    }

    // HTTP 429 Flood Control
    if (status === 429) {
      let retryAfter = undefined;
      if (
        parsedJson &&
        typeof parsedJson === 'object' &&
        parsedJson.parameters &&
        typeof parsedJson.parameters === 'object' &&
        parsedJson.parameters.retry_after !== undefined
      ) {
        retryAfter = parsedJson.parameters.retry_after;
      }
      return {
        transport_phase: 'MAY_HAVE_BEEN_SENT',
        success: false,
        http_status: 429,
        retry_after: retryAfter,
      };
    }

    // Other HTTP 4xx
    if (status >= 400 && status < 500) {
      return {
        transport_phase: 'MAY_HAVE_BEEN_SENT',
        success: false,
        http_status: status,
      };
    }

    // HTTP 5xx or others
    return {
      transport_phase: 'MAY_HAVE_BEEN_SENT',
      success: false,
      http_status: status,
    };
  }
}

module.exports = {
  TelegramOutboundAdapter,
  TELEGRAM_CHANNEL_ID,
  TEXT_MAX_UTF16,
  NOT_SENT_CAUSE_CODES,
};
