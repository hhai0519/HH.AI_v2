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
const fs = require('node:fs');
const path = require('node:path');
const child_process = require('node:child_process');
const { SecretRef, SecretProviderError } = require('../core/secret-provider');
const {
  WindowsCredentialManagerSecretProvider,
  decodeCredentialBlobUtf16le,
  DEFAULT_TIMEOUT_MS,
} = require('../core/windows-credential-manager-provider');

// Native PowerShell runs (B-107, runtime/channel-gateway/AGENTS.md F2-A): every direct run goes through
// runNativeBridge, whose effective spawnSync timeout is locked to the production DEFAULT_TIMEOUT_MS and
// cannot be overridden by callers. The guard test below and scripts/tests/test_channel_gateway_core.py
// enforce this.
const NATIVE_SPAWN_TIMEOUT_MS = DEFAULT_TIMEOUT_MS;

function nativeSpawnOptions(extra) {
  return Object.assign({}, extra, { timeout: NATIVE_SPAWN_TIMEOUT_MS, windowsHide: true });
}

function runNativeBridge(file, args, extra) {
  return child_process.spawnSync(file, args, nativeSpawnOptions(extra));
}

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
      stdout: Buffer.from('mock-secret-payload', 'utf16le'),
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
  assert.strictEqual(capturedOptions.timeout, 60000); // Bounded timeout configured (F1-B / F2-A)

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
    return { status: 0, stdout: Buffer.from('non-empty-secret', 'utf16le'), stderr: Buffer.from('') };
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
    stdout: Buffer.from([0x01, 0x00, 0x02, 0x00, 0x03, 0x00, 0x04, 0x00]),
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

  const syntheticSecretText = 'SyntheticPayload_ASCII_é_中_😀_' + Math.random().toString(36).slice(2);
  const syntheticBytes = Buffer.from(syntheticSecretText, 'utf8');

  const runEncodedPs = (script) => {
    const b64 = Buffer.from(script, 'utf16le').toString('base64');
    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    const powershellPath = path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    return runNativeBridge(powershellPath, [
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
$bytes = [System.Text.Encoding]::Unicode.GetBytes('${syntheticSecretText}')
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
  const writeStart = process.hrtime.bigint();
  let writeRes;
  try {
    writeRes = runEncodedPs(writeScript);
  } finally {
    const elapsedMs = Number((process.hrtime.bigint() - writeStart) / 1000000n);
    console.log(`CREDM_SYN_WRITE_MS=${elapsedMs}`);
  }
  assert.strictEqual(writeRes.status, 0, `Synthetic credential write should succeed: ${writeRes.stderr}`);

  let retrieved = null;
  try {
    // 2. Read through actual provider with production default constructor (F2-A parity)
    const readExistingStart = process.hrtime.bigint();
    try {
      const realProvider = new WindowsCredentialManagerSecretProvider();
      assert.strictEqual(realProvider.timeoutMs, 60000, 'Live provider must use production DEFAULT_TIMEOUT_MS');
      retrieved = realProvider.getSecret(secretRef);
    } finally {
      const elapsedMs = Number((process.hrtime.bigint() - readExistingStart) / 1000000n);
      console.log(`CREDM_PROV_READ_EXISTING_MS=${elapsedMs}`);
    }

    // 3. Assert bytes equal in memory
    assert.strictEqual(Buffer.isBuffer(retrieved), true);
    assert.strictEqual(retrieved.equals(syntheticBytes), true);
    retrieved.fill(0);
    retrieved = null;
  } finally {
    // 4. Best-effort zeroization of retrieved buffer
    if (retrieved && Buffer.isBuffer(retrieved)) {
      retrieved.fill(0);
    }

    // 5. Clean up synthetic credential
    const delStart = process.hrtime.bigint();
    let delRes;
    try {
      delRes = runEncodedPs(deleteScript);
    } finally {
      const elapsedMs = Number((process.hrtime.bigint() - delStart) / 1000000n);
      console.log(`CREDM_SYN_DEL_MS=${elapsedMs}`);
    }
    assert.strictEqual(delRes.status, 0, `Synthetic credential cleanup should succeed: ${delRes.stderr}`);
  }

  // 7. Verify missing target fails closed after deletion using production default provider (F2-A parity)
  const readMissingStart = process.hrtime.bigint();
  try {
    const missingProvider = new WindowsCredentialManagerSecretProvider();
    assert.strictEqual(missingProvider.timeoutMs, 60000, 'Post-delete provider must use production DEFAULT_TIMEOUT_MS');
    assert.throws(
      () => missingProvider.getSecret(secretRef),
      { code: 'SECRET_NOT_FOUND' }
    );
  } finally {
    const elapsedMs = Number((process.hrtime.bigint() - readMissingStart) / 1000000n);
    console.log(`CREDM_PROV_READ_MISSING_MS=${elapsedMs}`);
  }
});

test('WindowsCredManProvider - K. spawn options contain bounded timeout and custom timeoutMs (F1-B)', () => {
  let capturedOptions = null;
  const mockSpawn = (cmd, args, opts) => {
    capturedOptions = opts;
    return { status: 0, stdout: Buffer.from('data', 'utf16le'), stderr: Buffer.from('') };
  };

  // 1. Default timeout
  const defaultProvider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });
  defaultProvider.getSecret(SecretRef.localApiHmac());
  assert.strictEqual(capturedOptions.timeout, 60000);

  // 2. Custom valid timeoutMs
  const customProvider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
    timeoutMs: 5000,
  });
  customProvider.getSecret(SecretRef.localApiHmac());
  assert.strictEqual(capturedOptions.timeout, 5000);

  // 3. Invalid timeoutMs values fail closed
  assert.throws(
    () => new WindowsCredentialManagerSecretProvider({ platform: 'win32', timeoutMs: 0 }),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => new WindowsCredentialManagerSecretProvider({ platform: 'win32', timeoutMs: -100 }),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => new WindowsCredentialManagerSecretProvider({ platform: 'win32', timeoutMs: 100000 }),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
  assert.throws(
    () => new WindowsCredentialManagerSecretProvider({ platform: 'win32', timeoutMs: '10000' }),
    { code: 'PROVIDER_PROTOCOL_ERROR' }
  );
});

test('WindowsCredManProvider - L. synthetic timeout error ETIMEDOUT maps to stable PROVIDER_UNAVAILABLE (F1-B)', () => {
  const mockSpawn = () => {
    const err = new Error('timed out after 10000ms');
    err.code = 'ETIMEDOUT';
    return { error: err, status: null, signal: 'SIGTERM' };
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
    assert.strictEqual(err.message.includes('timed out'), true);
    // Never leaks raw error stack or internal child details
    assert.strictEqual(err.message.includes('SIGTERM'), false);
    assert.strictEqual(err.message.includes('Error: timed out'), false);
  }
});

test('WindowsCredManProvider - M. subclass getTargetName override and mutation cannot redirect lookup (F1-C)', () => {
  let spawned = false;
  const mockSpawn = () => {
    spawned = true;
    return { status: 0, stdout: Buffer.from('data', 'utf16le'), stderr: Buffer.from('') };
  };

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  class SubclassSecretRef extends SecretRef {
    getTargetName() {
      return 'HH.AI_v2/channel-gateway/v1/telegram/injected-account/bot-token';
    }
  }

  const subRef = new SubclassSecretRef({
    channel: 'telegram',
    purpose: 'telegram-bot-token',
    accountId: 'orig-account',
  });

  assert.throws(
    () => provider.getSecret(subRef),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.strictEqual(spawned, false, 'spawnSync must not be called when subclass is passed');
});

test('WindowsCredManProvider - N. invalid canonical target fails closed before child spawn (F1-C)', () => {
  let spawned = false;
  const mockSpawn = () => {
    spawned = true;
    return { status: 0, stdout: Buffer.from('data', 'utf16le'), stderr: Buffer.from('') };
  };

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  assert.throws(
    () => provider.getSecret(null),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.throws(
    () => provider.getSecret({ channel: 'telegram', purpose: 'telegram-bot-token', accountId: 'acc' }),
    { code: 'INVALID_SECRET_REFERENCE' }
  );
  assert.strictEqual(spawned, false);
});

test('WindowsCredManProvider - O. PowerShell bridge structural assertion guards single ownership and cleanup (F1-A / F1-H1)', () => {
  const scriptPath = path.resolve(__dirname, '..', 'bin', 'windows-credential-manager-read.ps1');
  assert.strictEqual(fs.existsSync(scriptPath), true);
  const content = fs.readFileSync(scriptPath, 'utf8');

  // Guard 1: CredFree appears exactly once in the script (inside finally)
  const credFreeMatches = content.match(/\[WinCredBridge\]::CredFree/g) || [];
  assert.strictEqual(credFreeMatches.length, 1, 'CredFree must have exactly one ownership/free site');

  // Guard 2: Pointer is zeroed in finally
  assert.strictEqual(content.includes('$pCred = [IntPtr]::Zero'), true);

  // Guard 3: Managed array is cleared via [Array]::Clear in finally
  assert.strictEqual(content.includes('[Array]::Clear($blob, 0, $blob.Length)'), true);

  // Guard 4: Canonical target regex pattern is present
  assert.strictEqual(content.includes('$canonicalTargetPattern'), true);
});

test('WindowsCredManProvider - P. post-acquire stdout failure counterexample avoids double-free (F1-A / §22)', () => {
  if (process.platform !== 'win32') {
    return;
  }

  const uniqueAccountId = 'syn-fault-' + Date.now() + '-' + Math.floor(Math.random() * 10000);
  const secretRef = SecretRef.telegramBotToken(uniqueAccountId);
  const targetName = secretRef.getTargetName();
  const syntheticSecretText = 'FaultTestPayload_' + Math.random().toString(36).slice(2);

  const runEncodedPs = (script) => {
    const b64 = Buffer.from(script, 'utf16le').toString('base64');
    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    const powershellPath = path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    return runNativeBridge(powershellPath, [
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
public class WinCredFaultHelper {
    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredWrite([In] ref CREDENTIAL userCred, uint flags);
    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredDelete(string target, uint type, uint flags);
}
'@
if (-not ([System.Management.Automation.PSTypeName]'WinCredFaultHelper').Type) {
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
$c.UserName = "HHAI_FaultTest"

$ok = [WinCredFaultHelper]::CredWrite([ref]$c, 0)
[System.Runtime.InteropServices.Marshal]::FreeHGlobal($h)
if ($ok) { exit 0 } else { exit 1 }
`;

  const deleteScript = `
$sig = @'
using System;
using System.Runtime.InteropServices;
public class WinCredFaultDelHelper {
    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredDelete(string target, uint type, uint flags);
}
'@
if (-not ([System.Management.Automation.PSTypeName]'WinCredFaultDelHelper').Type) {
    Add-Type -TypeDefinition $sig
}
$ok = [WinCredFaultDelHelper]::CredDelete('${targetName}', 1, 0)
if ($ok) { exit 0 } else { exit 1 }
`;

  // 1. Write synthetic credential
  const writeRes = runEncodedPs(writeScript);
  assert.strictEqual(writeRes.status, 0, `Synthetic credential write should succeed: ${writeRes.stderr}`);

  try {
    // 2. Invoke bridge script with -TestFaultStage stdout
    const systemRoot = process.env.SystemRoot || 'C:\\Windows';
    const powershellPath = path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    const scriptPath = path.resolve(__dirname, '..', 'bin', 'windows-credential-manager-read.ps1');
    const faultRes = runNativeBridge(powershellPath, [
      '-NoLogo',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy', 'Bypass',
      '-File', scriptPath,
      targetName,
      '-TestFaultStage', 'stdout',
    ], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    // 3. Assert fail-closed exit code 1
    assert.strictEqual(faultRes.status, 1, `Bridge with fault seam must exit code 1 (status=${faultRes.status}, err=${faultRes.error}, stderr=${faultRes.stderr})`);
    // 4. Assert process did not crash with native double-free / AV code (e.g. 0xC0000005, 0xC0000374)
    assert.strictEqual(faultRes.signal, null, 'Process must terminate normally without crash signal');
    // 5. Assert zero secret bytes emitted to stdout or stderr
    assert.strictEqual(faultRes.stdout.length, 0, 'Stdout must be empty on failure');
    const stderrStr = (faultRes.stderr || Buffer.alloc(0)).toString('utf8');
    assert.strictEqual(stderrStr.includes(syntheticSecretText), false, 'Stderr must never leak secret bytes');
  } finally {
    // 6. Clean up synthetic credential
    const delRes = runEncodedPs(deleteScript);
    assert.strictEqual(delRes.status, 0, `Synthetic credential cleanup should succeed: ${delRes.stderr}`);
  }
});

test('WindowsCredManProvider - Q. PowerShell 5.1 Reflection.Emit type-load smoke', () => {
  if (process.platform !== 'win32') {
    return;
  }

  const scriptPath = path.resolve(__dirname, '..', 'bin', 'windows-credential-manager-read.ps1');
  assert.strictEqual(fs.existsSync(scriptPath), true, 'Production bridge script must exist');
  const content = fs.readFileSync(scriptPath, 'utf8');

  // 2. Fail-closed find production literal CredRead invocation boundary
  const marker = '[WinCredBridge]::CredRead';
  const matches = [...content.matchAll(/\[WinCredBridge\]::CredRead/g)];
  assert.strictEqual(matches.length, 1, 'Literal CredRead boundary must be uniquely determinable');
  const boundaryIdx = matches[0].index;

  // 3. Slicing strictly before CredRead line
  const lastNewlineBefore = content.lastIndexOf('\n', boundaryIdx);
  assert.strictEqual(lastNewlineBefore !== -1, true, 'Newline before CredRead boundary must exist');
  const prefix = content.slice(0, lastNewlineBefore);

  // 4. Reflection metadata assertions
  const assertScript = `
# Assertions on CREDENTIAL
$cred = [CREDENTIAL]
if (-not $cred.IsValueType) { exit 101 }
if (-not $cred.IsLayoutSequential) { exit 102 }

$expectedFields = @(
    @('Flags', 'UInt32'),
    @('Type', 'UInt32'),
    @('TargetName', 'IntPtr'),
    @('Comment', 'IntPtr'),
    @('LastWrittenLowDateTime', 'UInt32'),
    @('LastWrittenHighDateTime', 'UInt32'),
    @('CredentialBlobSize', 'UInt32'),
    @('CredentialBlob', 'IntPtr'),
    @('Persist', 'UInt32'),
    @('AttributeCount', 'UInt32'),
    @('Attributes', 'IntPtr'),
    @('TargetAlias', 'IntPtr'),
    @('UserName', 'IntPtr')
)
$actualFields = $cred.GetFields([System.Reflection.BindingFlags]'Public, Instance')
if ($actualFields.Length -ne $expectedFields.Length) { exit 103 }
for ($i = 0; $i -lt $expectedFields.Length; $i++) {
    if ($actualFields[$i].Name -ne $expectedFields[$i][0] -or $actualFields[$i].FieldType.Name -ne $expectedFields[$i][1]) {
        exit (110 + $i)
    }
}

# Assertions on WinCredBridge
$bridge = [WinCredBridge]
$readM = $bridge.GetMethod('CredRead', [System.Reflection.BindingFlags]'Public, Static')
if ($null -eq $readM -or $readM.ReturnType.Name -ne 'Boolean') { exit 201 }
$readParams = $readM.GetParameters()
if ($readParams.Length -ne 4) { exit 202 }
if ($readParams[0].ParameterType.Name -ne 'String' -or
    $readParams[1].ParameterType.Name -ne 'UInt32' -or
    $readParams[2].ParameterType.Name -ne 'UInt32' -or
    $readParams[3].ParameterType.Name -ne 'IntPtr&') { exit 203 }

$readAttrs = $readM.GetCustomAttributes([System.Runtime.InteropServices.DllImportAttribute], $false)
if ($readAttrs.Length -ne 1) { exit 204 }
$ra = $readAttrs[0]
if ($ra.Value -ne 'advapi32.dll' -or
    $ra.EntryPoint -ne 'CredReadW' -or
    $ra.SetLastError -ne $true -or
    $ra.CharSet -ne [System.Runtime.InteropServices.CharSet]::Unicode -or
    $ra.CallingConvention -ne [System.Runtime.InteropServices.CallingConvention]::Winapi -or
    $ra.PreserveSig -ne $true) { exit 205 }

$freeM = $bridge.GetMethod('CredFree', [System.Reflection.BindingFlags]'Public, Static')
if ($null -eq $freeM -or $freeM.ReturnType.Name -ne 'Void') { exit 301 }
$freeParams = $freeM.GetParameters()
if ($freeParams.Length -ne 1 -or $freeParams[0].ParameterType.Name -ne 'IntPtr') { exit 302 }

$freeAttrs = $freeM.GetCustomAttributes([System.Runtime.InteropServices.DllImportAttribute], $false)
if ($freeAttrs.Length -ne 1) { exit 303 }
$fa = $freeAttrs[0]
if ($fa.Value -ne 'advapi32.dll' -or
    $fa.EntryPoint -ne 'CredFree' -or
    $fa.CallingConvention -ne [System.Runtime.InteropServices.CallingConvention]::Winapi -or
    $fa.PreserveSig -ne $true) { exit 304 }

exit 0
`;

  const combinedScript = `& {
${prefix}

${assertScript}
} 'HH.AI_v2/channel-gateway/v1/telegram/test-account/bot-token'`;

  const b64 = Buffer.from(combinedScript, 'utf16le').toString('base64');
  const systemRoot = process.env.SystemRoot || 'C:\\Windows';
  const powershellPath = path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');

  const res = runNativeBridge(powershellPath, [
    '-NoLogo',
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy', 'Bypass',
    '-EncodedCommand', b64
  ], {
    stdio: ['ignore', 'pipe', 'pipe'],
    encoding: 'utf8',
  });

  assert.strictEqual(res.status, 0, `Type-load smoke failed with status ${res.status}: ${res.stderr}`);
});

test('WindowsCredManProvider - R. decodeCredentialBlobUtf16le decodes ASCII, BMP, and supplementary plane characters', () => {
  // 1. ASCII
  const asciiText = 'ASCII_Test_String_123!@#$';
  const asciiBlob = Buffer.from(asciiText, 'utf16le');
  const asciiDecoded = decodeCredentialBlobUtf16le(asciiBlob);
  assert.strictEqual(Buffer.isBuffer(asciiDecoded), true);
  assert.strictEqual(asciiDecoded.equals(Buffer.from(asciiText, 'utf8')), true);

  // 2. BMP non-ASCII
  const bmpText = 'BMP_é_à_ö_中_文_測試_€';
  const bmpBlob = Buffer.from(bmpText, 'utf16le');
  const bmpDecoded = decodeCredentialBlobUtf16le(bmpBlob);
  assert.strictEqual(Buffer.isBuffer(bmpDecoded), true);
  assert.strictEqual(bmpDecoded.equals(Buffer.from(bmpText, 'utf8')), true);

  // 3. Supplementary plane (U+1F600 emoji via surrogate pair)
  const suppText = '😀🚀🎉';
  const suppBlob = Buffer.from(suppText, 'utf16le');
  const suppDecoded = decodeCredentialBlobUtf16le(suppBlob);
  assert.strictEqual(Buffer.isBuffer(suppDecoded), true);
  assert.strictEqual(suppDecoded.length, 12); // 3 * 4 bytes
  assert.strictEqual(suppDecoded.equals(Buffer.from(suppText, 'utf8')), true);

  // 4. Mixed combined text
  const mixedText = 'Prefix_ASCII_é_中_😀_Suffix_123';
  const mixedBlob = Buffer.from(mixedText, 'utf16le');
  const mixedDecoded = decodeCredentialBlobUtf16le(mixedBlob);
  assert.strictEqual(mixedDecoded.equals(Buffer.from(mixedText, 'utf8')), true);
});

test('WindowsCredManProvider - S. decodeCredentialBlobUtf16le fails closed with SECRET_ENCODING_INVALID on all invalid encodings', () => {
  // 1. Odd byte length
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from([0x61])),
    { code: 'SECRET_ENCODING_INVALID' }
  );
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from([0x61, 0x00, 0x62])),
    { code: 'SECRET_ENCODING_INVALID' }
  );

  // 2. Initial BOM (0xFEFF)
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from('\uFEFFvalid', 'utf16le')),
    { code: 'SECRET_ENCODING_INVALID' }
  );

  // 3. Embedded U+0000
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from('hello\u0000world', 'utf16le')),
    { code: 'SECRET_ENCODING_INVALID' }
  );

  // 4. Trailing U+0000
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from('hello\u0000', 'utf16le')),
    { code: 'SECRET_ENCODING_INVALID' }
  );

  // 5. Unpaired high surrogate at end
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from('valid\uD83D', 'utf16le')),
    { code: 'SECRET_ENCODING_INVALID' }
  );

  // 6. High surrogate followed by non-low surrogate
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from('valid\uD83Da', 'utf16le')),
    { code: 'SECRET_ENCODING_INVALID' }
  );
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from('valid\uD83D\uD83D', 'utf16le')),
    { code: 'SECRET_ENCODING_INVALID' }
  );

  // 7. Lone low surrogate
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from('\uDE00', 'utf16le')),
    { code: 'SECRET_ENCODING_INVALID' }
  );
  assert.throws(
    () => decodeCredentialBlobUtf16le(Buffer.from('prefix\uDE00suffix', 'utf16le')),
    { code: 'SECRET_ENCODING_INVALID' }
  );
});

test('WindowsCredManProvider - T. getSecret zeroes stdout buffer on success and failure, and returns fresh distinct Buffer', () => {
  // 1. Success case: stdout buffer zeroed, returned Buffer is fresh distinct object
  const secretString = 'confidential-token-value-999';
  const stdoutBufSuccess = Buffer.from(secretString, 'utf16le');
  const mockSpawnSuccess = () => ({
    status: 0,
    stdout: stdoutBufSuccess,
    stderr: Buffer.from(''),
  });

  const providerSuccess = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawnSuccess,
  });

  const secretResult = providerSuccess.getSecret(SecretRef.telegramBotToken('acc-zero'));
  assert.strictEqual(Buffer.isBuffer(secretResult), true);
  assert.strictEqual(secretResult !== stdoutBufSuccess, true, 'Returned Buffer must not be bridge stdout object');
  assert.strictEqual(secretResult.toString('utf8'), secretString);

  // Verify stdout buffer was zeroed
  assert.strictEqual(stdoutBufSuccess.every((byte) => byte === 0), true, 'Stdout buffer must be zeroed on success');
  secretResult.fill(0);

  // 2. Transcoding failure case: stdout buffer zeroed on error
  const stdoutBufFailure = Buffer.from('corrupt\u0000secret', 'utf16le');
  const mockSpawnFailure = () => ({
    status: 0,
    stdout: stdoutBufFailure,
    stderr: Buffer.from(''),
  });

  const providerFailure = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawnFailure,
  });

  assert.throws(
    () => providerFailure.getSecret(SecretRef.telegramBotToken('acc-zero-fail')),
    { code: 'SECRET_ENCODING_INVALID' }
  );
  assert.strictEqual(stdoutBufFailure.every((byte) => byte === 0), true, 'Stdout buffer must be zeroed on transcode failure');
});

test('WindowsCredManProvider - U. error message and stack never leak secret marker string', () => {
  const canaryMarker = 'CANARY_SENSITIVE_SECRET_TOKEN_DO_NOT_LEAK_48201';
  const invalidBlob = Buffer.from(`auth_${canaryMarker}_\u0000`, 'utf16le');

  try {
    decodeCredentialBlobUtf16le(invalidBlob);
    assert.fail('Should have thrown SECRET_ENCODING_INVALID');
  } catch (err) {
    assert.strictEqual(err.code, 'SECRET_ENCODING_INVALID');
    assert.strictEqual(err.message.includes(canaryMarker), false, 'Error message must not leak canary marker');
    assert.strictEqual(err.stack.includes(canaryMarker), false, 'Error stack must not leak canary marker');
  }

  // Also verify through getSecret with mock spawn
  const mockSpawn = () => ({
    status: 0,
    stdout: Buffer.from(`auth_${canaryMarker}_\u0000`, 'utf16le'),
    stderr: Buffer.from(''),
  });

  const provider = new WindowsCredentialManagerSecretProvider({
    platform: 'win32',
    powershellPath: process.execPath,
    scriptPath: __filename,
    spawnSync: mockSpawn,
  });

  try {
    provider.getSecret(SecretRef.telegramBotToken('canary-acc'));
    assert.fail('Should have thrown SECRET_ENCODING_INVALID');
  } catch (err) {
    assert.strictEqual(err.code, 'SECRET_ENCODING_INVALID');
    assert.strictEqual(err.message.includes(canaryMarker), false, 'Error message must not leak canary marker');
    assert.strictEqual(err.stack.includes(canaryMarker), false, 'Error stack must not leak canary marker');
  }
});

test('WindowsCredManProvider - V. static source inspection guarantees absence of forbidden decoders', () => {
  const providerSourcePath = path.resolve(__dirname, '..', 'core', 'windows-credential-manager-provider.js');
  assert.strictEqual(fs.existsSync(providerSourcePath), true, 'Provider source file must exist');
  const source = fs.readFileSync(providerSourcePath, 'utf8');

  assert.strictEqual(source.includes('TextDecoder'), false, 'Source must not contain TextDecoder');
  assert.strictEqual(source.includes('fromCharCode'), false, 'Source must not contain fromCharCode');
  assert.strictEqual(source.includes('fromCodePoint'), false, 'Source must not contain fromCodePoint');
  assert.strictEqual(source.includes("toString('utf16le')"), false, "Source must not contain toString('utf16le')");
  assert.strictEqual(source.includes('toString("utf16le")'), false, 'Source must not contain toString("utf16le")');
});

test('WindowsCredManProvider - W. INC-1-F3 transcoding temporary buffer is zeroized on success and partial-write failure', () => {
  const originalAlloc = Buffer.alloc;
  let spiedBuffers = [];

  const installSpy = () => {
    spiedBuffers = [];
    Buffer.alloc = function (size, fill, encoding) {
      const buf = originalAlloc.call(Buffer, size, fill, encoding);
      spiedBuffers.push(buf);
      return buf;
    };
  };

  const restoreSpy = () => {
    Buffer.alloc = originalAlloc;
  };

  // 1. Success path: tempBuf must be zeroized in finally
  const payload = Buffer.from('hello-world-secret', 'utf16le');
  let result = null;
  try {
    installSpy();
    result = decodeCredentialBlobUtf16le(payload);
    restoreSpy();

    assert.strictEqual(Buffer.isBuffer(result), true);
    assert.strictEqual(result.toString('utf8'), 'hello-world-secret');

    // In decodeCredentialBlobUtf16le:
    // First alloc is tempBuf (size numCodeUnits * 3), second alloc is outBuf (size outIdx).
    assert.strictEqual(spiedBuffers.length, 2, 'Must allocate tempBuf and outBuf');
    const tempBuf = spiedBuffers[0];
    const outBuf = spiedBuffers[1];
    assert.strictEqual(tempBuf !== outBuf, true, 'tempBuf must be distinct from outBuf');
    assert.strictEqual(result === outBuf, true, 'Returned buffer must be outBuf');

    // Assert tempBuf is completely zeroed
    assert.strictEqual(
      tempBuf.every((byte) => byte === 0),
      true,
      'Transcoding tempBuf must be zeroized on success'
    );
  } finally {
    restoreSpy();
    if (result) {
      result.fill(0);
    }
    payload.fill(0);
  }

  // 2. Partial-write failure path: writes some bytes, then encounters NUL (0x0000)
  const partialPayload = Buffer.from('partial\u0000more', 'utf16le');
  try {
    installSpy();
    assert.throws(
      () => decodeCredentialBlobUtf16le(partialPayload),
      { code: 'SECRET_ENCODING_INVALID' }
    );
    restoreSpy();

    assert.strictEqual(spiedBuffers.length >= 1, true, 'tempBuf must have been allocated');
    const tempBuf = spiedBuffers[0];
    assert.strictEqual(
      tempBuf.every((byte) => byte === 0),
      true,
      'Transcoding tempBuf must be zeroized on partial-write failure'
    );
  } finally {
    restoreSpy();
    partialPayload.fill(0);
  }

  // 3. Partial-write failure path: writes some bytes, then encounters unpaired surrogate
  const partialSurrogatePayload = Buffer.concat([
    Buffer.from('partial', 'utf16le'),
    Buffer.from([0x00, 0xD8, 0x61, 0x00]), // lone high surrogate followed by 'a' (0x0061 not in 0xDC00..0xDFFF)
  ]);
  try {
    installSpy();
    assert.throws(
      () => decodeCredentialBlobUtf16le(partialSurrogatePayload),
      { code: 'SECRET_ENCODING_INVALID' }
    );
    restoreSpy();

    assert.strictEqual(spiedBuffers.length >= 1, true, 'tempBuf must have been allocated');
    const tempBuf = spiedBuffers[0];
    assert.strictEqual(
      tempBuf.every((byte) => byte === 0),
      true,
      'Transcoding tempBuf must be zeroized on partial surrogate failure'
    );
  } finally {
    restoreSpy();
    partialSurrogatePayload.fill(0);
  }
});

test('WindowsCredManProvider - native runs are locked to the production timeout (B-107, F2-A)', () => {
  // F2-A: the production bridge default and upper bound are both 60000 ms.
  assert.strictEqual(DEFAULT_TIMEOUT_MS, 60000);
  assert.strictEqual(NATIVE_SPAWN_TIMEOUT_MS, DEFAULT_TIMEOUT_MS);
  // Effective options reaching spawnSync: a caller-supplied budget or visibility must not survive.
  const calls = [];
  const originalSpawnSync = child_process.spawnSync;
  child_process.spawnSync = (file, args, options) => {
    calls.push({ file, args, options });
    return { status: 0, signal: null };
  };
  try {
    runNativeBridge('probe.exe', ['-a'], JSON.parse('{"encoding":"utf8","timeout":1,"windowsHide":false}'));
  } finally {
    child_process.spawnSync = originalSpawnSync;
  }
  assert.deepStrictEqual(calls, [
    { file: 'probe.exe', args: ['-a'], options: { encoding: 'utf8', timeout: NATIVE_SPAWN_TIMEOUT_MS, windowsHide: true } },
  ]);
});
