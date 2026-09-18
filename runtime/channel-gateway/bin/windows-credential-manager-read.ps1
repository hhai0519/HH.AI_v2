# runtime/channel-gateway/bin/windows-credential-manager-read.ps1
#
# ADR-0026: Gateway Secret Provider Windows Credential Manager Read Bridge.
#
# Invariants:
# - Pure Win32 CredReadW / CredFree bridge via advapi32.dll built-in APIs.
# - Reads exactly one CRED_TYPE_GENERIC credential target.
# - Zero credential enumeration (never calls CredEnumerate or cmdkey list).
# - Zero fallback to environment, files, or DPAPI.
# - Zero third-party PowerShell modules or external dependencies.
# - Zero informational text or headers on standard output.
# - Binary secret payload emitted directly to standard output stream only.
# - Never writes secret bytes or raw payload to standard error.
# - Defense-in-depth: Rejects targets outside canonical HH.AI_v2 namespace grammar.
# - Single native ownership model: CredFree called exactly once on all post-acquisition exit paths.
# - Pointer zeroed immediately after native release ($pCred = [IntPtr]::Zero).
# - Managed secret byte array best-effort zeroized in cleanup ([Array]::Clear).
# - Fail-closed exit codes:
#     0: Success (raw bytes written to stdout)
#     2: ERROR_NOT_FOUND (1168)
#     3: ERROR_ACCESS_DENIED (5)
#     1: Generic / unexpected error or invalid input

[CmdletBinding()]
param (
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$TargetName,

    [Parameter(Mandatory = $false)]
    [string]$TestFaultStage = $null
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($TargetName)) {
    exit 1
}

# Canonical HH.AI_v2 TargetName grammar assertion (Defense-in-Depth)
$canonicalTargetPattern = '^HH\.AI_v2/channel-gateway/v1/(?:telegram/(?:[A-Za-z0-9_.~!*()-]|%[0-9A-Fa-f]{2})+/bot-token|line/(?:[A-Za-z0-9_.~!*()-]|%[0-9A-Fa-f]{2})+/(?:channel-access-token|channel-secret)|local-api/hmac)$'

if ($TargetName -notmatch $canonicalTargetPattern) {
    exit 1
}

$signature = @'
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

public class WinCredBridge {
    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CredRead(string target, uint type, uint flags, out IntPtr pCred);

    [DllImport("advapi32.dll", EntryPoint = "CredFree", SetLastError = true)]
    public static extern void CredFree(IntPtr pCred);
}
'@

try {
    if (-not ([System.Management.Automation.PSTypeName]'WinCredBridge').Type) {
        Add-Type -TypeDefinition $signature -ErrorAction Stop
    }
} catch {
    exit 1
}

$pCred = [IntPtr]::Zero
$blob = $null
$CRED_TYPE_GENERIC = 1

$success = [WinCredBridge]::CredRead($TargetName, $CRED_TYPE_GENERIC, 0, [ref]$pCred)

if (-not $success) {
    $err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
    if ($err -eq 1168) {
        # ERROR_NOT_FOUND
        exit 2
    }
    if ($err -eq 5) {
        # ERROR_ACCESS_DENIED
        exit 3
    }
    exit 1
}

$exitCode = 1
try {
    $cred = [System.Runtime.InteropServices.Marshal]::PtrToStructure($pCred, [Type][CREDENTIAL])
    $blobSize = $cred.CredentialBlobSize
    if ($blobSize -eq 0) {
        $exitCode = 0
    } else {
        $blob = New-Object byte[] $blobSize
        [System.Runtime.InteropServices.Marshal]::Copy($cred.CredentialBlob, $blob, 0, $blobSize)

        $stdoutStream = [Console]::OpenStandardOutput()

        # Test seam: simulate stdout write failure after native acquisition
        if ($TestFaultStage -eq 'stdout') {
            throw [System.IO.IOException]::new("Simulated stdout failure after acquisition")
        }

        $stdoutStream.Write($blob, 0, $blob.Length)
        $stdoutStream.Flush()
        $exitCode = 0
    }
} catch {
    $exitCode = 1
} finally {
    if ($pCred -ne [IntPtr]::Zero) {
        [WinCredBridge]::CredFree($pCred)
        $pCred = [IntPtr]::Zero
    }
    if ($null -ne $blob) {
        [Array]::Clear($blob, 0, $blob.Length)
        $blob = $null
    }
}

exit $exitCode
