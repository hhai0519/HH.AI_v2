/**
 * runtime/channel-gateway/core/windows-credential-manager-access.js
 *
 * SEC-02 INC-2: Guarded Windows Credential Manager Access Primitives.
 *
 * Invariants:
 * - Win32-only access wrapper backed by Windows Credential Manager.
 * - Fails closed with UNSUPPORTED_PLATFORM on any non-win32 platform.
 * - Exported methods: isPresent(ref), createNew(ref, utf16leBlob), deleteExact(ref).
 * - Zero credential read / retrieve method in this interface.
 * - Zero credential enumeration.
 * - Uses child-process argument array without shell (shell: false).
 * - Minimal, non-secret environment passed to bridge child process (6 keys).
 * - Binary stdin only for secret delivery in createNew; EOF closed immediately.
 * - Borrowed caller Buffer is never mutated; private copies zeroized in finally.
 * - Strict token wire protocol (PRESENT, ABSENT, CREATED, DELETED); exit 0 stderr must be empty.
 * - Errors never contain secrets, lengths, hashes, paths, or child stdout/stderr.
 * - Timeout bounded to 60000ms with zero retry.
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const child_process = require('node:child_process');
const {
  resolveManagedTarget,
  CredentialManagerError,
} = require('./managed-credential-target');
const { decodeCredentialBlobUtf16le } = require('./windows-credential-manager-provider');

const DEFAULT_TIMEOUT_MS = 60000;
const MAX_TIMEOUT_MS = 60000;
const MAX_BLOB_SIZE = 2560;

/**
 * Validates a token string from stdout against allowed tokens.
 * Only exact token with optional single LF or CRLF is accepted.
 * No trimming, no whitespace tolerance.
 *
 * @param {Buffer} stdoutBuf
 * @param {string[]} validTokens
 * @returns {string|null}
 */
function matchProtocolToken(stdoutBuf, validTokens) {
  if (!Buffer.isBuffer(stdoutBuf) || stdoutBuf.length === 0) {
    return null;
  }
  const str = stdoutBuf.toString('utf8');
  for (const token of validTokens) {
    if (str === token || str === `${token}\n` || str === `${token}\r\n`) {
      return token;
    }
  }
  return null;
}

class WindowsCredentialManagerAccess {
  /**
   * @param {object} [options={}]
   * @param {string} [options.platform] - Platform override for testing
   * @param {string} [options.scriptPath] - Custom bridge script path for testing
   * @param {string} [options.powershellPath] - Custom powershell.exe path for testing
   * @param {function} [options.spawnSync] - Custom spawnSync implementation for testing
   * @param {number} [options.timeoutMs] - Bounded timeout in milliseconds
   */
  constructor(options = {}) {
    this.platform = options.platform || process.platform;
    this.spawnSync = options.spawnSync || child_process.spawnSync;

    if (options.timeoutMs !== undefined) {
      if (
        typeof options.timeoutMs !== 'number' ||
        !Number.isInteger(options.timeoutMs) ||
        options.timeoutMs <= 0 ||
        options.timeoutMs > MAX_TIMEOUT_MS
      ) {
        throw new CredentialManagerError(
          'Invalid timeoutMs: must be a positive integer <= 60000',
          'PROVIDER_PROTOCOL_ERROR'
        );
      }
      this.timeoutMs = options.timeoutMs;
    } else {
      this.timeoutMs = DEFAULT_TIMEOUT_MS;
    }

    if (this.platform !== 'win32') {
      throw new CredentialManagerError(
        'WindowsCredentialManagerAccess is only supported on win32 platform',
        'UNSUPPORTED_PLATFORM'
      );
    }

    this.scriptPath =
      options.scriptPath ||
      path.resolve(__dirname, '..', 'bin', 'windows-credential-manager-access.ps1');

    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    this.powershellPath =
      options.powershellPath ||
      path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');

    if (!fs.existsSync(this.scriptPath)) {
      throw new CredentialManagerError(
        'Credential bridge script does not exist',
        'PROVIDER_UNAVAILABLE'
      );
    }

    if (!fs.existsSync(this.powershellPath)) {
      throw new CredentialManagerError(
        'PowerShell executable does not exist',
        'PROVIDER_UNAVAILABLE'
      );
    }
  }

  /**
   * Executes the native bridge child process with strict environment and arguments.
   *
   * @private
   * @param {string} operation - 'presence', 'create', 'delete'
   * @param {string} targetName - Canonical TargetName
   * @param {Buffer} [inputBlob] - Optional stdin blob for create operation
   * @returns {{ status: number, stdout: Buffer, stderr: Buffer }}
   */
  _executeBridge(operation, targetName, inputBlob) {
    if (this.platform !== 'win32') {
      throw new CredentialManagerError(
        'WindowsCredentialManagerAccess requires win32 platform',
        'UNSUPPORTED_PLATFORM'
      );
    }

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
      '-Operation', operation,
      '-TargetName', targetName,
    ];

    const spawnOptions = {
      env: childEnv,
      windowsHide: true,
      maxBuffer: 1024 * 1024,
      timeout: this.timeoutMs,
      shell: false,
    };

    if (inputBlob) {
      spawnOptions.input = inputBlob;
      spawnOptions.stdio = ['pipe', 'pipe', 'pipe'];
    } else {
      spawnOptions.stdio = ['ignore', 'pipe', 'pipe'];
    }

    let result;
    try {
      result = this.spawnSync(this.powershellPath, args, spawnOptions);
    } catch (err) {
      throw new CredentialManagerError(
        'Failed to execute Windows Credential Manager bridge',
        'PROVIDER_UNAVAILABLE'
      );
    }

    if (!result) {
      throw new CredentialManagerError(
        'Windows Credential Manager bridge returned no result',
        'PROVIDER_UNAVAILABLE'
      );
    }

    if (result.error) {
      if (result.error.code === 'ETIMEDOUT') {
        throw new CredentialManagerError(
          'Windows Credential Manager access timed out',
          'PROVIDER_UNAVAILABLE'
        );
      }
      throw new CredentialManagerError(
        'Error executing Windows Credential Manager bridge',
        'PROVIDER_UNAVAILABLE'
      );
    }

    if (result.signal) {
      throw new CredentialManagerError(
        'Windows Credential Manager bridge terminated by signal',
        'PROVIDER_PROTOCOL_ERROR'
      );
    }

    return result;
  }

  /**
   * Checks whether a managed credential target is present in Windows Credential Manager.
   *
   * @param {object} ref - Managed credential reference
   * @returns {boolean} true if present, false if absent
   */
  isPresent(ref) {
    const targetName = resolveManagedTarget(ref);
    const result = this._executeBridge('presence', targetName);

    if (result.status === 0) {
      if (!Buffer.isBuffer(result.stdout) || !Buffer.isBuffer(result.stderr) || result.stderr.length !== 0) {
        throw new CredentialManagerError(
          'Windows Credential Manager bridge produced unexpected error output',
          'PROVIDER_PROTOCOL_ERROR'
        );
      }
      const token = matchProtocolToken(result.stdout, ['PRESENT', 'ABSENT']);
      if (token === 'PRESENT') {
        return true;
      }
      if (token === 'ABSENT') {
        return false;
      }
      throw new CredentialManagerError(
        'Windows Credential Manager bridge returned invalid protocol token',
        'PROVIDER_PROTOCOL_ERROR'
      );
    }

    this._handleErrorStatus(result.status);
  }

  /**
   * Creates a new credential in Windows Credential Manager.
   * Fails if the credential already exists.
   *
   * @param {object} ref - Managed credential reference
   * @param {Buffer} utf16leBlob - Borrowed UTF-16LE buffer
   * @returns {true} Returns true on success
   */
  createNew(ref, utf16leBlob) {
    const targetName = resolveManagedTarget(ref);

    if (!Buffer.isBuffer(utf16leBlob) || utf16leBlob.length === 0 || utf16leBlob.length % 2 !== 0) {
      throw new CredentialManagerError(
        'Invalid credential blob encoding',
        'SECRET_ENCODING_INVALID'
      );
    }

    if (utf16leBlob.length > MAX_BLOB_SIZE) {
      throw new CredentialManagerError(
        'Credential blob exceeds maximum allowable size',
        'SECRET_ENCODING_INVALID'
      );
    }

    const privateCopy = Buffer.alloc(utf16leBlob.length);
    let verifiedUtf8 = null;
    try {
      utf16leBlob.copy(privateCopy);
      const firstCodeUnit = privateCopy.readUInt16LE(0);
      if (firstCodeUnit === 0xFEFF || firstCodeUnit === 0xFFFE) {
        throw new CredentialManagerError(
          'Invalid credential blob encoding',
          'SECRET_ENCODING_INVALID'
        );
      }

      try {
        verifiedUtf8 = decodeCredentialBlobUtf16le(privateCopy);
      } catch (err) {
        throw new CredentialManagerError(
          'Invalid credential blob encoding',
          'SECRET_ENCODING_INVALID'
        );
      }

      const result = this._executeBridge('create', targetName, privateCopy);

      if (result.status === 0) {
        if (!Buffer.isBuffer(result.stdout) || !Buffer.isBuffer(result.stderr) || result.stderr.length !== 0) {
          throw new CredentialManagerError(
            'Windows Credential Manager bridge produced unexpected error output',
            'PROVIDER_PROTOCOL_ERROR'
          );
        }
        const token = matchProtocolToken(result.stdout, ['CREATED']);
        if (token === 'CREATED') {
          return true;
        }
        throw new CredentialManagerError(
          'Windows Credential Manager bridge returned invalid protocol token',
          'PROVIDER_PROTOCOL_ERROR'
        );
      }

      this._handleErrorStatus(result.status);
    } finally {
      // Independent owners: a failure while clearing one buffer must not skip the other.
      try {
        if (verifiedUtf8) {
          verifiedUtf8.fill(0);
        }
      } finally {
        privateCopy.fill(0);
      }
    }
  }

  /**
   * Deletes a credential target from Windows Credential Manager.
   *
   * @param {object} ref - Managed credential reference
   * @returns {boolean} true if deleted, false if already absent
   */
  deleteExact(ref) {
    const targetName = resolveManagedTarget(ref);
    const result = this._executeBridge('delete', targetName);

    if (result.status === 0) {
      if (!Buffer.isBuffer(result.stdout) || !Buffer.isBuffer(result.stderr) || result.stderr.length !== 0) {
        throw new CredentialManagerError(
          'Windows Credential Manager bridge produced unexpected error output',
          'PROVIDER_PROTOCOL_ERROR'
        );
      }
      const token = matchProtocolToken(result.stdout, ['DELETED', 'ABSENT']);
      if (token === 'DELETED') {
        return true;
      }
      if (token === 'ABSENT') {
        return false;
      }
      throw new CredentialManagerError(
        'Windows Credential Manager bridge returned invalid protocol token',
        'PROVIDER_PROTOCOL_ERROR'
      );
    }

    this._handleErrorStatus(result.status);
  }

  /**
   * Maps non-zero child process status to stable CredentialManagerError.
   *
   * @private
   * @param {number} status
   */
  _handleErrorStatus(status) {
    if (status === 3) {
      throw new CredentialManagerError(
        'Access denied accessing Windows Credential Manager target',
        'PROVIDER_ACCESS_DENIED'
      );
    }
    if (status === 4) {
      throw new CredentialManagerError(
        'Credential already exists in Windows Credential Manager',
        'CREDENTIAL_ALREADY_EXISTS'
      );
    }
    if (status === 5) {
      throw new CredentialManagerError(
        'Credential target is currently busy',
        'CREDENTIAL_BUSY'
      );
    }
    if (status === 6) {
      throw new CredentialManagerError(
        'Invalid credential encoding',
        'SECRET_ENCODING_INVALID'
      );
    }
    if (status === 1) {
      throw new CredentialManagerError(
        'Windows Credential Manager provider is unavailable',
        'PROVIDER_UNAVAILABLE'
      );
    }
    throw new CredentialManagerError(
      'Windows Credential Manager bridge failed with an unexpected status',
      'PROVIDER_PROTOCOL_ERROR'
    );
  }
}

module.exports = {
  WindowsCredentialManagerAccess,
  CredentialManagerError,
  DEFAULT_TIMEOUT_MS,
  MAX_TIMEOUT_MS,
  MAX_BLOB_SIZE,
};
