#Requires -Version 5.1
<#
  Güncel dist\CinMuhasebe → D2 güncelleme ZIP + (varsa) USB CinMuhasebe klasörü.
  PG kurulum / DB / aktarım YOK. baglanti_ayari pakete girmez.
#>
param(
    [string]$RepoKok = "",
    [string]$CiktiZip = "",
    [string]$AppVersion = "",
    [switch]$UsbYok
)

$ErrorActionPreference = "Stop"
if (-not $RepoKok) {
    $RepoKok = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$Dist = Join-Path $RepoKok "dist\CinMuhasebe"
$Exe = Join-Path $Dist "CinMuhasebe.exe"
if (-not (Test-Path $Exe)) { throw "EXE yok: $Exe — once PyInstaller" }
if (-not (Test-Path (Join-Path $Dist "_internal"))) { throw "dist\_internal yok — eksik derleme" }

if (-not $AppVersion) {
    $brand = Get-Content (Join-Path $RepoKok "branding.py") -Raw -Encoding UTF8
    if ($brand -match 'APP_VERSION\s*=\s*"([^"]+)"') { $AppVersion = $Matches[1] } else { $AppVersion = "0.0.0" }
}

$Stamp = Get-Date -Format "yyyyMMdd_HHmm"
$PaketAd = "CinMuhasebe_DNM_D2_GUNCELLE_$Stamp"
$OutDir = Join-Path $RepoKok "paket"
$StageRoot = Join-Path $RepoKok "paket\_stage_d2_guncelle"
$StageApp = Join-Path $StageRoot $PaketAd
if (-not $CiktiZip) { $CiktiZip = Join-Path $OutDir "$PaketAd.zip" }

$sha = (Get-FileHash $Exe -Algorithm SHA256).Hash.ToUpperInvariant()
$mtime = (Get-Item $Exe).LastWriteTime.ToString("o")
$size = (Get-Item $Exe).Length

# BUILD_INFO (paket + dist)
$buildInfo = @"
APP_VERSION=$AppVersion
EXE_SHA256=$sha
EXE_SIZE=$size
EXE_MTIME=$mtime
BUILD_STAMP=$Stamp
BUILD_PC=$env:COMPUTERNAME
"@
Set-Content -Path (Join-Path $Dist "BUILD_INFO.txt") -Value $buildInfo -Encoding ASCII

if (Test-Path $StageRoot) { Remove-Item -Recurse -Force $StageRoot }
$stageDist = Join-Path $StageApp "CinMuhasebe"
$stageKur = Join-Path $StageApp "kurulum"
New-Item -ItemType Directory -Force -Path $stageDist, $stageKur, $OutDir | Out-Null

Write-Host "dist kopyalanıyor (canlı güncelleme YOK; yalnız paket)..."
$rc = Start-Process robocopy.exe -ArgumentList @(
    "`"$Dist`"", "`"$stageDist`"", "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS",
    "/XF", "baglanti_ayari.json", "kullanici_ayarlari.json", "ayarlar.json",
    "credentials.json", "evo_credentials.json", "evobulut_credentials.json",
    "veri_konumu.txt", "VERITABANI_KONUMU.txt", "ILK_YONETICI_SIFRE.txt",
    "*.db", "*.db-wal", "*.db-shm"
) -Wait -PassThru -NoNewWindow
if ($rc.ExitCode -ge 8) { throw "robocopy exit $($rc.ExitCode)" }

Copy-Item -Force (Join-Path $PSScriptRoot "00_D2_GUNCELLE.ps1") (Join-Path $stageKur "00_D2_GUNCELLE.ps1")
$sha | Set-Content (Join-Path $stageKur "BEKLENEN_SHA256.txt") -Encoding ASCII
Set-Content -Path (Join-Path $stageDist "BUILD_INFO.txt") -Value $buildInfo -Encoding ASCII

$CaSrc = Join-Path $env:APPDATA "postgresql\root.crt"
if (-not (Test-Path $CaSrc)) {
    $CaSrc = Join-Path $RepoKok "paket\_stage_d2_istemci\CinMuhasebe_DNM_D2_ISTEMCI_20261109_1504\kurulum\root.crt"
}
if (Test-Path $CaSrc) { Copy-Item -Force $CaSrc (Join-Path $stageKur "root.crt") }

@"
Cin Muhasebe — DNM D2 GÜNCELLEME paketi
=======================================
Sürüm       : $AppVersion
EXE SHA-256 : $sha
EXE mtime   : $mtime
EXE size    : $size
Kaynak      : $Dist
Üretim PC   : $env:COMPUTERNAME
Paket       : $PaketAd

Desteklenen makineler / roller
- DESKTOP-CGSE5GK → Ana Makine (host 127.0.0.1)
- DESKTOP-FL08BVD → Terminal 1 (host 192.168.1.114)
- DESKTOP-NB7SBPA → Terminal 2 (host 192.168.1.114)

USB: CinMuhasebe\GUNCELLE.cmd → rol seç → güncelle/kur → program açılır
ZIP: GUNCELLE_CALISTIR.bat veya kurulum\00_D2_GUNCELLE.ps1

Koruma
- PostgreSQL / DB oluşturma / restore YOK
- Evo aktarım / mali kayıt YOK
- Aktif baglanti_ayari.json ve kullanıcı ayarları korunur
- Yedek: %LOCALAPPDATA%\CinMuhasebe\DNM_D2_GERI_<zaman>
"@ | Set-Content (Join-Path $StageApp "OKU_BENI.txt") -Encoding UTF8

$manifest = @{
    format = "d2-guncelle-paket-v2"
    paket_ad = $PaketAd
    app_version = $AppVersion
    olusturma = (Get-Date -Format o)
    kaynak_makine = $env:COMPUTERNAME
    exe_path = $Exe
    exe_sha256 = $sha
    exe_mtime = $mtime
    exe_size = $size
    makineler = @("DESKTOP-CGSE5GK", "DESKTOP-FL08BVD", "DESKTOP-NB7SBPA")
    roller = @("ANA", "TERMINAL1", "TERMINAL2")
    pg_host_ana = "127.0.0.1"
    pg_host_terminal = "192.168.1.114"
    sistem_db = "cin_sistem_dnm_d2_20260901"
    firma_db = "cin_firma_dnm_d2_20260901"
    otomatik_aktarim = $false
    mali_kayit = $false
    betik = "kurulum\00_D2_GUNCELLE.ps1"
}
($manifest | ConvertTo-Json -Depth 5) | Set-Content (Join-Path $StageApp "PAKET_MANIFEST.json") -Encoding UTF8

$bat = @"
@echo off
setlocal
set "KOK=%~dp0"
if "%KOK:~-1%"=="\" set "KOK=%KOK:~0,-1%"
set "PS1=%KOK%\kurulum\00_D2_GUNCELLE.ps1"
if not exist "%PS1%" ( echo HATA: %PS1% & pause & exit /b 1 )
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -PaketKok "%KOK%" -Rol AUTO
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" ( echo Hata: %ERR% )
echo.
pause
exit /b %ERR%
"@
Set-Content -Path (Join-Path $StageApp "GUNCELLE_CALISTIR.bat") -Value $bat -Encoding ASCII

if (Test-Path $CiktiZip) { Remove-Item -Force $CiktiZip }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($StageApp, $CiktiZip)
$zipSha = (Get-FileHash $CiktiZip -Algorithm SHA256).Hash.ToUpperInvariant()

# USB: CinMuhasebe klasörü (sürücü harfi sabit değil)
$usbKok = $null
foreach ($letter in @('D', 'E', 'F', 'G', 'H')) {
    $cand = "${letter}:\CinMuhasebe"
    if (Test-Path $cand) { $usbKok = $cand; break }
}
$usbSurum = $null
$usbAktif = $null
$usbCmd = $null
if ($usbKok -and -not $UsbYok) {
    Write-Host "USB bulundu: $usbKok"
    $surumAd = "${AppVersion}_$Stamp"
    $usbSurum = Join-Path $usbKok "Surumler\$surumAd"
    $usbAktif = Join-Path $usbKok "SonGuncelleme\paket"
    $usbOnceki = Join-Path $usbKok ("SonGuncelleme\paket_onceki_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    New-Item -ItemType Directory -Force -Path (Split-Path $usbSurum) | Out-Null
    if (Test-Path $usbAktif) {
        if (Test-Path $usbOnceki) { Remove-Item -Recurse -Force $usbOnceki }
        Rename-Item $usbAktif (Split-Path $usbOnceki -Leaf) -ErrorAction SilentlyContinue
        if (Test-Path $usbAktif) {
            # rename fail → kopyala kenara
            New-Item -ItemType Directory -Force -Path $usbOnceki | Out-Null
            robocopy $usbAktif $usbOnceki /E /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
            Remove-Item -Recurse -Force $usbAktif
        } else {
            # renamed into SonGuncelleme\paket_onceki_* — move under SonGuncelleme
            $renamed = Join-Path (Split-Path $usbAktif) (Split-Path $usbOnceki -Leaf)
            if ((Test-Path $renamed) -and ($renamed -ne $usbOnceki)) {
                Move-Item $renamed $usbOnceki -Force -ErrorAction SilentlyContinue
            }
        }
    }
    New-Item -ItemType Directory -Force -Path $usbAktif, $usbSurum | Out-Null
    robocopy $StageApp $usbAktif /E /R:2 /W:2 /NFL /NDL /NJH /NJS | Out-Null
    robocopy $StageApp $usbSurum /E /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
    $usbCmd = Join-Path $usbKok "GUNCELLE.cmd"
    Copy-Item -Force (Join-Path $PSScriptRoot "GUNCELLE.cmd") $usbCmd
    Copy-Item -Force (Join-Path $PSScriptRoot "GUNCELLE_PAKET_SEC.ps1") (Join-Path $usbKok "GUNCELLE_PAKET_SEC.ps1")
    # Sürüm satırını CMD'ye gömmek için küçük not
    $usbOkun = @"
Cin Muhasebe USB — $AppVersion ($Stamp)
=====================================
GUNCELLE.cmd → rol seç → güncelle/kur
Aktif paket : SonGuncelleme\paket
Arsiv       : Surumler\$surumAd
EXE SHA256  : $sha

Ana Makine / Terminal 2: GUNCELLE.cmd → [2] veya [3]
Terminal 1 (bu uretim PC): masaüstü kısayolu veya [1] Otomatik
"@
    Set-Content (Join-Path $usbKok "OKU_BENI.txt") -Value $usbOkun -Encoding UTF8
    Write-Host "USB aktif: $usbAktif"
    Write-Host "USB GUNCELLE.cmd: $usbCmd"
} elseif (-not $UsbYok) {
    Write-Warning "USB CinMuhasebe klasoru bulunamadi — yerel paket hazir: $CiktiZip"
}

$son = @{
    format = "d2-guncelle-paket-son-v2"
    app_version = $AppVersion
    zip = $CiktiZip
    zip_sha256 = $zipSha
    exe = $Exe
    exe_sha256 = $sha
    exe_mtime = $mtime
    exe_size = $size
    paket_ad = $PaketAd
    stage = $StageApp
    betik = "kurulum\00_D2_GUNCELLE.ps1"
    usb_kok = $usbKok
    usb_surum = $usbSurum
    usb_aktif = $usbAktif
    usb_guncelle_cmd = $usbCmd
}
($son | ConvertTo-Json) | Set-Content (Join-Path $OutDir "D2_GUNCELLE_PAKET_SON.json") -Encoding UTF8
($son | ConvertTo-Json) | Set-Content (Join-Path $OutDir "D2_SON_DAGITIM_$AppVersion.json") -Encoding UTF8
Write-Host "ZIP: $CiktiZip"
Write-Host "ZIP SHA: $zipSha"
Write-Host "EXE SHA: $sha"
Write-Host "SURUM: $AppVersion"
Write-Host "STAGE: $StageApp"
