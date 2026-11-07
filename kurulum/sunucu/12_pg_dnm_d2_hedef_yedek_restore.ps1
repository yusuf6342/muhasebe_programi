# DNM D2 — boş sistem/firma DB + dump → ayrı restore_test (mali yazım yok)
# Tercihen ANA MAKİNE (DESKTOP-CGSE5GK) yönetici PowerShell; PgHost=127.0.0.1
# Terminalden: PgHost=192.168.1.114 (postgres pg_hba izinliyse)
#
# cin_app'e CREATEDB / SUPERUSER VERİLMEZ.
# Parola: MUHASEBE_PG_SUPER_PASSWORD veya Read-Host SecureString (sohbet/log yok).
# Mevcut hedef DB varsa içeriği incelemeden SİLMEZ / üzerine yazmaz.
# Günlük/kabul/RAY/D1 adlarına dokunmaz.
#
#   .\kurulum\sunucu\12_pg_dnm_d2_hedef_yedek_restore.ps1
#   .\kurulum\sunucu\12_pg_dnm_d2_hedef_yedek_restore.ps1 -PgHost 127.0.0.1

param(
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres",
    [string]$AppUser = "cin_app",
    [string]$SistemDb = "cin_sistem_dnm_d2_20260901",
    [string]$FirmaDb = "cin_firma_dnm_d2_20260901",
    [string]$RestoreSistem = "cin_sistem_dnm_d2_restore_test",
    [string]$RestoreFirma = "cin_firma_dnm_d2_restore_test",
    [string]$YedekKok = "$env:LOCALAPPDATA\CinMuhasebeTest\yedekler_pg_d2"
)

$ErrorActionPreference = "Stop"
Write-Host "=== DNM D2 hedef + yedek/restore (CREATEDB cin_app'e yok) ===" -ForegroundColor Cyan
Write-Host "Makine: $env:COMPUTERNAME | PgHost=$PgHost"

$Korunan = @(
    "cin_sistem", "cin_firma_ray", "postgres",
    "cin_sistem_deneme", "cin_firma_deneme",
    "cin_sistem_kabul_20261105", "cin_firma_kabul_20261105",
    "cin_sistem_restore_20261105", "cin_firma_restore_20261105",
    "cin_sistem_dnm_d1_20260831", "cin_firma_dnm_d1_20260831"
)

foreach ($ad in @($SistemDb, $FirmaDb, $RestoreSistem, $RestoreFirma)) {
    if ($ad -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$') { throw "Gecersiz DB adi: $ad" }
    if ($ad -in $Korunan) { throw "Hedef korunan ada carpti: $ad" }
}
if ($SistemDb -eq $FirmaDb) { throw "Sistem ve firma ayni olamaz" }

function Find-PgBin([string]$exe) {
    foreach ($a in @(
        "C:\Program Files\PostgreSQL\17\bin\$exe",
        "C:\Program Files\PostgreSQL\16\bin\$exe",
        "C:\Program Files\PostgreSQL\18\bin\$exe"
    )) { if (Test-Path $a) { return $a } }
    $cmd = Get-Command ($exe -replace '\.exe$','') -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$psql = Find-PgBin "psql.exe"
$pgDump = Find-PgBin "pg_dump.exe"
$pgRestore = Find-PgBin "pg_restore.exe"
if (-not $psql) { throw "psql yok" }
if (-not $pgDump) { throw "pg_dump yok" }
if (-not $pgRestore) { throw "pg_restore yok" }

$env:PGPASSWORD = $env:MUHASEBE_PG_SUPER_PASSWORD
if (-not $env:PGPASSWORD) {
    $secure = Read-Host "PostgreSQL superuser ($SuperUser) parolasi" -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

$rolVar = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$AppUser'"
if ($rolVar -notmatch "1") {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    throw "Uygulama rolu yok: $AppUser"
}
# Yetki genisletme YOK
$yetki = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc `
    "SELECT rolcreatedb::text || ',' || rolsuper::text FROM pg_roles WHERE rolname='$AppUser'"
Write-Host "cin_app rolcreatedb,rolsuper=$($yetki.Trim()) (degistirilmez)"

function Db-Exists([string]$name) {
    $v = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$name'"
    return ($v -match "1")
}

function Ensure-EmptyDb([string]$name) {
    if (Db-Exists $name) {
        Write-Host "Zaten var (dokunulmadi): $name" -ForegroundColor Yellow
        return "MEVCUT"
    }
    Write-Host "CREATE DATABASE $name OWNER $AppUser ..."
    & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -c `
        "CREATE DATABASE $name OWNER $AppUser;"
    if ($LASTEXITCODE -ne 0) { throw "CREATE DATABASE basarisiz: $name" }
    Write-Host "OK: $name"
    return "OLUSTURULDU"
}

$d1 = Ensure-EmptyDb $SistemDb
$d2 = Ensure-EmptyDb $FirmaDb
$r1 = Ensure-EmptyDb $RestoreSistem
$r2 = Ensure-EmptyDb $RestoreFirma

# App parola — dump/restore cin_app ile
$appPass = $env:MUHASEBE_PG_PASSWORD
if (-not $appPass) {
    $s2 = Read-Host "cin_app parolasi (dump/restore)" -AsSecureString
    $appPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s2))
}

$etiket = Get-Date -Format "yyyy-MM-dd_HHmmss"
$klasor = Join-Path $YedekKok "pg_d2_$etiket"
New-Item -ItemType Directory -Force -Path $klasor | Out-Null

$env:PGPASSWORD = $appPass
& $pgDump -h $PgHost -p $Port -U $AppUser -Fc -f (Join-Path $klasor "$SistemDb.dump") $SistemDb
if ($LASTEXITCODE -ne 0) { throw "pg_dump sistem basarisiz" }
& $pgDump -h $PgHost -p $Port -U $AppUser -Fc -f (Join-Path $klasor "$FirmaDb.dump") $FirmaDb
if ($LASTEXITCODE -ne 0) { throw "pg_dump firma basarisiz" }

# Restore: hedef zaten tabloluysa atla (silme yok)
function TableCount([string]$db) {
    $v = & $psql -h $PgHost -p $Port -U $AppUser -d $db -tAc `
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
    return [int]($v.Trim())
}

foreach ($pair in @(
    @{ Src = $SistemDb; Dst = $RestoreSistem },
    @{ Src = $FirmaDb; Dst = $RestoreFirma }
)) {
    $n = TableCount $pair.Dst
    if ($n -gt 0) {
        Write-Host "Restore atlandi (hedef tablolu, silinmedi): $($pair.Dst) tablo=$n" -ForegroundColor Yellow
        continue
    }
    Write-Host "pg_restore -> $($pair.Dst)"
    & $pgRestore -h $PgHost -p $Port -U $AppUser -d $pair.Dst --no-owner --no-acl `
        (Join-Path $klasor "$($pair.Src).dump")
    # pg_restore 1 = uyari olabilir
    if ($LASTEXITCODE -gt 1) { throw "pg_restore basarisiz: $($pair.Dst) exit=$LASTEXITCODE" }
}

Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue

$meta = @{
    zaman = $etiket
    host = $PgHost
    sistem = $SistemDb
    firma = $FirmaDb
    restore_sistem = $RestoreSistem
    restore_firma = $RestoreFirma
    db_durum = @{ $SistemDb = $d1; $FirmaDb = $d2; $RestoreSistem = $r1; $RestoreFirma = $r2 }
    not = "Sema Python create_all ayri; bu betik bos DB + dump/restore. K05/mali yazim yok."
} | ConvertTo-Json -Depth 5
Set-Content -Path (Join-Path $klasor "KUME.json") -Value $meta -Encoding UTF8

Write-Host ""
Write-Host "Yedek: $klasor" -ForegroundColor Green
Write-Host "Sonra terminalde: .venv\Scripts\python.exe -m tools.dnm_d2.pg_d2_hedef_hazirla"
Write-Host "(sema + profil + cin_app dogrulama; aktif kabul profili korunur)"
Write-Host "K05/K06 tam kabul ve mali yazim HALA KAPALI"
