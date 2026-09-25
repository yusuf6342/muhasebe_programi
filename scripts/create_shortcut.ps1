# Cin Muhasebe — masaüstü ve Başlat menüsü kısayolu
# Kullanım:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1 -ExePath "C:\path\CinMuhasebe.exe"
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1 -DryRun
#
# EXE yoksa otomatik olarak calistir.bat (veya pythonw + main.py) kullanılır.

[CmdletBinding()]
param(
    [string]$ExePath = "",
    [switch]$DryRun,
    [switch]$SkipStartMenu
)

$ErrorActionPreference = "Stop"
$ShortcutName = "Cin Muhasebe.lnk"
$Description = "Cin Muhasebe Programı"

function Resolve-ProjectRoot {
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    return (Resolve-Path (Join-Path $here "..")).Path
}

function Resolve-LaunchTarget {
    param([string]$Explicit, [string]$Root)

    if ($Explicit) {
        $p = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Explicit)
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
            throw "Belirtilen hedef bulunamadı: $p"
        }
        $full = (Resolve-Path -LiteralPath $p).Path
        return @{
            TargetPath      = $full
            Arguments       = ""
            WorkingDirectory = (Split-Path -Parent $full)
            Kind            = "explicit"
        }
    }

    $exeCandidates = @(
        (Join-Path $Root "dist\CinMuhasebe\CinMuhasebe.exe"),
        (Join-Path $Root "dist\CinMuhasebe.exe"),
        (Join-Path $Root "build\CinMuhasebe.exe"),
        (Join-Path $Root "CinMuhasebe.exe")
    )
    foreach ($c in $exeCandidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) {
            $full = (Resolve-Path -LiteralPath $c).Path
            return @{
                TargetPath       = $full
                Arguments        = ""
                WorkingDirectory = (Split-Path -Parent $full)
                Kind             = "exe"
            }
        }
    }

    $bat = Join-Path $Root "calistir.bat"
    if (Test-Path -LiteralPath $bat -PathType Leaf) {
        $full = (Resolve-Path -LiteralPath $bat).Path
        return @{
            TargetPath       = $full
            Arguments        = ""
            WorkingDirectory = $Root
            Kind             = "bat"
        }
    }

    $mainPy = Join-Path $Root "main.py"
    if (-not (Test-Path -LiteralPath $mainPy -PathType Leaf)) {
        throw "Ne CinMuhasebe.exe ne calistir.bat ne main.py bulundu: $Root"
    }

    $pythonw = $null
    foreach ($cand in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\pythonw.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\pythonw.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\pythonw.exe")
    )) {
        if (Test-Path -LiteralPath $cand) { $pythonw = $cand; break }
    }
    if (-not $pythonw) {
        $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
        if ($cmd) { $pythonw = $cmd.Source }
    }
    if (-not $pythonw) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd) { $pythonw = $cmd.Source }
    }
    if (-not $pythonw) {
        throw "Python bulunamadı. https://www.python.org/downloads/"
    }

    return @{
        TargetPath       = $pythonw
        Arguments        = "`"$mainPy`""
        WorkingDirectory = $Root
        Kind             = "python"
    }
}

$root = Resolve-ProjectRoot
$launch = Resolve-LaunchTarget -Explicit $ExePath -Root $root

# Masaüstü kısayolu için ICO gerekir; PNG (CinLogo.png) kısayol ikonu olarak güvenilir değildir.
$icoCandidates = @(
    (Join-Path $root "assets\branding\CinLogo.ico"),
    (Join-Path $root "assets\branding\cin_muhasebe.ico")
)
$ico = $null
foreach ($c in $icoCandidates) {
    if (Test-Path -LiteralPath $c) { $ico = $c; break }
}
if ($ico) {
    $iconLocation = "$ico,0"
} elseif ($launch.Kind -eq "exe") {
    $iconLocation = "$($launch.TargetPath),0"
} else {
    Write-Warning "CinLogo.ico bulunamadı. Kısayol için assets\branding\CinLogo.ico ekleyin (PNG EXE/kısayol ikonu olmaz)."
    $pyIcon = $null
    foreach ($cand in @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\pythonw.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\pythonw.exe")
    )) {
        if (Test-Path -LiteralPath $cand) { $pyIcon = $cand; break }
    }
    if ($pyIcon) {
        $iconLocation = "$pyIcon,0"
    } else {
        $iconLocation = "$env:SystemRoot\System32\shell32.dll,24"
    }
}

$desktop = [Environment]::GetFolderPath("Desktop")
$desktopLnk = Join-Path $desktop $ShortcutName
$startMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
$startLnk = Join-Path $startMenu $ShortcutName

Write-Host "Hedef türü: $($launch.Kind)"
Write-Host "Target: $($launch.TargetPath)"
if ($launch.Arguments) { Write-Host "Args: $($launch.Arguments)" }
Write-Host "WorkDir: $($launch.WorkingDirectory)"
Write-Host "Icon: $iconLocation"
Write-Host "Desktop: $desktopLnk"

if ($DryRun) {
    Write-Host "DryRun: kısayol yazılmadı."
    exit 0
}

$shell = New-Object -ComObject WScript.Shell

function New-CinShortcut {
    param([string]$LnkPath)
    $dir = Split-Path -Parent $LnkPath
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    if (-not (Test-Path -LiteralPath $launch.TargetPath -PathType Leaf)) {
        throw "Kısayol oluşturulamaz; hedef yok: $($launch.TargetPath)"
    }
    $s = $shell.CreateShortcut($LnkPath)
    $s.TargetPath = $launch.TargetPath
    $s.Arguments = $launch.Arguments
    $s.WorkingDirectory = $launch.WorkingDirectory
    $s.WindowStyle = 1
    $s.Description = $Description
    $s.IconLocation = $iconLocation
    $s.Save()
    return (Resolve-Path -LiteralPath $LnkPath).Path
}

$created = @()
$created += New-CinShortcut -LnkPath $desktopLnk
if (-not $SkipStartMenu) {
    $created += New-CinShortcut -LnkPath $startLnk
}

# Eski adla kalan kısayolu da aynı hedefe güncelle
$eski = Join-Path $desktop "Muhasebe Programi.lnk"
if (Test-Path -LiteralPath $eski) {
    $created += New-CinShortcut -LnkPath $eski
    Write-Host "Eski 'Muhasebe Programi.lnk' güncellendi."
}

Write-Host ""
Write-Host "Kısayollar hazır:"
$created | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "Not: EXE yoksa kısayol calistir.bat ile açılır (konsol penceresi normal)."
