#Requires -Version 5.1
<#
  Güncel dist\CinMuhasebe → D2 güncelleme ZIP'i.
  İçinde tek betik: 00_D2_GUNCELLE.ps1 (3 makine kimliği).
  PG kurulum / DB oluşturma / aktarım YOK.
#>
param(
    [string]$RepoKok = "",
    [string]$CiktiZip = ""
)

$ErrorActionPreference = "Stop"
if (-not $RepoKok) {
    $RepoKok = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$Dist = Join-Path $RepoKok "dist\CinMuhasebe"
$Exe = Join-Path $Dist "CinMuhasebe.exe"
if (-not (Test-Path $Exe)) { throw "EXE yok: $Exe — once PyInstaller" }

$Stamp = Get-Date -Format "yyyyMMdd_HHmm"
$PaketAd = "CinMuhasebe_DNM_D2_GUNCELLE_$Stamp"
$OutDir = Join-Path $RepoKok "paket"
$StageRoot = Join-Path $RepoKok "paket\_stage_d2_guncelle"
$StageApp = Join-Path $StageRoot $PaketAd
if (-not $CiktiZip) { $CiktiZip = Join-Path $OutDir "$PaketAd.zip" }

$sha = (Get-FileHash $Exe -Algorithm SHA256).Hash.ToUpperInvariant()
$mtime = (Get-Item $Exe).LastWriteTime.ToString("o")
$size = (Get-Item $Exe).Length

if (Test-Path $StageRoot) { Remove-Item -Recurse -Force $StageRoot }
$stageDist = Join-Path $StageApp "CinMuhasebe"
$stageKur = Join-Path $StageApp "kurulum"
New-Item -ItemType Directory -Force -Path $stageDist, $stageKur, $OutDir | Out-Null

Write-Host "dist kopyalanıyor (canlı güncelleme YOK; yalnız ZIP; 00_D2_GUNCELLE.ps1 çalıştırılmaz)..."
# Kullanıcı verisi / DB / bağlantı / yazıcı tercihleri pakete girmez
$rc = Start-Process robocopy.exe -ArgumentList @(
    "`"$Dist`"", "`"$stageDist`"", "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS",
    "/XF", "baglanti_ayari.json", "kullanici_ayarlari.json", "ayarlar.json",
    "credentials.json", "evo_credentials.json", "evobulut_credentials.json",
    "veri_konumu.txt", "VERITABANI_KONUMU.txt", "ILK_YONETICI_SIFRE.txt",
    "*.db", "*.db-wal", "*.db-shm"
) -Wait -PassThru -NoNewWindow
if ($rc.ExitCode -ge 8) { throw "robocopy exit $($rc.ExitCode)" }

$guncelle = @'
#Requires -Version 5.1
<#
  D2 program güncellemesi — tek betik, makine kimliğine göre.
  - DESKTOP-CGSE5GK (ana): host 127.0.0.1 korunur
  - DESKTOP-FL08BVD / DESKTOP-NB7SBPA (terminal): host 192.168.1.114 korunur
  PG kurulumu, DB oluşturma/geri yükleme, Evo aktarım, mali kayıt YOK.
  Aktif baglanti_ayari.json, kullanıcı ayarları, sertifika ve kimlik bilgileri korunur.
#>
param(
    [string]$PaketKok = "",
    [switch]$Force
)
$ErrorActionPreference = "Stop"

$MakineProfil = @{
    "DESKTOP-CGSE5GK" = @{
        Rol = "ANA"
        KisayolAdi = "CİN MUHASEBE — DNM D2 — ANA"
        BeklenenHost = "127.0.0.1"
        TerminalKimligi = "DNM-D2-ANA"
    }
    "DESKTOP-FL08BVD" = @{
        Rol = "TERMINAL"
        KisayolAdi = "CİN MUHASEBE — DNM D2 — TERMINAL"
        BeklenenHost = "192.168.1.114"
        TerminalKimligi = "DNM-D2-FL08BVD"
    }
    "DESKTOP-NB7SBPA" = @{
        Rol = "TERMINAL"
        KisayolAdi = "CİN MUHASEBE — DNM D2 — TERMINAL"
        BeklenenHost = "192.168.1.114"
        TerminalKimligi = "DNM-D2-NB7SBPA"
    }
}

$Pc = $env:COMPUTERNAME
Write-Host "PC=$Pc"
if (-not $MakineProfil.ContainsKey($Pc)) {
    throw "YANLIS MAKINE: desteklenenler DESKTOP-CGSE5GK / DESKTOP-FL08BVD / DESKTOP-NB7SBPA. Su an: $Pc"
}
$Prof = $MakineProfil[$Pc]
Write-Host ("Rol={0} beklenen_host={1}" -f $Prof.Rol, $Prof.BeklenenHost)

if (-not $PaketKok) {
    $PaketKok = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $PaketKok "CinMuhasebe\CinMuhasebe.exe"))) { $PaketKok = $PSScriptRoot }
}
$Src = Join-Path $PaketKok "CinMuhasebe"
$SrcExe = Join-Path $Src "CinMuhasebe.exe"
if (-not (Test-Path $SrcExe)) { throw "EXE yok: $SrcExe" }

$BeklenenSha = Get-Content (Join-Path $PSScriptRoot "BEKLENEN_SHA256.txt") -ErrorAction SilentlyContinue |
    Select-Object -First 1
$SrcSha = (Get-FileHash $SrcExe -Algorithm SHA256).Hash.ToUpperInvariant()
if ($BeklenenSha -and ($SrcSha -ne $BeklenenSha.Trim().ToUpperInvariant()) -and -not $Force) {
    throw "EXE SHA uyusmuyor. Beklenen=$BeklenenSha Gelen=$SrcSha (Force ile gecebilirsiniz)"
}

$HedefKok = Join-Path $env:LOCALAPPDATA "CinMuhasebe\DNM_D2"
$HedefApp = Join-Path $HedefKok "CinMuhasebe"
$HedefExe = Join-Path $HedefApp "CinMuhasebe.exe"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Geri = Join-Path $env:LOCALAPPDATA "CinMuhasebe\DNM_D2_GERI_$Stamp"
New-Item -ItemType Directory -Force -Path $HedefKok, $Geri | Out-Null

Write-Host "Koruma: PG/DB dokunulmaz; mali kayit yok; baglanti_ayari.json korunur"

# Acik uygulamayi nazikce kapat (kullanici oturumu / Stop-Process -Force YOK)
Get-Process CinMuhasebe -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Nazik kapanis isteniyor PID=$($_.Id)"
    try { $_.CloseMainWindow() | Out-Null } catch {}
}
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    $alive = @(Get-Process CinMuhasebe -ErrorAction SilentlyContinue)
    if ($alive.Count -eq 0) { break }
    Start-Sleep -Seconds 2
}
$alive = @(Get-Process CinMuhasebe -ErrorAction SilentlyContinue)
if ($alive.Count -gt 0) {
    throw ("CinMuhasebe hala acik (PID={0}). Kaydedip kapatip yeniden calistirin; zorla kapatma yapilmaz." -f ($alive.Id -join ","))
}
Start-Sleep -Seconds 1

# --- yedek: program + ayarlar ---
if (Test-Path $HedefApp) {
    robocopy $HedefApp (Join-Path $Geri "CinMuhasebe") /E /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
}
Get-ChildItem $HedefKok -Filter "baglanti*.json" -ErrorAction SilentlyContinue | Copy-Item -Destination $Geri -Force
$Desk = [Environment]::GetFolderPath("Desktop")
Get-ChildItem $Desk -Filter "*.lnk" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "*MUHASEBE*" -or $_.Name -like "*Cin*" -or $_.Name -like "*DNM*" } |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $Geri $_.Name) -Force }

$CaDir = Join-Path $env:APPDATA "postgresql"
$CaPath = Join-Path $CaDir "root.crt"
if (Test-Path $CaPath) { Copy-Item -Force $CaPath (Join-Path $Geri "root.crt") }

# Aktif baglanti + olasi kullanıcı ayarlarını kenara al (robocopy üzerine yazmasın)
$Korunan = Join-Path $Geri "_korunan_aktif"
New-Item -ItemType Directory -Force -Path $Korunan | Out-Null
$KorunanDosyalar = @(
    (Join-Path $HedefApp "baglanti_ayari.json"),
    (Join-Path $HedefKok "baglanti_ayari.json"),
    (Join-Path $HedefApp "kullanici_ayarlari.json"),
    (Join-Path $HedefApp "ayarlar.json"),
    (Join-Path $HedefApp "credentials.json"),
    (Join-Path $HedefApp "evo_credentials.json"),
    (Join-Path $HedefApp "evobulut_credentials.json")
)
foreach ($p in $KorunanDosyalar) {
    if (Test-Path $p) {
        $rel = $p.Substring($HedefKok.Length).TrimStart('\')
        $dest = Join-Path $Korunan $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
        Copy-Item -Force $p $dest
        Write-Host "Korundu: $rel"
    }
}
# keyring / credential store dokunulmaz (Windows Credential Manager)

# Program dosyalarını güncelle
New-Item -ItemType Directory -Force -Path $HedefApp | Out-Null
$rc2 = Start-Process robocopy.exe -ArgumentList @(
    "`"$Src`"", "`"$HedefApp`"", "/E", "/R:2", "/W:2", "/NFL", "/NDL", "/NJH", "/NJS"
) -Wait -PassThru -NoNewWindow
if ($rc2.ExitCode -ge 8) { throw "robocopy guncelleme exit $($rc2.ExitCode)" }

# Korunan ayarları geri yaz
Get-ChildItem $Korunan -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    $rel = $_.FullName.Substring($Korunan.Length).TrimStart('\')
    $dest = Join-Path $HedefKok $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Copy-Item -Force $_.FullName $dest
    Write-Host "Geri yazildi: $rel"
}

# baglanti_ayari.json yoksa oluşturma — mevcut aktif profil zorunlu korunur.
# Yalnız örnek profil (bilinçli inceleme için) güncellenir; host makineye göre.
$Ornek = @{
    kipi = "yerel_ag_postgres"
    schema_surum = 1
    profil_adi = "DNM İKİNCİ DÖNEM DENEME"
    postgres = @{
        host = $Prof.BeklenenHost
        port = 5432
        sistem_db = "cin_sistem_dnm_d2_20260901"
        firma_db = "cin_firma_dnm_d2_20260901"
        kullanici = "cin_app"
        sslmode = "verify-full"
        ortam = "DENEME"
        terminal_kimligi = $Prof.TerminalKimligi
    }
    otomatik_aktarim = $false
    sqlite_zorlama_yok = $true
}
$Ornek | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $HedefKok "baglanti_ayari.D2_ORNEK.json") -Encoding UTF8

# Aktif baglanti host doğrulama (değiştirmeden uyar)
$AktifBag = Join-Path $HedefApp "baglanti_ayari.json"
if (-not (Test-Path $AktifBag)) { $AktifBag = Join-Path $HedefKok "baglanti_ayari.json" }
if (Test-Path $AktifBag) {
    try {
        $aktif = Get-Content $AktifBag -Raw -Encoding UTF8 | ConvertFrom-Json
        $h = [string]$aktif.postgres.host
        Write-Host "Aktif baglanti host=$h db=$($aktif.postgres.sistem_db)/$($aktif.postgres.firma_db)"
        if ($h -and ($h -ne $Prof.BeklenenHost) -and -not $Force) {
            Write-Warning "Aktif host ($h) beklenen $($Prof.BeklenenHost) degil — DOSYA DEGISTIRILMEDI. Kontrol edin."
        }
        $sd = [string]$aktif.postgres.sistem_db
        $fd = [string]$aktif.postgres.firma_db
        if ($sd -and $sd -ne "cin_sistem_dnm_d2_20260901") {
            Write-Warning "Aktif sistem_db beklenmeyen: $sd — DOSYA DEGISTIRILMEDI."
        }
        if ($fd -and $fd -ne "cin_firma_dnm_d2_20260901") {
            Write-Warning "Aktif firma_db beklenmeyen: $fd — DOSYA DEGISTIRILMEDI."
        }
    } catch {
        Write-Warning "baglanti_ayari.json okunamadi: $_"
    }
} else {
    Write-Warning "Aktif baglanti_ayari.json bulunamadi; ornek profil yazildi. Bilinçli kopyalayın."
}

# Sertifika: mevcut root.crt korunur; yoksa paketten kopyala
$CaSrc = Join-Path $PSScriptRoot "root.crt"
if (-not (Test-Path $CaPath) -and (Test-Path $CaSrc)) {
    New-Item -ItemType Directory -Force -Path $CaDir | Out-Null
    Copy-Item -Force $CaSrc $CaPath
    Write-Host "root.crt ilk kez kopyalandi"
} elseif (Test-Path $CaPath) {
    Write-Host "Mevcut root.crt korundu"
}

# Masaüstü kısayolları → güncel DNM_D2 EXE (profil adı + ana "Cin Muhasebe.lnk")
$Wsh = New-Object -ComObject WScript.Shell
$DeskList = @(
    $Desk,
    [Environment]::GetFolderPath('CommonDesktopDirectory'),
    (Join-Path $env:USERPROFILE 'Desktop'),
    (Join-Path $env:USERPROFILE 'OneDrive\Masaüstü')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
$KisayolAdlari = @($Prof.KisayolAdi, 'Cin Muhasebe')
foreach ($D in $DeskList) {
    foreach ($Ad in $KisayolAdlari) {
        $LnkPath = Join-Path $D "$Ad.lnk"
        if (-not (Test-Path $LnkPath) -and $Ad -ne $Prof.KisayolAdi) { continue }
        if (Test-Path $LnkPath) { Copy-Item $LnkPath (Join-Path $Geri "$Ad.lnk.bak") -Force -ErrorAction SilentlyContinue }
        $Lnk = $Wsh.CreateShortcut($LnkPath)
        $Lnk.TargetPath = $HedefExe
        $Lnk.WorkingDirectory = $HedefApp
        $Lnk.Arguments = ''
        $Lnk.IconLocation = "$HedefExe,0"
        $Lnk.Description = "Cin Muhasebe — DNM_D2 ($($Prof.Rol))"
        $Lnk.Save()
        Write-Host "Kisayol: $LnkPath"
    }
}
$LnkPath = Join-Path $Desk "$($Prof.KisayolAdi).lnk"

$YeniSha = (Get-FileHash $HedefExe -Algorithm SHA256).Hash.ToUpperInvariant()
$Sonuc = @{
    format = "d2-guncelleme-sonuc-v1"
    zaman = (Get-Date -Format o)
    makine = $Pc
    rol = $Prof.Rol
    hedef_exe = $HedefExe
    exe_sha256 = $YeniSha
    paket_sha_beklenen = $BeklenenSha
    yedek = $Geri
    baglanti_korundu = (Test-Path $AktifBag)
    kisayol = $LnkPath
}
($Sonuc | ConvertTo-Json -Depth 5) | Set-Content (Join-Path $HedefKok "SON_GUNCELLEME.json") -Encoding UTF8
($Sonuc | ConvertTo-Json -Depth 5) | Set-Content (Join-Path $Geri "SON_GUNCELLEME.json") -Encoding UTF8

Write-Host "GUNCELLEME TAMAM"
Write-Host "EXE: $HedefExe"
Write-Host "SHA: $YeniSha"
Write-Host "Yedek: $Geri"
Write-Host "Kisayol: $LnkPath"
if ($YeniSha -ne $SrcSha) { throw "Hedef EXE SHA kaynakla uyusmuyor" }
'@

Set-Content -Path (Join-Path $stageKur "00_D2_GUNCELLE.ps1") -Value $guncelle -Encoding UTF8
$sha | Set-Content (Join-Path $stageKur "BEKLENEN_SHA256.txt") -Encoding ASCII

$CaSrc = Join-Path $env:APPDATA "postgresql\root.crt"
if (-not (Test-Path $CaSrc)) {
    $CaSrc = Join-Path $RepoKok "paket\_stage_d2_istemci\CinMuhasebe_DNM_D2_ISTEMCI_20261109_1504\kurulum\root.crt"
}
if (Test-Path $CaSrc) { Copy-Item -Force $CaSrc (Join-Path $stageKur "root.crt") }

@"
Cin Muhasebe — DNM D2 GÜNCELLEME paketi
=======================================
EXE SHA-256 : $sha
EXE mtime   : $mtime
EXE size    : $size
Kaynak      : $Dist
Üretim PC   : $env:COMPUTERNAME
Paket       : $PaketAd

Desteklenen makineler
- DESKTOP-CGSE5GK (ana)     → host 127.0.0.1
- DESKTOP-FL08BVD (terminal)→ host 192.168.1.114
- DESKTOP-NB7SBPA (terminal)→ host 192.168.1.114

DB (degismez)
- cin_sistem_dnm_d2_20260901
- cin_firma_dnm_d2_20260901

Güncelleme
powershell -ExecutionPolicy Bypass -File .\kurulum\00_D2_GUNCELLE.ps1

Koruma
- PostgreSQL kurulumu / DB oluşturma / restore YOK
- Evo aktarım / mali kayıt YOK
- Aktif baglanti_ayari.json, kullanıcı ayarları, sertifika, kimlik bilgileri korunur
- Önce yedek: %LOCALAPPDATA%\CinMuhasebe\DNM_D2_GERI_<zaman>
"@ | Set-Content (Join-Path $StageApp "OKU_BENI.txt") -Encoding UTF8

$manifest = @{
    format = "d2-guncelle-paket-v1"
    paket_ad = $PaketAd
    olusturma = (Get-Date -Format o)
    kaynak_makine = $env:COMPUTERNAME
    exe_path = $Exe
    exe_sha256 = $sha
    exe_mtime = $mtime
    exe_size = $size
    makineler = @("DESKTOP-CGSE5GK", "DESKTOP-FL08BVD", "DESKTOP-NB7SBPA")
    pg_host_ana = "127.0.0.1"
    pg_host_terminal = "192.168.1.114"
    sistem_db = "cin_sistem_dnm_d2_20260901"
    firma_db = "cin_firma_dnm_d2_20260901"
    otomatik_aktarim = $false
    mali_kayit = $false
    betik = "kurulum\00_D2_GUNCELLE.ps1"
}
($manifest | ConvertTo-Json -Depth 5) | Set-Content (Join-Path $StageApp "PAKET_MANIFEST.json") -Encoding UTF8

# UNC ag yolundan calisan baslatici (cd /d UNC basarisiz — tam yol + -PaketKok)
$bat = @"
@echo off
REM UNC ag yolundan da calisir (cd /d UNC basarisiz olur).
setlocal
set "KOK=%~dp0"
set "STAGE=%KOK%stage"
REM %~dp0 sonunda \ vardir; ayri 'stage' alt klasoru yok — paket kokunu kullan
set "STAGE=%KOK%"
if "%STAGE:~-1%"=="\" set "STAGE=%STAGE:~0,-1%"
set "PS1=%STAGE%\kurulum\00_D2_GUNCELLE.ps1"
if not exist "%PS1%" (
  echo HATA: Betik bulunamadi:
  echo   %PS1%
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -PaketKok "%STAGE%"
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo.
  echo Guncelleme hata kodu: %ERR%
)
echo.
pause
exit /b %ERR%
"@
Set-Content -Path (Join-Path $StageApp "GUNCELLE_CALISTIR.bat") -Value $bat -Encoding ASCII

if (Test-Path $CiktiZip) { Remove-Item -Force $CiktiZip }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($StageApp, $CiktiZip)
$zipSha = (Get-FileHash $CiktiZip -Algorithm SHA256).Hash.ToUpperInvariant()

$son = @{
    zip = $CiktiZip
    zip_sha256 = $zipSha
    exe = $Exe
    exe_sha256 = $sha
    exe_mtime = $mtime
    exe_size = $size
    paket_ad = $PaketAd
    stage = $StageApp
    betik = "kurulum\00_D2_GUNCELLE.ps1"
}
($son | ConvertTo-Json) | Set-Content (Join-Path $OutDir "D2_GUNCELLE_PAKET_SON.json") -Encoding UTF8
Write-Host "ZIP: $CiktiZip"
Write-Host "ZIP SHA: $zipSha"
Write-Host "EXE SHA: $sha"
Write-Host "STAGE: $StageApp"
