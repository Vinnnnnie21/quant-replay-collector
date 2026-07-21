[CmdletBinding()]
param(
    [string]$TargetPath = "",
    [string]$DesktopPath = [Environment]::GetFolderPath("Desktop"),
    [string]$IconPath = "",
    [string]$ManifestPath = "",
    [string]$ExpectedVersion = "",
    [string]$ShortcutName = "QRC",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($TargetPath)) {
    $TargetPath = Join-Path $scriptRoot "..\quant_collector_app\dist\QRC\QRC.exe"
}

function Get-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path (Get-Location) $Path))
}

function Get-ShortcutFileName {
    param([Parameter(Mandatory = $true)][string]$Name)

    $trimmed = $Name.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        throw "ShortcutName must not be empty."
    }
    if ($trimmed.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "ShortcutName contains invalid filename characters."
    }
    if ($trimmed.EndsWith(".lnk", [StringComparison]::OrdinalIgnoreCase)) {
        return $trimmed
    }
    return "$trimmed.lnk"
}

$resolvedTarget = Get-AbsolutePath $TargetPath
if (-not (Test-Path -LiteralPath $resolvedTarget -PathType Leaf)) {
    throw "Target application was not found: $resolvedTarget"
}
if ([string]::IsNullOrWhiteSpace($IconPath)) {
    $packagedIcon = Join-Path (
        [IO.Path]::GetDirectoryName($resolvedTarget)
    ) "_internal\assets\app_icon.ico"
    $IconPath = if (Test-Path -LiteralPath $packagedIcon -PathType Leaf) {
        $packagedIcon
    } else {
        Join-Path $scriptRoot "..\quant_collector_app\assets\app_icon.ico"
    }
}
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path ([IO.Path]::GetDirectoryName($resolvedTarget)) "release-manifest.json"
}
$resolvedManifest = Get-AbsolutePath $ManifestPath
if (-not (Test-Path -LiteralPath $resolvedManifest -PathType Leaf)) {
    throw "Release manifest was not found: $resolvedManifest"
}
$manifest = Get-Content -LiteralPath $resolvedManifest -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.package_format -ne "onedir") {
    throw "Release manifest package format is not onedir: $($manifest.package_format)"
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedVersion) -and $manifest.application_version -ne $ExpectedVersion) {
    throw "Release manifest version mismatch. Expected $ExpectedVersion, got $($manifest.application_version)."
}
if ($manifest.native_launch_verified -ne $true) {
    throw "Release manifest does not contain a successful native launch verification."
}
$manifestTarget = Get-AbsolutePath (Join-Path ([IO.Path]::GetDirectoryName($resolvedManifest)) $manifest.entrypoint)
if (-not $manifestTarget.Equals($resolvedTarget, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release manifest entrypoint does not match target: $manifestTarget"
}
$actualTargetHash = (Get-FileHash -LiteralPath $resolvedTarget -Algorithm SHA256).Hash.ToLowerInvariant()
$expectedTargetHash = [string]$manifest.entrypoint_sha256
if (-not $actualTargetHash.Equals($expectedTargetHash, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release target hash does not match the manifest. Refusing to replace the shortcut."
}

$resolvedDesktop = Get-AbsolutePath $DesktopPath
$shortcutPath = Join-Path $resolvedDesktop (Get-ShortcutFileName $ShortcutName)
$workingDirectory = [IO.Path]::GetDirectoryName($resolvedTarget)
$resolvedIcon = Get-AbsolutePath $IconPath
$iconExists = Test-Path -LiteralPath $resolvedIcon -PathType Leaf

if (-not $iconExists) {
    Write-Warning "Icon file not found; the application default icon will be used: $resolvedIcon"
}

Write-Output "ShortcutPath=$shortcutPath"
Write-Output "TargetPath=$resolvedTarget"
Write-Output "ManifestPath=$resolvedManifest"
Write-Output "ValidatedVersion=$($manifest.application_version)"
Write-Output "ValidatedSchema=$($manifest.database_schema_version)"
Write-Output "NativeLaunchVerified=$($manifest.native_launch_verified)"
Write-Output "TargetSha256=$actualTargetHash"
Write-Output "WorkingDirectory=$workingDirectory"
if ($iconExists) {
    Write-Output "IconLocation=$resolvedIcon"
} else {
    Write-Output "IconLocation=<application default>"
}
Write-Output "DryRun=$([bool]$DryRun)"

if ($DryRun) {
    return
}

if (-not (Test-Path -LiteralPath $resolvedDesktop -PathType Container)) {
    throw "Desktop directory was not found: $resolvedDesktop"
}

$shell = $null
$shortcut = $null
try {
    $shell = New-Object -ComObject WScript.Shell
    $temporaryShortcut = "$shortcutPath.$([Guid]::NewGuid().ToString('N')).tmp.lnk"
    $shortcut = $shell.CreateShortcut($temporaryShortcut)
    $shortcut.TargetPath = $resolvedTarget
    $shortcut.WorkingDirectory = $workingDirectory
    if ($iconExists) {
        $shortcut.IconLocation = "$resolvedIcon,0"
    }
    $shortcut.Save()
    Move-Item -LiteralPath $temporaryShortcut -Destination $shortcutPath -Force
    Write-Output "Created shortcut: $shortcutPath"
} finally {
    if ($null -ne $shortcut) {
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut)
    }
    if ($null -ne $shell) {
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
    }
    if ($null -ne $temporaryShortcut -and (Test-Path -LiteralPath $temporaryShortcut)) {
        Remove-Item -LiteralPath $temporaryShortcut -Force
    }
}
