# runtime/channel-gateway/bin/windows-credential-manager-read.ps1
#
# ADR-0026: Gateway Secret Provider Windows Credential Manager Read Bridge.
#
# Invariants:
# - Pure Win32 CredReadW / CredFree bridge via Reflection.Emit dynamic P/Invoke (advapi32.dll).
# - Reads exactly one CRED_TYPE_GENERIC credential target.
# - Zero credential enumeration (never calls CredEnumerate or cmdkey list).
# - Zero fallback to environment, files, or DPAPI.
# - Zero third-party PowerShell modules, external cmdlets, or external dependencies.
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

# Defense-in-depth: Disable automatic module loading across bridge execution
$PSModuleAutoLoadingPreference = 'None'
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($TargetName)) {
    exit 1
}

# Canonical HH.AI_v2 TargetName grammar assertion (Defense-in-Depth)
$canonicalTargetPattern = '^HH\.AI_v2/channel-gateway/v1/(?:telegram/(?:[A-Za-z0-9_.~!*()-]|%[0-9A-Fa-f]{2})+/bot-token|line/(?:[A-Za-z0-9_.~!*()-]|%[0-9A-Fa-f]{2})+/(?:channel-access-token|channel-secret)|local-api/hmac)$'

if ($TargetName -notmatch $canonicalTargetPattern) {
    exit 1
}

# Reflection.Emit dynamic assembly and module for Win32 Credential Manager bridge
$asmName = [System.Reflection.AssemblyName]::new('HHAI.ChannelGateway.WinCredBridge')
$asmBuilder = [System.Reflection.Emit.AssemblyBuilder]::DefineDynamicAssembly($asmName, [System.Reflection.Emit.AssemblyBuilderAccess]::Run)
$modBuilder = $asmBuilder.DefineDynamicModule('WinCredBridgeModule')

# Define CREDENTIAL value type (SequentialLayout)
$credTypeAttr = [System.Reflection.TypeAttributes]'Public, SequentialLayout, Sealed, BeforeFieldInit'
$credTypeBuilder = $modBuilder.DefineType('CREDENTIAL', $credTypeAttr, [System.ValueType])

$credFields = @(
    @('Flags', [UInt32]),
    @('Type', [UInt32]),
    @('TargetName', [IntPtr]),
    @('Comment', [IntPtr]),
    @('LastWrittenLowDateTime', [UInt32]),
    @('LastWrittenHighDateTime', [UInt32]),
    @('CredentialBlobSize', [UInt32]),
    @('CredentialBlob', [IntPtr]),
    @('Persist', [UInt32]),
    @('AttributeCount', [UInt32]),
    @('Attributes', [IntPtr]),
    @('TargetAlias', [IntPtr]),
    @('UserName', [IntPtr])
)

foreach ($f in $credFields) {
    [void]$credTypeBuilder.DefineField($f[0], $f[1], [System.Reflection.FieldAttributes]::Public)
}

$credType = $credTypeBuilder.CreateType()

# Define WinCredBridge static class
$bridgeTypeBuilder = $modBuilder.DefineType('WinCredBridge', [System.Reflection.TypeAttributes]'Public, Abstract, Sealed, BeforeFieldInit')

$dllImportCtor = [System.Runtime.InteropServices.DllImportAttribute].GetConstructor(@([string]))
$entryPointField = [System.Runtime.InteropServices.DllImportAttribute].GetField('EntryPoint')
$charSetField = [System.Runtime.InteropServices.DllImportAttribute].GetField('CharSet')
$setLastErrorField = [System.Runtime.InteropServices.DllImportAttribute].GetField('SetLastError')
$callingConventionField = [System.Runtime.InteropServices.DllImportAttribute].GetField('CallingConvention')
$preserveSigField = [System.Runtime.InteropServices.DllImportAttribute].GetField('PreserveSig')

$methodAttr = [System.Reflection.MethodAttributes]'Public, Static, PinvokeImpl'

# CredRead(string target, uint type, uint flags, out IntPtr pCred)
$byRefIntPtr = [IntPtr].MakeByRefType()
$credReadMethod = $bridgeTypeBuilder.DefineMethod('CredRead', $methodAttr, [bool], @([string], [UInt32], [UInt32], $byRefIntPtr))
$credReadAttrBuilder = [System.Reflection.Emit.CustomAttributeBuilder]::new(
    $dllImportCtor,
    @('advapi32.dll'),
    @($entryPointField, $charSetField, $setLastErrorField, $callingConventionField, $preserveSigField),
    @('CredReadW', [System.Runtime.InteropServices.CharSet]::Unicode, $true, [System.Runtime.InteropServices.CallingConvention]::Winapi, $true)
)
$credReadMethod.SetCustomAttribute($credReadAttrBuilder)

# CredFree(IntPtr pCred)
$credFreeMethod = $bridgeTypeBuilder.DefineMethod('CredFree', $methodAttr, [void], @([IntPtr]))
$credFreeAttrBuilder = [System.Reflection.Emit.CustomAttributeBuilder]::new(
    $dllImportCtor,
    @('advapi32.dll'),
    @($entryPointField, $callingConventionField, $preserveSigField),
    @('CredFree', [System.Runtime.InteropServices.CallingConvention]::Winapi, $true)
)
$credFreeMethod.SetCustomAttribute($credFreeAttrBuilder)

$bridgeType = $bridgeTypeBuilder.CreateType()

# Runtime fail-closed metadata assertions
$readM = $bridgeType.GetMethod('CredRead', [System.Reflection.BindingFlags]'Public, Static')
if ($null -eq $readM -or $readM.ReturnType -ne [bool]) { exit 1 }
$readParams = $readM.GetParameters()
if ($readParams.Count -ne 4 -or
    $readParams[0].ParameterType -ne [string] -or
    $readParams[1].ParameterType -ne [UInt32] -or
    $readParams[2].ParameterType -ne [UInt32] -or
    $readParams[3].ParameterType -ne $byRefIntPtr) { exit 1 }

$readAttrs = $readM.GetCustomAttributes([System.Runtime.InteropServices.DllImportAttribute], $false)
if ($readAttrs.Length -ne 1) { exit 1 }
$ra = $readAttrs[0]
if ($ra.Value -ne 'advapi32.dll' -or
    $ra.EntryPoint -ne 'CredReadW' -or
    $ra.SetLastError -ne $true -or
    $ra.CharSet -ne [System.Runtime.InteropServices.CharSet]::Unicode -or
    $ra.CallingConvention -ne [System.Runtime.InteropServices.CallingConvention]::Winapi -or
    $ra.PreserveSig -ne $true) { exit 1 }

$freeM = $bridgeType.GetMethod('CredFree', [System.Reflection.BindingFlags]'Public, Static')
if ($null -eq $freeM -or $freeM.ReturnType -ne [void]) { exit 1 }
$freeParams = $freeM.GetParameters()
if ($freeParams.Count -ne 1 -or $freeParams[0].ParameterType -ne [IntPtr]) { exit 1 }

$freeAttrs = $freeM.GetCustomAttributes([System.Runtime.InteropServices.DllImportAttribute], $false)
if ($freeAttrs.Length -ne 1) { exit 1 }
$fa = $freeAttrs[0]
if ($fa.Value -ne 'advapi32.dll' -or
    $fa.EntryPoint -ne 'CredFree' -or
    $fa.CallingConvention -ne [System.Runtime.InteropServices.CallingConvention]::Winapi -or
    $fa.PreserveSig -ne $true) { exit 1 }

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
    $cred = [System.Runtime.InteropServices.Marshal]::PtrToStructure($pCred, [Type]$credType)
    $blobSize = $cred.CredentialBlobSize
    if ($blobSize -eq 0) {
        $exitCode = 0
    } else {
        $blob = [byte[]]::new($blobSize)
        [System.Runtime.InteropServices.Marshal]::Copy($cred.CredentialBlob, $blob, 0, $blobSize)

        $stdoutStream = [Console]::OpenStandardOutput()

        # Test seam: simulate stdout write failure after native acquisition
        if ($TestFaultStage -eq 'stdout') {
            throw ([System.IO.IOException]::new('Simulated stdout failure after acquisition'))
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
