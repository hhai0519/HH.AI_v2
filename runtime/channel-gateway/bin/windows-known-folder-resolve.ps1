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
# - UTF-8 without BOM encoding (ADR-0013 §2C / CHECK 19).

$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

$ErrorActionPreference = 'Stop'

try {
    $desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    $localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)

    if ([string]::IsNullOrWhiteSpace($desktop) -or [string]::IsNullOrWhiteSpace($localAppData)) {
        [Console]::Error.WriteLine("Failed to resolve Windows Known Folders: resolved path was empty or whitespace")
        exit 1
    }

    $payload = [ordered]@{
        DesktopDirectory = $desktop
        LocalApplicationData = $localAppData
    }

    $json = $payload | ConvertTo-Json -Compress
    [Console]::Out.WriteLine($json)
    exit 0
} catch {
    [Console]::Error.WriteLine("Failed to resolve Windows Known Folders: unexpected error")
    exit 1
}
