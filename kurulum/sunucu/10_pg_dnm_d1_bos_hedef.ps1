# Cin Muhasebe — DNM birinci dönem (31.08.2026) BOŞ izole PostgreSQL hedefi
# Mevcut RAY / DENEME / kabul / restore veritabanlarının üzerine YAZMAZ.
# TEMPLATE kopyası değil: boş CREATE DATABASE (eski mali veri taşınmaz).
# Ana makinede yönetici PowerShell; parola dosyaya yazılmaz.
#
#   .\kurulum\sunucu\10_pg_dnm_d1_bos_hedef.ps1
#
# Talimat: kurulum\dnm_d1_20260831\Cin_Muhasebe_DNM_D1_Bakiye_Mutabakat_Talimati_2026-11-06.xlsx

param(
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres",
    [string]$AppUser = "cin_app",
    [string]$SistemDb = "cin_sistem_dnm_d1_20260831",
    [string]$FirmaDb = "cin_firma_dnm_d1_20260831"
)

$ErrorActionPreference = "Stop"
Write-Host "=== DNM D1 boş izole hedef ===" -ForegroundColor Cyan
Write-Host "Makine: $env:COMPUTERNAME"

$Korunan = @(
    "cin_sistem", "cin_firma_ray", "postgres",
    "cin_sistem_deneme", "cin_firma_deneme",
    "cin_sistem_kabul_20261105", "cin_firma_kabul_20261105",
    "cin_sistem_restore_20261105", "cin_firma_restore_20261105"
)

foreach ($ad in @($SistemDb, $FirmaDb)) {
    if ($ad -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$') { throw "Gecersiz DB adi: $ad" }
    if ($ad -in $Korunan) { throw "Hedef korunan ada carpti: $ad" }
    if ($ad -match '_(deneme|kabul|restore|ray)(_|$)') {
        throw "DNM D1 hedefi deneme/kabul/restore/ray adini kullanamaz: $ad"
    }
}
if ($SistemDb -eq $FirmaDb) { throw "Sistem ve firma hedefi ayni olamaz" }

function Find-Psql {
    foreach ($a in @(
        "C:\Program Files\PostgreSQL\17\bin\psql.exe",
        "C:\Program Files\PostgreSQL\16\bin\psql.exe",
        "C:\Program Files\PostgreSQL\18\bin\psql.exe"
    )) { if (Test-Path $a) { return $a } }
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$psql = Find-Psql
if (-not $psql) { throw "psql bulunamadi" }
Write-Host "psql: $psql"

$env:PGPASSWORD = $env:MUHASEBE_PG_SUPER_PASSWORD
if (-not $env:PGPASSWORD) {
    $secure = Read-Host "PostgreSQL superuser ($SuperUser) parolasi" -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

$rolVar = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$AppUser'"
if ($rolVar -notmatch "1") {
    throw "Uygulama rolu yok: $AppUser — once 01_pg_deneme_hazirla.ps1 veya createuser"
}
Write-Host "Rol mevcut: $AppUser"

function Db-Exists([string]$name) {
    $v = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$name'"
    return ($v -match "1")
}

foreach ($db in @($SistemDb, $FirmaDb)) {
    if (Db-Exists $db) {
        Write-Host "Zaten var (dokunulmadi): $db" -ForegroundColor Yellow
        continue
    }
    Write-Host "CREATE DATABASE $db (bos, OWNER $AppUser) ..."
    & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -c `
        "CREATE DATABASE $db OWNER $AppUser;"
    if ($LASTEXITCODE -ne 0) { throw "CREATE DATABASE basarisiz: $db" }
    Write-Host "OK: $db"
}

Write-Host ""
Write-Host "SONRAKI:" -ForegroundColor Yellow
Write-Host "1) Bu hedeflere yalniz DNM D1 baglanti profili bagla; RAY/DENEME profilini degistirme"
Write-Host "2) Kaynak kapanis (K05) tamamlanmadan mali yazim baslatma"
Write-Host "3) EXE / dagitim paketi butun isler bitene kadar yok"
Write-Host "Hedefler: $SistemDb / $FirmaDb"
