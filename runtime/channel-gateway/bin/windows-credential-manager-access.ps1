# runtime/channel-gateway/bin/windows-credential-manager-access.ps1
#
# SEC-02 INC-2: Windows Credential Manager Guarded Access Bridge.
#
# Invariants:
# - Pure Win32 CredReadW / CredWriteW / CredDeleteW / CredFree bridge via Reflection.Emit (advapi32.dll).
# - Zero credential enumeration (never calls CredEnumerate or cmdkey).
# - Zero fallback to environment, files, or DPAPI.
# - Zero third-party PowerShell modules, external cmdlets, or external dependencies.
# - Zero informational text on standard output.
# - Fail-closed exit codes:
#     0: Success (PRESENT, ABSENT, CREATED, DELETED on stdout)
#     3: ERROR_ACCESS_DENIED (5)
#     4: CREDENTIAL_ALREADY_EXISTS (on create if already exists)
#     5: CREDENTIAL_BUSY (mutex acquisition failed / WaitOne(0) returned false)
#     6: SECRET_ENCODING_INVALID (invalid blob encoding / size > 2560)
#     1: Generic error / abandoned mutex / unexpected failure
# - Strict parameter validation and target allowlist without echoing input.
# - Named mutex: Global\HH.AI_v2.CredMan.v1.<SID>.<digest> protects write and delete.
# - Single native ownership model: resources freed and zeroized in finally.

[CmdletBinding()]
param (
    [Parameter(Mandatory = $true)]
    [string]$Operation,

    [Parameter(Mandatory = $true)]
    [string]$TargetName,

    [Parameter(Mandatory = $false)]
    [string]$TestFaultStage = $null,

    [Parameter(Mandatory = $false)]
    [switch]$TraceCleanup
)

$PSModuleAutoLoadingPreference = 'None'
$ErrorActionPreference = 'Stop'

if ($Operation -ne 'presence' -and $Operation -ne 'create' -and $Operation -ne 'delete') {
    exit 1
}

if ([string]::IsNullOrWhiteSpace($TargetName)) {
    exit 1
}

if ($TargetName.Length -gt 32767) {
    exit 1
}

if ($TargetName -match '[\x00-\x1F\x7F]') {
    exit 1
}

if ($TargetName.Contains('*') -or $TargetName.Contains('?')) {
    exit 1
}

# Canonical TargetName grammar assertion
$targetPattern = '^(?:HH\.AI_v2/channel-gateway/v1/(?:telegram/([^/]+)/bot-token|line/([^/]+)/(?:channel-access-token|channel-secret)|local-api/hmac)|HH\.AI_v2/mcp-launcher/v1/(?:jules/api-key|notion/api-token))$'
$targetRegex = [System.Text.RegularExpressions.Regex]::new($targetPattern)
$match = $targetRegex.Match($TargetName)
if (-not $match.Success) {
    exit 1
}

# Strict percent-encoding verification for account segment if present
$accountSegment = $null
if ($match.Groups[1].Success) {
    $accountSegment = $match.Groups[1].Value
} elseif ($match.Groups[2].Success) {
    $accountSegment = $match.Groups[2].Value
}

if ($null -ne $accountSegment) {
    $strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        [void]$strictUtf8.GetBytes($accountSegment)
        $decoded = [System.Uri]::UnescapeDataString($accountSegment)
        [void]$strictUtf8.GetBytes($decoded)
    } catch {
        exit 1
    }
    if ($decoded -match '[\x00-\x1F\x7F]' -or $decoded.Contains('*') -or $decoded.Contains('?')) {
        exit 1
    }
    $reencoded = [System.Uri]::EscapeDataString($decoded).Replace("'", "%27")
    if ($reencoded -cne $accountSegment) {
        exit 1
    }
}

# Test fault stages and trace cleanup restrictions: only allowed on synthetic Telegram targets (syn-<GUID>)
$hasTestFaultStage = $PSBoundParameters.ContainsKey('TestFaultStage')
if ($hasTestFaultStage -or $TraceCleanup.IsPresent) {
    $synMatch = [System.Text.RegularExpressions.Regex]::IsMatch(
        $TargetName,
        '^HH\.AI_v2/channel-gateway/v1/telegram/syn-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/bot-token$'
    )
    if (-not $synMatch) {
        exit 1
    }
}

if ($hasTestFaultStage) {
    if ([string]::IsNullOrEmpty($TestFaultStage)) {
        exit 1
    }
    if ($TestFaultStage -eq 'keep-mutex-open' -or $TestFaultStage -eq 'hold-mutex' -or $TestFaultStage -eq 'after-read-check' -or $TestFaultStage -eq 'after-blob-alloc') {
        if ($Operation -ne 'create') {
            exit 1
        }
    } elseif ($TestFaultStage -eq 'acquired-read') {
        if ($Operation -ne 'presence') {
            exit 1
        }
    } elseif ($TestFaultStage -eq 'before-stdout') {
        if ($Operation -ne 'create' -and $Operation -ne 'delete') {
            exit 1
        }
    } else {
        exit 1
    }
}

# Reflection.Emit dynamic assembly and module for Win32 Credential Manager access bridge
$asmName = [System.Reflection.AssemblyName]::new('HHAI.ChannelGateway.WinCredAccessBridge')
$asmBuilder = [System.Reflection.Emit.AssemblyBuilder]::DefineDynamicAssembly($asmName, [System.Reflection.Emit.AssemblyBuilderAccess]::Run)
$modBuilder = $asmBuilder.DefineDynamicModule('WinCredAccessBridgeModule')

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

# Define WinCredAccessBridge static class
$bridgeTypeBuilder = $modBuilder.DefineType('WinCredAccessBridge', [System.Reflection.TypeAttributes]'Public, Abstract, Sealed, BeforeFieldInit')

$dllImportCtor = [System.Runtime.InteropServices.DllImportAttribute].GetConstructor(@([string]))
$entryPointField = [System.Runtime.InteropServices.DllImportAttribute].GetField('EntryPoint')
$charSetField = [System.Runtime.InteropServices.DllImportAttribute].GetField('CharSet')
$setLastErrorField = [System.Runtime.InteropServices.DllImportAttribute].GetField('SetLastError')
$callingConventionField = [System.Runtime.InteropServices.DllImportAttribute].GetField('CallingConvention')
$preserveSigField = [System.Runtime.InteropServices.DllImportAttribute].GetField('PreserveSig')

$methodAttr = [System.Reflection.MethodAttributes]'Public, Static, PinvokeImpl'
$byRefIntPtr = [IntPtr].MakeByRefType()

# CredRead(string target, uint type, uint flags, out IntPtr pCred)
$credReadMethod = $bridgeTypeBuilder.DefineMethod('CredRead', $methodAttr, [bool], @([string], [UInt32], [UInt32], $byRefIntPtr))
$credReadAttrBuilder = [System.Reflection.Emit.CustomAttributeBuilder]::new(
    $dllImportCtor,
    @('advapi32.dll'),
    @($entryPointField, $charSetField, $setLastErrorField, $callingConventionField, $preserveSigField),
    @('CredReadW', [System.Runtime.InteropServices.CharSet]::Unicode, $true, [System.Runtime.InteropServices.CallingConvention]::Winapi, $true)
)
$credReadMethod.SetCustomAttribute($credReadAttrBuilder)

# CredWrite(IntPtr pCred, uint flags)
$credWriteMethod = $bridgeTypeBuilder.DefineMethod('CredWrite', $methodAttr, [bool], @([IntPtr], [UInt32]))
$credWriteAttrBuilder = [System.Reflection.Emit.CustomAttributeBuilder]::new(
    $dllImportCtor,
    @('advapi32.dll'),
    @($entryPointField, $setLastErrorField, $callingConventionField, $preserveSigField),
    @('CredWriteW', $true, [System.Runtime.InteropServices.CallingConvention]::Winapi, $true)
)
$credWriteMethod.SetCustomAttribute($credWriteAttrBuilder)

# CredDelete(string target, uint type, uint flags)
$credDeleteMethod = $bridgeTypeBuilder.DefineMethod('CredDelete', $methodAttr, [bool], @([string], [UInt32], [UInt32]))
$credDeleteAttrBuilder = [System.Reflection.Emit.CustomAttributeBuilder]::new(
    $dllImportCtor,
    @('advapi32.dll'),
    @($entryPointField, $charSetField, $setLastErrorField, $callingConventionField, $preserveSigField),
    @('CredDeleteW', [System.Runtime.InteropServices.CharSet]::Unicode, $true, [System.Runtime.InteropServices.CallingConvention]::Winapi, $true)
)
$credDeleteMethod.SetCustomAttribute($credDeleteAttrBuilder)

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

$writeM = $bridgeType.GetMethod('CredWrite', [System.Reflection.BindingFlags]'Public, Static')
if ($null -eq $writeM -or $writeM.ReturnType -ne [bool]) { exit 1 }
$writeParams = $writeM.GetParameters()
if ($writeParams.Count -ne 2 -or
    $writeParams[0].ParameterType -ne [IntPtr] -or
    $writeParams[1].ParameterType -ne [UInt32]) { exit 1 }
$writeAttrs = $writeM.GetCustomAttributes([System.Runtime.InteropServices.DllImportAttribute], $false)
if ($writeAttrs.Length -ne 1) { exit 1 }
$wa = $writeAttrs[0]
if ($wa.Value -ne 'advapi32.dll' -or
    $wa.EntryPoint -ne 'CredWriteW' -or
    $wa.SetLastError -ne $true -or
    $wa.CallingConvention -ne [System.Runtime.InteropServices.CallingConvention]::Winapi -or
    $wa.PreserveSig -ne $true) { exit 1 }

$deleteM = $bridgeType.GetMethod('CredDelete', [System.Reflection.BindingFlags]'Public, Static')
if ($null -eq $deleteM -or $deleteM.ReturnType -ne [bool]) { exit 1 }
$delParams = $deleteM.GetParameters()
if ($delParams.Count -ne 3 -or
    $delParams[0].ParameterType -ne [string] -or
    $delParams[1].ParameterType -ne [UInt32] -or
    $delParams[2].ParameterType -ne [UInt32]) { exit 1 }
$delAttrs = $deleteM.GetCustomAttributes([System.Runtime.InteropServices.DllImportAttribute], $false)
if ($delAttrs.Length -ne 1) { exit 1 }
$da = $delAttrs[0]
if ($da.Value -ne 'advapi32.dll' -or
    $da.EntryPoint -ne 'CredDeleteW' -or
    $da.SetLastError -ne $true -or
    $da.CharSet -ne [System.Runtime.InteropServices.CharSet]::Unicode -or
    $da.CallingConvention -ne [System.Runtime.InteropServices.CallingConvention]::Winapi -or
    $da.PreserveSig -ne $true) { exit 1 }

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

# CREDENTIAL layout assertions (R4)
$ptrSize = [System.IntPtr]::Size
$credSizeActual = [System.Runtime.InteropServices.Marshal]::SizeOf([Type]$credType)
$blobSizeOffset = [System.Runtime.InteropServices.Marshal]::OffsetOf([Type]$credType, 'CredentialBlobSize').ToInt64()
$blobOffset = [System.Runtime.InteropServices.Marshal]::OffsetOf([Type]$credType, 'CredentialBlob').ToInt64()
$userOffset = [System.Runtime.InteropServices.Marshal]::OffsetOf([Type]$credType, 'UserName').ToInt64()

if ($ptrSize -eq 8) {
    if ($credSizeActual -ne 80 -or $blobSizeOffset -ne 32 -or $blobOffset -ne 40 -or $userOffset -ne 72) {
        exit 1
    }
} elseif ($ptrSize -eq 4) {
    if ($credSizeActual -ne 52 -or $blobSizeOffset -ne 24 -or $blobOffset -ne 28 -or $userOffset -ne 48) {
        exit 1
    }
} else {
    exit 1
}

$pReadCred = [IntPtr]::Zero
$pBlob = [IntPtr]::Zero
$pTargetName = [IntPtr]::Zero
$pCred = [IntPtr]::Zero
$blob = $null
$blobLength = 0
$readBuf = $null
$mutex = $null
$mutexAcquired = $false
$acquiredForTrace = 0
$hasAbandoned = $false
$exitCode = 1
$cleanupFailed = 0

$readCalls = 0
$writeCalls = 0
$deleteCalls = 0
$readFreeCount = 0
$blobClearCount = 0
$blobFreeCount = 0
$mutexReleaseCount = 0
$mutexDisposeCount = 0

$CRED_TYPE_GENERIC = [UInt32]1
$CRED_PERSIST_LOCAL_MACHINE = [UInt32]2

try {
    if ($Operation -eq 'presence') {
        $readCalls++
        $readSuccess = [WinCredAccessBridge]::CredRead($TargetName, $CRED_TYPE_GENERIC, 0, [ref]$pReadCred)
        if ($readSuccess) {
            if ($pReadCred -eq [IntPtr]::Zero) {
                $exitCode = 1
                exit 1
            }
            if ($TestFaultStage -eq 'acquired-read') {
                throw [System.InvalidOperationException]::new('Fault after acquired read pointer')
            }
            [WinCredAccessBridge]::CredFree($pReadCred)
            $pReadCred = [IntPtr]::Zero
            $readFreeCount++

            $outBytes = [System.Text.Encoding]::ASCII.GetBytes("PRESENT`r`n")
            $stdOut = [Console]::OpenStandardOutput()
            $stdOut.Write($outBytes, 0, $outBytes.Length)
            $stdOut.Flush()
            $exitCode = 0
            exit 0
        } else {
            $err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
            if ($err -eq 1168) {
                # ERROR_NOT_FOUND -> ABSENT
                $outBytes = [System.Text.Encoding]::ASCII.GetBytes("ABSENT`r`n")
                $stdOut = [Console]::OpenStandardOutput()
                $stdOut.Write($outBytes, 0, $outBytes.Length)
                $stdOut.Flush()
                $exitCode = 0
                exit 0
            } elseif ($err -eq 5) {
                # ERROR_ACCESS_DENIED
                $exitCode = 3
                exit 3
            } else {
                $exitCode = 1
                exit 1
            }
        }
    }

    # For create and delete: acquire named mutex
    $targetUpper = $TargetName.ToUpperInvariant()
    $targetBytes = [System.Text.Encoding]::UTF8.GetBytes($targetUpper)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha.ComputeHash($targetBytes)
    } finally {
        $sha.Dispose()
    }
    $sb = [System.Text.StringBuilder]::new(64)
    foreach ($b in $hashBytes) {
        [void]$sb.Append($b.ToString('x2'))
    }
    $digest = $sb.ToString()

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    try {
        $sid = $identity.User.Value
    } finally {
        $identity.Dispose()
    }

    $mutexName = [string]::Concat('Global\HH.AI_v2.CredMan.v1.', $sid, '.', $digest)
    try {
        $mutex = [System.Threading.Mutex]::new($false, $mutexName)
    } catch {
        $exitCode = 1
        exit 1
    }

    if ($TestFaultStage -eq 'keep-mutex-open') {
        $outBytes = [System.Text.Encoding]::ASCII.GetBytes("KEEPER_READY`r`n")
        $stdOut = [Console]::OpenStandardOutput()
        $stdOut.Write($outBytes, 0, $outBytes.Length)
        $stdOut.Flush()
        $stdIn = [Console]::OpenStandardInput()
        $dummy = [byte[]]::new(1)
        [void]$stdIn.Read($dummy, 0, 1)
        $exitCode = 0
        exit 0
    }

    try {
        $waitResult = $mutex.WaitOne(0)
        if ($waitResult) {
            $mutexAcquired = $true
            $acquiredForTrace = 1
        } else {
            # Busy: initial ownership false, WaitOne returned false
            $exitCode = 5
            exit 5
        }
    } catch [System.Threading.AbandonedMutexException] {
        $mutexAcquired = $true
        $acquiredForTrace = 1
        $hasAbandoned = $true
    } catch {
        if ($_.Exception.InnerException -is [System.Threading.AbandonedMutexException]) {
            $mutexAcquired = $true
            $acquiredForTrace = 1
            $hasAbandoned = $true
        } else {
            $exitCode = 1
            exit 1
        }
    }

    if ($hasAbandoned) {
        # Abandoned mutex: ownership acquired, but must not call native credential APIs
        $exitCode = 1
        exit 1
    }

    if ($TestFaultStage -eq 'hold-mutex') {
        $outBytes = [System.Text.Encoding]::ASCII.GetBytes("HELD`r`n")
        $stdOut = [Console]::OpenStandardOutput()
        $stdOut.Write($outBytes, 0, $outBytes.Length)
        $stdOut.Flush()
        $stdIn = [Console]::OpenStandardInput()
        $dummy = [byte[]]::new(1)
        [void]$stdIn.Read($dummy, 0, 1)
        $exitCode = 0
        exit 0
    }

    if ($Operation -eq 'create') {
        # Mutex acquired: first check exact presence
        $readCalls++
        $readSuccess = [WinCredAccessBridge]::CredRead($TargetName, $CRED_TYPE_GENERIC, 0, [ref]$pReadCred)
        if ($readSuccess) {
            if ($pReadCred -eq [IntPtr]::Zero) {
                $exitCode = 1
                exit 1
            }
            # Target already exists!
            [WinCredAccessBridge]::CredFree($pReadCred)
            $pReadCred = [IntPtr]::Zero
            $readFreeCount++
            $exitCode = 4
            exit 4
        }
        $err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
        if ($err -ne 1168) {
            if ($err -eq 5) {
                $exitCode = 3
                exit 3
            }
            $exitCode = 1
            exit 1
        }

        # Target absent, can proceed
        if ($TestFaultStage -eq 'after-read-check') {
            throw [System.InvalidOperationException]::new('Fault after read check')
        }

        # Bounded read from binary stdin: up to 2561 bytes
        $maxBlobSize = 2560
        $readBuf = [byte[]]::new($maxBlobSize + 1)
        $stdIn = [Console]::OpenStandardInput()
        $totalRead = 0
        while ($totalRead -lt $readBuf.Length) {
            $readChunk = $stdIn.Read($readBuf, $totalRead, $readBuf.Length - $totalRead)
            if ($readChunk -le 0) {
                break
            }
            $totalRead += $readChunk
        }

        if ($totalRead -gt $maxBlobSize -or $totalRead -le 0 -or ($totalRead % 2 -ne 0)) {
            $exitCode = 6
            exit 6
        }

        $blob = [byte[]]::new($totalRead)
        $blobLength = $totalRead
        [System.Array]::Copy($readBuf, 0, $blob, 0, $totalRead)
        [System.Array]::Clear($readBuf, 0, $readBuf.Length)
        $readBuf = $null

        # Native blob validation: reject BOM, NUL, unpaired surrogates
        $firstWord = [System.BitConverter]::ToUInt16($blob, 0)
        if ($firstWord -eq 0xFEFF -or $firstWord -eq 0xFFFE) {
            $exitCode = 6
            exit 6
        }

        $idx = 0
        $validSequence = $true
        while ($idx -lt $blob.Length) {
            $cu = [System.BitConverter]::ToUInt16($blob, $idx)
            if ($cu -eq 0) {
                $validSequence = $false
                break
            }
            if ($cu -ge 0xD800 -and $cu -le 0xDBFF) {
                if ($idx + 2 -ge $blob.Length) {
                    $validSequence = $false
                    break
                }
                $cu2 = [System.BitConverter]::ToUInt16($blob, $idx + 2)
                if ($cu2 -lt 0xDC00 -or $cu2 -gt 0xDFFF) {
                    $validSequence = $false
                    break
                }
                $idx += 4
            } elseif ($cu -ge 0xDC00 -and $cu -le 0xDFFF) {
                $validSequence = $false
                break
            } else {
                $idx += 2
            }
        }

        if (-not $validSequence) {
            $exitCode = 6
            exit 6
        }

        $pBlob = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($blob.Length)
        [System.Runtime.InteropServices.Marshal]::Copy($blob, 0, $pBlob, $blob.Length)
        if ($TestFaultStage -eq 'after-blob-alloc') {
            throw [System.InvalidOperationException]::new('Fault after blob allocation')
        }

        $pTargetName = [System.Runtime.InteropServices.Marshal]::StringToHGlobalUni($TargetName)

        $credInstance = [System.Activator]::CreateInstance([Type]$credType)
        $credInstance.Flags = [UInt32]0
        $credInstance.Type = $CRED_TYPE_GENERIC
        $credInstance.TargetName = $pTargetName
        $credInstance.Comment = [IntPtr]::Zero
        $credInstance.LastWrittenLowDateTime = [UInt32]0
        $credInstance.LastWrittenHighDateTime = [UInt32]0
        $credInstance.CredentialBlobSize = [UInt32]$blob.Length
        $credInstance.CredentialBlob = $pBlob
        $credInstance.Persist = $CRED_PERSIST_LOCAL_MACHINE
        $credInstance.AttributeCount = [UInt32]0
        $credInstance.Attributes = [IntPtr]::Zero
        $credInstance.TargetAlias = [IntPtr]::Zero
        $credInstance.UserName = [IntPtr]::Zero

        $credSize = [System.Runtime.InteropServices.Marshal]::SizeOf([Type]$credType)
        $pCred = [System.Runtime.InteropServices.Marshal]::AllocHGlobal($credSize)
        [System.Runtime.InteropServices.Marshal]::StructureToPtr($credInstance, $pCred, $false)

        $writeCalls++
        $writeSuccess = [WinCredAccessBridge]::CredWrite($pCred, 0)
        if (-not $writeSuccess) {
            $wErr = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
            if ($wErr -eq 5) {
                $exitCode = 3
                exit 3
            }
            $exitCode = 1
            exit 1
        }

        if ($TestFaultStage -eq 'before-stdout') {
            throw [System.InvalidOperationException]::new('Fault before stdout')
        }

        $outBytes = [System.Text.Encoding]::ASCII.GetBytes("CREATED`r`n")
        $stdOut = [Console]::OpenStandardOutput()
        $stdOut.Write($outBytes, 0, $outBytes.Length)
        $stdOut.Flush()
        $exitCode = 0
        exit 0
    }

    if ($Operation -eq 'delete') {
        $deleteCalls++
        $delSuccess = [WinCredAccessBridge]::CredDelete($TargetName, $CRED_TYPE_GENERIC, 0)
        if ($delSuccess) {
            if ($TestFaultStage -eq 'before-stdout') {
                throw [System.InvalidOperationException]::new('Fault before stdout')
            }
            $outBytes = [System.Text.Encoding]::ASCII.GetBytes("DELETED`r`n")
            $stdOut = [Console]::OpenStandardOutput()
            $stdOut.Write($outBytes, 0, $outBytes.Length)
            $stdOut.Flush()
            $exitCode = 0
            exit 0
        } else {
            $err = [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()
            if ($err -eq 1168) {
                $outBytes = [System.Text.Encoding]::ASCII.GetBytes("ABSENT`r`n")
                $stdOut = [Console]::OpenStandardOutput()
                $stdOut.Write($outBytes, 0, $outBytes.Length)
                $stdOut.Flush()
                $exitCode = 0
                exit 0
            } elseif ($err -eq 5) {
                $exitCode = 3
                exit 3
            } else {
                $exitCode = 1
                exit 1
            }
        }
    }
} catch {
    $exitCode = 1
} finally {
    $cleanupFailed = 0
    if ($pReadCred -ne [IntPtr]::Zero) {
        try {
            [WinCredAccessBridge]::CredFree($pReadCred)
            $pReadCred = [IntPtr]::Zero
            $readFreeCount++
        } catch {
            $cleanupFailed = 1
            $exitCode = 1
        }
    }
    if ($pBlob -ne [IntPtr]::Zero) {
        try {
            if ($blobLength -gt 0) {
                $zeroArr = [byte[]]::new($blobLength)
                [System.Runtime.InteropServices.Marshal]::Copy($zeroArr, 0, $pBlob, $blobLength)
                [System.Array]::Clear($zeroArr, 0, $zeroArr.Length)
                $blobClearCount++
            }
            [System.Runtime.InteropServices.Marshal]::FreeHGlobal($pBlob)
            $pBlob = [IntPtr]::Zero
            $blobFreeCount++
        } catch {
            $cleanupFailed = 1
            $exitCode = 1
        }
    }
    if ($pTargetName -ne [IntPtr]::Zero) {
        try {
            [System.Runtime.InteropServices.Marshal]::FreeHGlobal($pTargetName)
            $pTargetName = [IntPtr]::Zero
        } catch {
            $cleanupFailed = 1
            $exitCode = 1
        }
    }
    if ($pCred -ne [IntPtr]::Zero) {
        try {
            [System.Runtime.InteropServices.Marshal]::FreeHGlobal($pCred)
            $pCred = [IntPtr]::Zero
        } catch {
            $cleanupFailed = 1
            $exitCode = 1
        }
    }
    if ($null -ne $blob) {
        try {
            [System.Array]::Clear($blob, 0, $blob.Length)
            $blob = $null
        } catch {
            $cleanupFailed = 1
            $exitCode = 1
        }
    }
    if ($null -ne $readBuf) {
        try {
            [System.Array]::Clear($readBuf, 0, $readBuf.Length)
            $readBuf = $null
        } catch {
            $cleanupFailed = 1
            $exitCode = 1
        }
    }
    if ($mutexAcquired) {
        try {
            $mutex.ReleaseMutex()
            $mutexAcquired = $false
            $mutexReleaseCount++
        } catch {
            $cleanupFailed = 1
            $exitCode = 1
        }
    }
    if ($null -ne $mutex) {
        try {
            $mutex.Dispose()
            $mutex = $null
            $mutexDisposeCount++
        } catch {
            $cleanupFailed = 1
            $exitCode = 1
        }
    }
    if ($TraceCleanup) {
        [Console]::Error.WriteLine([string]::Concat(
            'CLEANUP: acquired=', [int]$acquiredForTrace,
            ' readCalls=', $readCalls,
            ' writeCalls=', $writeCalls,
            ' deleteCalls=', $deleteCalls,
            ' readFree=', $readFreeCount,
            ' blobClear=', $blobClearCount,
            ' blobFree=', $blobFreeCount,
            ' mutexRelease=', $mutexReleaseCount,
            ' mutexDispose=', $mutexDisposeCount,
            ' cleanupFailed=', $cleanupFailed
        ))
    }
}

exit $exitCode
