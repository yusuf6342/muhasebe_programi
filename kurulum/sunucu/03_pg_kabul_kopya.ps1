# Cin Muhasebe — Ana makinede kabul testi icin izole DB kopyalari
# CIN_SISTEM/FIRMA_DENEME uzerine yazmaz; TEMPLATE ile kopyalar.
# Ana bilgisayarda (DESKTOP-CGSE5GK) yonetici PowerShell ile calistirin.
# Parola: MUHASEBE_PG_SUPER_PASSWORD veya guvenli istem (dosyaya yazmayin).

param(
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres",
    [string]$AppUser = "cin_app",
    [string]$SrcSistem = "cin_sistem_deneme",
    [string]$SrcFirma = "cin_firma_deneme",
    [string]$DstSistem = "cin_sistem_kabul_20261105",
    [string]$DstFirma = "cin_firma_kabul_20261105"
)

$ErrorActionPreference = "Stop"
Write-Host "=== Kabul izolasyon kopyasi ===" -ForegroundColor Cyan
Write-Host "Makine: $env:COMPUTERNAME"

function Find-Psql {
    foreach ($a in @(
        "C:\Program Files\PostgreSQL\17\bin\psql.exe",
        "C:\Program Files\PostgreSQL\16\bin\psql.exe"
    )) { if (Test-Path $a) { return $a } }
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$psql = Find-Psql
if (-not $psql) { throw "psql bulunamadi" }

$env:PGPASSWORD = $env:MUHASEBE_PG_SUPER_PASSWORD
if (-not $env:PGPASSWORD) {
    $secure = Read-Host "PostgreSQL superuser ($SuperUser) parolasi" -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

function Db-Exists([string]$name) {
    $v = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$name'"
    return ($v -match "1")
}

function Clone-Db([string]$src, [string]$dst) {
    if (Db-Exists $dst) {
        Write-Host "Zaten var (dokunulmadi): $dst"
        return
    }
    if (-not (Db-Exists $src)) { throw "Kaynak yok: $src" }
    Write-Host "Baglantilar kesiliyor: $src"
    & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -c @"
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '$src' AND pid <> pg_backend_pid();
"@
    Write-Host "CREATE DATABASE $dst TEMPLATE $src ..."
    & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -c `
        "CREATE DATABASE $dst TEMPLATE $src OWNER $AppUser;"
    if ($LASTEXITCODE -ne 0) { throw "CREATE DATABASE basarisiz: $dst" }
    Write-Host "OK: $dst"
}

Clone-Db $SrcSistem $DstSistem
Clone-Db $SrcFirma $DstFirma

# RAY001'i kopyadaki firma DB'ye yonlendir; diger firmalar kilitli kalsin
& $psql -h $PgHost -p $Port -U $SuperUser -d $DstSistem -v ON_ERROR_STOP=1 -c @"
UPDATE companies SET db_path = 'pg:$DstFirma' WHERE firma_kodu = 'RAY001';
UPDATE companies SET aktif = false WHERE firma_kodu <> 'RAY001';
SELECT id, firma_kodu, db_path, aktif FROM companies ORDER BY id;
"@

# cin_app'e CREATEDB vermeden yedek/geri yukleme icin en az baglanti
Write-Host "Kaynak deneme DB'ler dokunulmadi (TEMPLATE okuduktan sonra baglantilar acilabilir)."
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
Write-Host "Tamam. Hedef: $DstSistem / $DstFirma" -ForegroundColor Green
