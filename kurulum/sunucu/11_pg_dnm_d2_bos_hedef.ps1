# Cin Muhasebe — DNM ikinci dönem (D2) BOŞ izole PostgreSQL hedefi
# Mevcut RAY / DENEME / kabul / restore / D1 DNM veritabanlarının üzerine YAZMAZ.
# TEMPLATE kopyası değil: boş CREATE DATABASE (eski mali veri taşınmaz).
#
# cin_app'e CREATEDB veya SUPERUSER VERİLMEZ.
# Bu betik yalnızca mevcut yetkili yönetim akışıyla (postgres superuser) çalışır.
# Parola sohbet/log'a yazılmaz: MUHASEBE_PG_SUPER_PASSWORD veya Read-Host.
#
# Deneme durumu: BEKLIYOR — ana makinede yönetici PowerShell ile çalıştırın.
# Gerçek D2 kurulumu / mali yazım K05+K06 sonrası (bu betik yalnız boş hedef).
#
#   .\kurulum\sunucu\11_pg_dnm_d2_bos_hedef.ps1
#
# Sonraki (ayrı, K06): 04_pg_restore_ayri_hedef.ps1 benzeri dump→
#   cin_sistem_dnm_d2_restore_test / cin_firma_dnm_d2_restore_test

param(
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres",
    [string]$AppUser = "cin_app",
    [string]$SistemDb = "cin_sistem_dnm_d2_20260901",
    [string]$FirmaDb = "cin_firma_dnm_d2_20260901"
)

$ErrorActionPreference = "Stop"
Write-Host "=== DNM D2 bos izole hedef (CREATEDB cin_app'e verilmez) ===" -ForegroundColor Cyan
Write-Host "Makine: $env:COMPUTERNAME"
Write-Host "Durum: DENEME_BEKLIYOR — yalnizca yetkili superuser ile"

$Korunan = @(
    "cin_sistem", "cin_firma_ray", "postgres",
    "cin_sistem_deneme", "cin_firma_deneme",
    "cin_sistem_kabul_20261105", "cin_firma_kabul_20261105",
    "cin_sistem_restore_20261105", "cin_firma_restore_20261105",
    "cin_sistem_dnm_d1_20260831", "cin_firma_dnm_d1_20260831"
)

foreach ($ad in @($SistemDb, $FirmaDb)) {
    if ($ad -notmatch '^[A-Za-z_][A-Za-z0-9_]{0,62}$') { throw "Gecersiz DB adi: $ad" }
    if ($ad -in $Korunan) { throw "Hedef korunan ada carpti: $ad" }
    if ($ad -match '_(deneme|kabul|restore|ray)(_|$)') {
        throw "DNM D2 hedefi deneme/kabul/restore/ray adini kullanamaz: $ad"
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
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    throw "Uygulama rolu yok: $AppUser — once 01_pg_deneme_hazirla.ps1 veya createuser"
}
# CREATEDB / SUPERUSER cin_app'e EKLENMEZ — yalnızca rolün varlığı doğrulanır
$rolYetki = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc `
    "SELECT rolcreatedb::text || ',' || rolsuper::text FROM pg_roles WHERE rolname='$AppUser'"
Write-Host "Rol mevcut: $AppUser (rolcreatedb,rolsuper=$($rolYetki.Trim())) — bu betik yetki genisletmez"

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
    if ($LASTEXITCODE -ne 0) {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        throw "CREATE DATABASE basarisiz: $db"
    }
    Write-Host "OK: $db"
}

Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "SONRAKI:" -ForegroundColor Yellow
Write-Host "1) DNM D2 baglanti profili yalniz bu hedeflere; RAY/DENEME/D1 profilini degistirme"
Write-Host "2) K05/K06 olmadan mali yazim / EXE yok"
Write-Host "3) Izole restore: dump sonra cin_*_dnm_d2_restore_test (04 benzeri; korunanlara yazma)"
Write-Host "Hedefler: $SistemDb / $FirmaDb"
Write-Host "DENEME_BEKLIYOR kaldirildiysa: bos DB olustu; K06 henuz acik degil"
