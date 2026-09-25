#!/usr/bin/env node
/**
 * runtime/channel-gateway/bin/gateway.js
 *
 * TG-MVP-11: Channel Gateway Foreground Bootstrap.
 *
 * Responsibilities:
 * - Foreground bootstrap entry point only.
 * - Safe to require() from a unit test: importing the module has ZERO side effects.
 * - Production execution occurs strictly when `require.main === module`.
 * - Tests invoke `runGateway(deps)` with injected dependencies.
 */

'use strict';

const { GatewayRuntimeOwner } = require('../core/gateway-runtime-owner');

/**
 * Injectable gateway entry function for testing and production bootstrap.
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
  const { loadDataLocationConfigFromFile } = require('../core/local-config-loader');
  const { WindowsCredentialManagerProvider } = require('../core/windows-credential-manager-provider');
  const { AccountRegistry } = require('../core/account-registry');

  let configPath = null;
  const args = process.argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--config' && i + 1 < args.length) {
      configPath = args[i + 1];
      break;
    }
  }

  if (!configPath) {
    console.error('Usage: node runtime/channel-gateway/bin/gateway.js --config <path-to-config.json>');
    process.exit(1);
  }

  try {
    const config = loadDataLocationConfigFromFile(configPath);
    const secretProvider = new WindowsCredentialManagerProvider();
    const accountRegistry = new AccountRegistry();
    if (Array.isArray(config.accounts)) {
      for (const acc of config.accounts) {
        accountRegistry.registerAccount(acc);
      }
    }
    const stateRoot = config.dataLocations.stateRoot;

    runGateway({
      stateRoot,
      config,
      accountRegistry,
      secretProvider,
    }).catch((err) => {
      console.error('[gateway] Fatal startup error:', err && err.message ? err.message : err);
      process.exit(1);
    });
  } catch (err) {
    console.error('[gateway] Configuration or initialization error:', err && err.message ? err.message : err);
    process.exit(1);
  }
}

module.exports = {
  runGateway,
};
