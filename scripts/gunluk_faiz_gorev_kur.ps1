# Cin Muhasebe — günlük faiz Windows görev zamanlayıcısı (DOC2-19)
# Tek görev adı; her sürümde çoğalmaz (Unregister + Register veya Update).
# Kullanım:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\gunluk_faiz_gorev_kur.ps1
#   ... -ExePath "C:\path\CinMuhasebe.exe"
#   ... -DryRun

[CmdletBinding()]
param(
    [string]$ExePath = "",
    [string]$TaskName = "CinMuhasebe_GunlukFaiz",
    [string]$Time = "00:10",
    [switch]$DryRun,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

function Resolve-ProjectRoot {
    $here = $PSScriptRoot
    if (-not $here) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    return (Resolve-Path (Join-Path $here "..")).Path
}

function Resolve-FaizTarget {
    param([string]$Explicit, [string]$Root)

    if ($Explicit) {
        $p = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Explicit)
        if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {
            throw "Belirtilen EXE bulunamadı: $p"
        }
        $full = (Resolve-Path -LiteralPath $p).Path
        return @{
            TargetPath       = $full
            Arguments        = "--gunluk-faiz"
            WorkingDirectory = (Split-Path -Parent $full)
            Kind             = "exe"
        }
    }

    $exeCandidates = @(
        (Join-Path $Root "dist\CinMuhasebe\CinMuhasebe.exe"),
        (Join-Path $Root "dist\CinMuhasebe.exe"),
        (Join-Path $Root "CinMuhasebe.exe")
    )
    foreach ($c in $exeCandidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) {
            $full = (Resolve-Path -LiteralPath $c).Path
            return @{
                TargetPath       = $full
                Arguments        = "--gunluk-faiz"
                WorkingDirectory = (Split-Path -Parent $full)
                Kind             = "exe"
            }
        }
    }

    $py = Join-Path $Root ".venv\Scripts\python.exe"
    $mainPy = Join-Path $Root "main.py"
    if ((Test-Path -LiteralPath $py -PathType Leaf) -and (Test-Path -LiteralPath $mainPy -PathType Leaf)) {
        return @{
            TargetPath       = (Resolve-Path -LiteralPath $py).Path
            Arguments        = "`"$mainPy`" --gunluk-faiz"
            WorkingDirectory = $Root
            Kind             = "python"
        }
    }

    throw "CinMuhasebe.exe veya .venv\Scripts\python.exe + main.py bulunamadı: $Root"
}

$Root = Resolve-ProjectRoot
$target = Resolve-FaizTarget -Explicit $ExePath -Root $Root

Write-Host "Proje: $Root"
Write-Host "Hedef: $($target.TargetPath) $($target.Arguments)"
Write-Host "Görev: $TaskName @ $Time (Europe/Istanbul iş günü sınırına uygun yerel saat)"

if ($Remove) {
    if ($DryRun) {
        Write-Host "[DryRun] Unregister-ScheduledTask $TaskName"
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Görev kaldırıldı (varsa): $TaskName"
    exit 0
}

if ($DryRun) {
    Write-Host "[DryRun] Görev kurulmayacak."
    exit 0
}

# Mevcut görevi kaldırıp yeniden kur — sürüm güncellemesinde çoğalmaz
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute $target.TargetPath `
    -Argument $target.Arguments `
    -WorkingDirectory $target.WorkingDirectory

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Cin Muhasebe günlük faiz / kaçırılan gün tamamlaması (--gunluk-faiz). Yeniden kurulum aynı adı günceller." `
    -Force | Out-Null

Write-Host "Tamam: görev '$TaskName' her gün $Time saatinde çalışacak."
Write-Host "PC kapalıysa sonraki açılışta StartWhenAvailable ile tetiklenir; uygulama açılışı da gap fill yapar."
