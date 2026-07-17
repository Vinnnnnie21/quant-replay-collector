[CmdletBinding()]
param(
    [string]$TargetPath = "",
    [string]$DesktopPath = [Environment]::GetFolderPath("Desktop"),
    [string]$IconPath = "",
    [string]$ShortcutName = "QRC",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($TargetPath)) {
    $TargetPath = Join-Path $scriptRoot "..\quant_collector_app\dist\QRC.exe"
}
if ([string]::IsNullOrWhiteSpace($IconPath)) {
    $IconPath = Join-Path $scriptRoot "..\quant_collector_app\assets\app_icon.ico"
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
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $resolvedTarget
    $shortcut.WorkingDirectory = $workingDirectory
    if ($iconExists) {
        $shortcut.IconLocation = "$resolvedIcon,0"
    }
    $shortcut.Save()
    Write-Output "Created shortcut: $shortcutPath"
} finally {
    if ($null -ne $shortcut) {
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut)
    }
    if ($null -ne $shell) {
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell)
    }
}
