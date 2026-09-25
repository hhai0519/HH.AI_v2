#!/usr/bin/env node
/**
 * runtime/channel-gateway/bin/gateway.js
 *
 * TG-MVP-11 / D-TG11-3: Channel Gateway Production Bootstrap & Seam.
 *
 * Responsibilities:
 * - Deterministic production-bootstrap seam for GatewayRuntimeOwner.
 * - Safe to require() with ZERO side effects.
 * - Enforces D-TG11-3: exactly one enabled Telegram account at startup.
 * - Bounded stderr diagnostics: GATEWAY_CONFIG_ERROR or GATEWAY_STARTUP_ERROR only.
 * - No secrets, raw error messages, or environment leaks.
 */

'use strict';

const path = require('node:path');
const { GatewayRuntimeOwner } = require('../core/gateway-runtime-owner');
const { loadDataLocationConfigFromFile } = require('../core/local-config-loader');
const { WindowsCredentialManagerSecretProvider } = require('../core/windows-credential-manager-provider');
const { AccountRegistry } = require('../core/account-registry');

/**
 * Derives repository root from module location.
 */
function deriveRepoRoot() {
  return path.resolve(__dirname, '..', '..', '..');
}

/**
 * Pure secret provider class resolver for production bootstrap and unit testing.
 *
 * @param {object} [options={}]
 * @returns {Function} Concrete SecretProvider constructor
 */
function resolveSecretProviderClass(options = {}) {
  return options.SecretProviderClass || WindowsCredentialManagerSecretProvider;
}

/**
 * Deterministic production bootstrap function.
 *
 * @param {object} [options={}]
 * @param {string} [options.configPath]
 * @param {Array<string>} [options.args]
 * @param {string} [options.repoRoot]
 * @param {Function} [options.loadConfig]
 * @param {Function} [options.AccountRegistryClass]
 * @param {Function} [options.SecretProviderClass]
 * @param {Function} [options.RuntimeOwnerClass]
 * @param {object} [options.secretProvider]
 * @param {object} [options.owner]
 * @param {object} [options.ownerDeps]
 * @param {boolean} [options.validateStartupLocations=true]
 * @param {boolean} [options.startOwner=true]
 * @param {boolean} [options.exitOnError=false]
 * @param {object} [options.stderr]
 * @param {Function} [options.exit]
 * @returns {Promise<{ ok: boolean, code?: string, owner?: object, accountRegistry?: object, secretProvider?: object, config?: object }>}
 */
async function bootstrapGateway(options = {}) {
  const stderr = options.stderr || process.stderr;
  const exit = options.exit || process.exit;
  const exitOnError = options.exitOnError === true;

  let configPath = options.configPath;
  if (!configPath) {
    const args = options.args || process.argv.slice(2);
    for (let i = 0; i < args.length; i++) {
      if (args[i] === '--config' && i + 1 < args.length) {
        configPath = args[i + 1];
        break;
      }
    }
  }

  if (!configPath) {
    stderr.write('GATEWAY_CONFIG_ERROR\n');
    if (exitOnError) exit(1);
    return { ok: false, code: 'GATEWAY_CONFIG_ERROR' };
  }

  const repoRoot = options.repoRoot || deriveRepoRoot();
  const validateStartupLocations = options.validateStartupLocations !== undefined ? options.validateStartupLocations : true;
  const configLoader = options.loadConfig || loadDataLocationConfigFromFile;

  let config;
  try {
    config = configLoader(configPath, {
      repoRoot,
      validateStartupLocations,
    });
  } catch {
    stderr.write('GATEWAY_CONFIG_ERROR\n');
    if (exitOnError) exit(1);
    return { ok: false, code: 'GATEWAY_CONFIG_ERROR' };
  }

  // D-TG11-3: Exactly one enabled Telegram account
  try {
    const telegramAccounts = (config && config.accounts && Array.isArray(config.accounts.telegram))
      ? config.accounts.telegram
      : [];

    const enabledAccounts = telegramAccounts.filter((acc) => acc && acc.enabled === true);

    if (enabledAccounts.length !== 1) {
      stderr.write('GATEWAY_CONFIG_ERROR\n');
      if (exitOnError) exit(1);
      return { ok: false, code: 'GATEWAY_CONFIG_ERROR' };
    }

    const soleEnabledAccount = enabledAccounts[0];

    // Construct AccountRegistry with channel domain 'telegram'
    const RegistryClass = options.AccountRegistryClass || AccountRegistry;
    const accountRegistry = new RegistryClass('telegram');

    for (const acc of telegramAccounts) {
      accountRegistry.register(acc);
    }

    accountRegistry.setActive(soleEnabledAccount.id);

    // Wire secret provider
    let secretProvider = options.secretProvider;
    if (!secretProvider) {
      const ProviderClass = resolveSecretProviderClass(options);
      secretProvider = new ProviderClass();
    }

    const stateRoot = config.dataLocations ? config.dataLocations.stateRoot : undefined;

    const ownerDeps = {
      stateRoot,
      config,
      accountRegistry,
      secretProvider,
      ...(options.ownerDeps || {}),
    };

    const RuntimeOwnerClass = options.RuntimeOwnerClass || GatewayRuntimeOwner;
    const owner = options.owner || new RuntimeOwnerClass(ownerDeps);

    if (options.startOwner !== false) {
      try {
        await owner.start();
      } catch {
        stderr.write('GATEWAY_STARTUP_ERROR\n');
        if (exitOnError) exit(1);
        return { ok: false, code: 'GATEWAY_STARTUP_ERROR' };
      }
    }

    return {
      ok: true,
      owner,
      accountRegistry,
      secretProvider,
      config,
    };
  } catch {
    stderr.write('GATEWAY_CONFIG_ERROR\n');
    if (exitOnError) exit(1);
    return { ok: false, code: 'GATEWAY_CONFIG_ERROR' };
  }
}

/**
 * Injectable gateway entry function for testing and backward compatibility.
 *
 * @param {object} [deps={}] Injected dependencies or options for GatewayRuntimeOwner
 * @returns {Promise<GatewayRuntimeOwner>} Started GatewayRuntimeOwner instance
 */
async function runGateway(deps = {}) {
  const owner = deps.owner || new GatewayRuntimeOwner(deps);
  await owner.start();
  return owner;
}

if (require.main === module) {
  bootstrapGateway({ exitOnError: true }).catch(() => {
    process.exit(1);
  });
}

module.exports = {
  runGateway,
  bootstrapGateway,
  deriveRepoRoot,
  resolveSecretProviderClass,
  WindowsCredentialManagerSecretProvider,
};
