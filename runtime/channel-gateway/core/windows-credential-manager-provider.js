/**
 * runtime/channel-gateway/core/windows-credential-manager-provider.js
 *
 * ADR-0026: Concrete Windows Credential Manager Secret Provider.
 *
 * Invariants:
 * - Win32-only concrete provider backed by Windows Credential Manager (CRED_TYPE_GENERIC).
 * - Fails closed with UNSUPPORTED_PLATFORM on any non-win32 platform.
 * - Exact target lookup only (never enumerates credential store).
 * - Zero fallback provider; missing/inaccessible secrets fail closed.
 * - Uses child-process argument array without shell (shell: false).
 * - Private, captured stdio only; secrets never leak to terminal, args, or environment.
 * - Minimal, non-secret environment passed to bridge child process.
 * - Returns secret material strictly as a Buffer; no string conversion, no JSON serialization.
 * - Zero in-memory secret caching inside provider v1 (retrieved on-demand).
 * - Consumer owns Buffer lifecycle and is expected to best-effort zeroize (buf.fill(0)).
 * - Throws stable, non-secret SecretProviderError; never includes raw secret, stdout, or stderr.
 * - Zero npm or native third-party dependencies.
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const child_process = require('node:child_process');
const {
  SecretProvider,
  SecretProviderError,
} = require('./secret-provider');

class WindowsCredentialManagerSecretProvider extends SecretProvider {
  /**
   * @param {object} [options={}]
   * @param {string} [options.platform] - Platform override for testing (defaults to process.platform)
   * @param {string} [options.scriptPath] - Custom bridge script path for testing
   * @param {string} [options.powershellPath] - Custom powershell.exe path for testing
   * @param {function} [options.spawnSync] - Custom spawnSync implementation for testing
   */
  constructor(options = {}) {
    super();
    this.platform = options.platform || process.platform;
    this.spawnSync = options.spawnSync || child_process.spawnSync;

    if (this.platform !== 'win32') {
      throw new SecretProviderError(
        `WindowsCredentialManagerSecretProvider is only supported on win32 platform (current: '${this.platform}')`,
        'UNSUPPORTED_PLATFORM'
      );
    }

    this.scriptPath = options.scriptPath || path.resolve(__dirname, '..', 'bin', 'windows-credential-manager-read.ps1');

    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    this.powershellPath =
      options.powershellPath ||
      path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');

    if (!fs.existsSync(this.scriptPath)) {
      throw new SecretProviderError(
        `Credential Manager bridge script does not exist: '${this.scriptPath}'`,
        'PROVIDER_UNAVAILABLE'
      );
    }

    if (!fs.existsSync(this.powershellPath)) {
      throw new SecretProviderError(
        `PowerShell executable does not exist: '${this.powershellPath}'`,
        'PROVIDER_UNAVAILABLE'
      );
    }
  }

  /**
   * Retrieves secret material for a SecretRef from Windows Credential Manager.
   *
   * @param {import('./secret-provider').SecretRef} secretRef
   * @returns {Buffer} Raw secret buffer
   */
  getSecret(secretRef) {
    if (this.platform !== 'win32') {
      throw new SecretProviderError(
        `WindowsCredentialManagerSecretProvider requires win32 platform (current: '${this.platform}')`,
        'UNSUPPORTED_PLATFORM'
      );
    }

    SecretProvider.validateSecretRef(secretRef);
    const targetName = secretRef.getTargetName();

    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    const childEnv = {
      SystemRoot: systemRoot,
      SystemDrive: process.env.SystemDrive || 'C:',
      PATH: process.env.PATH || `${systemRoot}\\System32;${systemRoot}`,
      PATHEXT: process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC',
      TEMP: process.env.TEMP || `${systemRoot}\\Temp`,
      TMP: process.env.TMP || `${systemRoot}\\Temp`,
    };

    const args = [
      '-NoLogo',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy', 'Bypass',
      '-File', this.scriptPath,
      targetName,
    ];

    let result;
    try {
      result = this.spawnSync(this.powershellPath, args, {
        stdio: ['ignore', 'pipe', 'pipe'],
        env: childEnv,
        windowsHide: true,
        maxBuffer: 1024 * 1024,
      });
    } catch (err) {
      throw new SecretProviderError(
        'Failed to launch Windows Credential Manager bridge',
        'PROVIDER_UNAVAILABLE'
      );
    }

    if (result.error) {
      throw new SecretProviderError(
        'Error executing Windows Credential Manager bridge',
        'PROVIDER_UNAVAILABLE'
      );
    }

    if (result.status === 2) {
      throw new SecretProviderError(
        'Credential target not found in Windows Credential Manager',
        'SECRET_NOT_FOUND'
      );
    }

    if (result.status === 3) {
      throw new SecretProviderError(
        'Access denied accessing Windows Credential Manager target',
        'PROVIDER_ACCESS_DENIED'
      );
    }

    if (result.status !== 0) {
      throw new SecretProviderError(
        `Windows Credential Manager bridge failed with status ${result.status}`,
        'PROVIDER_PROTOCOL_ERROR'
      );
    }

    let payload = result.stdout;
    if (!Buffer.isBuffer(payload)) {
      payload = Buffer.from(payload || '');
    }

    if (payload.length === 0) {
      throw new SecretProviderError(
        'Credential payload is empty in Windows Credential Manager',
        'SECRET_EMPTY'
      );
    }

    return payload;
  }
}

module.exports = {
  WindowsCredentialManagerSecretProvider,
};
