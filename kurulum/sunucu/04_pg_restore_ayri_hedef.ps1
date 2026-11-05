# Yedegi AYRI bos DB adlarina geri yukler (deneme/canli uzerine yazmaz).
# Ana makinede superuser ile calistirin.
# Ornek:
#   .\04_pg_restore_ayri_hedef.ps1 -DumpKlasor "$env:LOCALAPPDATA\CinMuhasebeTest\yedekler_pg\pg_kume_kabul_YYYY-MM-DD_HHMMSS"

param(
    [Parameter(Mandatory = $true)][string]$DumpKlasor,
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres",
    [string]$AppUser = "cin_app",
    [string]$SrcSistemDump = "cin_sistem_deneme.dump",
    [string]$SrcFirmaDump = "cin_firma_deneme.dump",
    [string]$DstSistem = "cin_sistem_restore_20261105",
    [string]$DstFirma = "cin_firma_restore_20261105"
)

$ErrorActionPreference = "Stop"
$psqlBin = "C:\Program Files\PostgreSQL\17\bin"
$psql = Join-Path $psqlBin "psql.exe"
$restore = Join-Path $psqlBin "pg_restore.exe"
if (-not (Test-Path $psql)) { throw "psql yok" }

$env:PGPASSWORD = $env:MUHASEBE_PG_SUPER_PASSWORD
if (-not $env:PGPASSWORD) {
    $secure = Read-Host "PostgreSQL superuser ($SuperUser) parolasi" -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

function Ensure-EmptyDb([string]$name) {
    $var = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$name'"
    if ($var -match "1") { throw "Hedef zaten var, uzerine yazilmaz: $name" }
    & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $name OWNER $AppUser;"
}

Ensure-EmptyDb $DstSistem
Ensure-EmptyDb $DstFirma

$sysDump = Join-Path $DumpKlasor $SrcSistemDump
$frDump = Join-Path $DumpKlasor $SrcFirmaDump
if (-not (Test-Path $sysDump)) { throw "Yok: $sysDump" }
if (-not (Test-Path $frDump)) { throw "Yok: $frDump" }

& $restore -h $PgHost -p $Port -U $SuperUser -d $DstSistem --no-owner --role=$AppUser --exit-on-error $sysDump
if ($LASTEXITCODE -ne 0) { throw "sistem restore exit=$LASTEXITCODE" }
& $restore -h $PgHost -p $Port -U $SuperUser -d $DstFirma --no-owner --role=$AppUser --exit-on-error $frDump
if ($LASTEXITCODE -ne 0) { throw "firma restore exit=$LASTEXITCODE" }

& $psql -h $PgHost -p $Port -U $SuperUser -d $DstSistem -v ON_ERROR_STOP=1 -c @"
UPDATE companies SET db_path = 'pg:$DstFirma' WHERE firma_kodu = 'RAY001';
UPDATE companies SET aktif = false WHERE firma_kodu <> 'RAY001';
SELECT id, firma_kodu, db_path, aktif FROM companies ORDER BY id;
"@

Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
Write-Host "OK restore: $DstSistem / $DstFirma" -ForegroundColor Green
