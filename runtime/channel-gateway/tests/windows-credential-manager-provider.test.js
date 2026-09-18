/**
 * runtime/channel-gateway/tests/windows-credential-manager-provider.test.js
 *
 * ADR-0026: Windows Credential Manager Secret Provider Tests.
 * Uses node:test and node:assert only.
 * Covers mock provider tests and live Windows synthetic integration tests.
 * Zero unapproved TAP skips on any platform.
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const child_process = require('node:child_process');
const { SecretRef } = require('../core/secret-provider');
const {
  WindowsCredentialManagerSecretProvider,
} = require('../core/windows-credential-manager-provider');

test('WindowsCredManProvider - A. non-win32 fails UNSUPPORTED_PLATFORM without OS lookup', () => {
  assert.throws(
    () => new WindowsCredentialManagerSecretProvider({ platform: 'linux' }),
    { code: 'UNSUPPORTED_PLATFORM' }
  );

  assert.throws(
    () => new WindowsCredentialManagerSecretProvider({ platform: 'darwin' }),
    { code: 'UNSUPPORTED_PLATFORM' }
  );
});

test('WindowsCredManProvider - B. bridge invocation has shell=false, target exact only, secret absent from args', () => {
  let capturedCmd = null;
  let capturedArgs = null;
  let capturedOptions = null;

  const mockSpawn = (cmd, args, opts) => {
    capturedCmd = cmd;
    capturedArgs = args;
    capturedOptions = opts;
    return {
      status: 0,
      stdout: Buffer.from('mock-secret-payload'),
      stderr: Buffer.from(''),
    };
  };

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath, // Dummy executable path that exists
    scriptPath: __filename, // Dummy script path that exists
    spawnSync: mockSpawn,
  });

  const ref = SecretRef.telegramBotToken('test-bot-account');
  const secret = provider.getSecret(ref);

  assert.strictEqual(Buffer.isBuffer(secret), true);
  assert.strictEqual(secret.toString(), 'mock-secret-payload');

  // Verify command array execution without shell
  assert.strictEqual(capturedOptions.shell, undefined); // Default is false, no shell:true
  assert.strictEqual(capturedOptions.windowsHide, true);

  // Verify args contain exact target and no secret
  assert.strictEqual(capturedArgs.includes('-File'), true);
  assert.strictEqual(capturedArgs.includes('-NoLogo'), true);
  const targetIndex = capturedArgs.indexOf(ref.getTargetName());
  assert.strictEqual(targetIndex !== -1, true);
  assert.strictEqual(
    capturedArgs[targetIndex],
    'HH.AI_v2/channel-gateway/v1/telegram/test-bot-account/bot-token'
  );

  // Verify child environment is scrubbed and does not contain arbitrary secrets
  assert.strictEqual(capturedOptions.env.SECRET_KEY, undefined);
  assert.strictEqual(capturedOptions.env.TOKEN, undefined);
});

test('WindowsCredManProvider - C. provider never requests enumeration', () => {
  let spawnedArgs = [];

  const mockSpawn = (cmd, args, opts) => {
    spawnedArgs = args;
    return { status: 0, stdout: Buffer.from('non-empty-secret'), stderr: Buffer.from('') };
  };

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  provider.getSecret(SecretRef.localApiHmac());

  // Verify args contain no enumeration flags
  const argsString = spawnedArgs.join(' ').toLowerCase();
  assert.strictEqual(argsString.includes('enumerate'), false);
  assert.strictEqual(argsString.includes('list'), false);
  assert.strictEqual(argsString.includes('all'), false);
});

test('WindowsCredManProvider - D. successful bridge output becomes Buffer', () => {
  const mockSpawn = () => ({
    status: 0,
    stdout: Buffer.from([0x01, 0x02, 0x03, 0x04]),
    stderr: Buffer.from(''),
  });

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  const result = provider.getSecret(SecretRef.lineChannelAccessToken('acc1'));
  assert.strictEqual(Buffer.isBuffer(result), true);
  assert.strictEqual(result.length, 4);
  assert.strictEqual(result[0], 0x01);
  assert.strictEqual(result[3], 0x04);
});

test('WindowsCredManProvider - E. empty output fails SECRET_EMPTY', () => {
  const mockSpawn = () => ({
    status: 0,
    stdout: Buffer.alloc(0),
    stderr: Buffer.from(''),
  });

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  assert.throws(
    () => provider.getSecret(SecretRef.lineChannelSecret('acc1')),
    { code: 'SECRET_EMPTY' }
  );
});

test('WindowsCredManProvider - F. missing target maps SECRET_NOT_FOUND', () => {
  const mockSpawn = () => ({
    status: 2, // Exit code 2 maps to ERROR_NOT_FOUND
    stdout: Buffer.alloc(0),
    stderr: Buffer.from(''),
  });

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  assert.throws(
    () => provider.getSecret(SecretRef.telegramBotToken('missing-account')),
    { code: 'SECRET_NOT_FOUND' }
  );
});

test('WindowsCredManProvider - G. access/provider failures map stable errors', () => {
  // Status 3 maps to ACCESS_DENIED
  const accessDeniedProvider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: () => ({ status: 3, stdout: Buffer.alloc(0), stderr: Buffer.from('') }),
  });

  assert.throws(
    () => accessDeniedProvider.getSecret(SecretRef.localApiHmac()),
    { code: 'PROVIDER_ACCESS_DENIED' }
  );

  // Status 1 maps to PROVIDER_PROTOCOL_ERROR
  const genericErrorProvider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: () => ({ status: 1, stdout: Buffer.alloc(0), stderr: Buffer.from('') }),
  });

  assert.throws(
    () => genericErrorProvider.getSecret(SecretRef.localApiHmac()),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );

  // Spawn error maps to PROVIDER_UNAVAILABLE
  const unavailableProvider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: () => ({ error: new Error('spawn ENOENT') }),
  });

  assert.throws(
    () => unavailableProvider.getSecret(SecretRef.localApiHmac()),
    { code: 'PROVIDER_UNAVAILABLE' }
  );
});

test('WindowsCredManProvider - H. raw secret never appears in thrown error', () => {
  const sensitiveToken = 'SUPER_SECRET_TOKEN_DO_NOT_LEAK';
  const mockSpawn = () => {
    const err = new Error(`Failure: ${sensitiveToken}`);
    return { error: err, status: -1 };
  };

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  try {
    provider.getSecret(SecretRef.telegramBotToken('acc1'));
    assert.fail('Should have thrown');
  } catch (err) {
    assert.strictEqual(err.code, 'PROVIDER_UNAVAILABLE');
    // Error message must not contain secret values
    assert.strictEqual(err.message.includes(sensitiveToken), false);
  }
});

test('WindowsCredManProvider - I. raw stdout/stderr never incorporated into error', () => {
  const secretStderr = 'sensitive stderr info';
  const secretStdout = 'sensitive stdout info';

  const mockSpawn = () => ({
    status: 1,
    stdout: Buffer.from(secretStdout),
    stderr: Buffer.from(secretStderr),
  });

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  try {
    provider.getSecret(SecretRef.localApiHmac());
    assert.fail('Should have thrown');
  } catch (err) {
    assert.strictEqual(err.code, 'PROVIDER_PROTOCOL_ERROR');
    assert.strictEqual(err.message.includes(secretStderr), false);
    assert.strictEqual(err.message.includes(secretStdout), false);
  }
});

test('WindowsCredManProvider - J. Windows live synthetic CredMan integration', () => {
  if (process.platform !== 'win32') {
    // On non-Windows, assert that real provider cannot be initialized without platform error
    assert.throws(
      () => new WindowsCredentialManagerSecretProvider(),
      { code: 'UNSUPPORTED_PLATFORM' }
    );
    return;
  }

  // Windows live synthetic Credential Manager test
  const uniqueAccountId = 'syn-acc-' + Date.now() + '-' + Math.floor(Math.random() * 10000);
  const secretRef = SecretRef.telegramBotToken(uniqueAccountId);
  const targetName = secretRef.getTargetName();

  const syntheticSecretText = 'SyntheticPayload_' + Math.random().toString(36).slice(2);
  const syntheticBytes = Buffer.from(syntheticSecretText, 'utf8');

  const runEncodedPs = (script) => {
    const b64 = Buffer.from(script, 'utf16le').toString('base64');
    return child_process.spawnSync('powershell.exe', [
      '-NoLogo',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy', 'Bypass',
      '-EncodedCommand', b64
    ], { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8' });
  };

  const writeScript = `
$sig = @'
using System;
using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct CREDENTIAL {
    public uint Flags;
    public uint Type;
    public string TargetName;
    public string Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
    public uint CredentialBlobSize;
    public IntPtr CredentialBlob;
    public uint Persist;
    public uint AttributeCount;
    public IntPtr Attributes;
    public string TargetAlias;
    public string UserName;
}
public class WinCredLiveHelper {
    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredWrite([In] ref CREDENTIAL userCred, uint flags);
    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredDelete(string target, uint type, uint flags);
}
'@
if (-not ([System.Management.Automation.PSTypeName]'WinCredLiveHelper').Type) {
    Add-Type -TypeDefinition $sig
}

$target = '${targetName}'
$bytes = [System.Text.Encoding]::UTF8.GetBytes('${syntheticSecretText}')
$h = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($bytes.Length)
[System.Runtime.InteropServices.Marshal]::Copy($bytes, 0, $h, $bytes.Length)

$c = New-Object CREDENTIAL
$c.Type = 1 # CRED_TYPE_GENERIC
$c.TargetName = $target
$c.CredentialBlob = $h
$c.CredentialBlobSize = $bytes.Length
$c.Persist = 2 # CRED_PERSIST_LOCAL_MACHINE
$c.UserName = "HHAI_SyntheticTest"

$ok = [WinCredLiveHelper]::CredWrite([ref]$c, 0)
[System.Runtime.InteropServices.Marshal]::FreeHGlobal($h)
if ($ok) { exit 0 } else { exit 1 }
`;

  const deleteScript = `
$sig = @'
using System;
using System.Runtime.InteropServices;
public class WinCredLiveDelHelper {
    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredDelete(string target, uint type, uint flags);
}
'@
if (-not ([System.Management.Automation.PSTypeName]'WinCredLiveDelHelper').Type) {
    Add-Type -TypeDefinition $sig
}
$ok = [WinCredLiveDelHelper]::CredDelete('${targetName}', 1, 0)
if ($ok) { exit 0 } else { exit 1 }
`;

  // 1. Write synthetic credential
  const writeRes = runEncodedPs(writeScript);
  assert.strictEqual(writeRes.status, 0, 'Synthetic credential write should succeed');

  let retrieved = null;
  try {
    // 2. Read through actual provider
    const realProvider = new WindowsCredentialManagerSecretProvider();
    retrieved = realProvider.getSecret(secretRef);

    // 3. Assert bytes equal in memory
    assert.strictEqual(Buffer.isBuffer(retrieved), true);
    assert.strictEqual(retrieved.equals(syntheticBytes), true);
  } finally {
    // 4. Best-effort zeroization of retrieved buffer
    if (retrieved && Buffer.isBuffer(retrieved)) {
      retrieved.fill(0);
    }

    // 5. Clean up synthetic credential
    const delRes = runEncodedPs(deleteScript);
    assert.strictEqual(delRes.status, 0, 'Synthetic credential cleanup should succeed');
  }

  // 6. Verify missing target fails closed after deletion
  const realProvider = new WindowsCredentialManagerSecretProvider();
  assert.throws(
    () => realProvider.getSecret(secretRef),
    { code: 'SECRET_NOT_FOUND' }
  );
});
