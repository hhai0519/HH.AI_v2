# runtime/channel-gateway/bin/windows-known-folder-resolve.ps1
#
# ADR-0022 D24: Windows Known-Folder Resolution Bridge.
#
# Invariants:
# - Resolves non-secret Known Folders (DesktopDirectory and LocalApplicationData) via .NET APIs.
# - Zero secret access, credential access, or environment enumeration.
# - Zero registry enumeration or network requests.
# - Zero filesystem writes or directory creation.
# - Outputs single compact machine-readable JSON payload to stdout.
# - Fail-closed on empty/whitespace paths or unexpected errors.
# - 7-bit ASCII source, deterministic UTF-8 stdout via .NET without BOM.

$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$PSModuleAutoLoadingPreference = 'None'
$ErrorActionPreference = 'Stop'

function Format-JsonString([string]$val) {
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.Append('"')
    $chars = $val.ToCharArray()
    for ($i = 0; $i -lt $chars.Length; $i++) {
        $ch = $chars[$i]
        $code = [int][char]$ch
        if ($ch -eq '\') {
            [void]$sb.Append('\\')
        } elseif ($ch -eq '"') {
            [void]$sb.Append('\"')
        } elseif ($ch -eq "`b") {
            [void]$sb.Append('\b')
        } elseif ($ch -eq "`f") {
            [void]$sb.Append('\f')
        } elseif ($ch -eq "`n") {
            [void]$sb.Append('\n')
        } elseif ($ch -eq "`r") {
            [void]$sb.Append('\r')
        } elseif ($ch -eq "`t") {
            [void]$sb.Append('\t')
        } elseif ($code -lt 32) {
            [void]$sb.Append('\u')
            [void]$sb.Append($code.ToString('x4'))
        } else {
            [void]$sb.Append($ch)
        }
    }
    [void]$sb.Append('"')
    return $sb.ToString()
}

try {
    $desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    $localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)

    if ([string]::IsNullOrWhiteSpace($desktop) -or [string]::IsNullOrWhiteSpace($localAppData)) {
        [Console]::Error.WriteLine("Failed to resolve Windows Known Folders: resolved path was empty or whitespace")
        exit 1
    }

    $escapedDesktop = Format-JsonString $desktop
    $escapedLocalAppData = Format-JsonString $localAppData

    $json = [string]::Concat('{"DesktopDirectory":', $escapedDesktop, ',"LocalApplicationData":', $escapedLocalAppData, '}')
    [Console]::Out.WriteLine($json)
    exit 0
} catch {
    [Console]::Error.WriteLine("Failed to resolve Windows Known Folders: unexpected error")
    exit 1
}
