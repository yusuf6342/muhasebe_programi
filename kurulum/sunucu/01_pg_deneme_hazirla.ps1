# Cin Muhasebe — Ana makine (DESKTOP-CGSE5GK) DENEME PostgreSQL hazırlığı
# Bu scripti ANA BİLGİSAYARDA yönetici PowerShell ile çalıştırın.
# Mevcut PostgreSQL verisini silmez; cin_sistem_deneme / cin_firma_deneme yoksa oluşturur.
# Parolayı bu dosyaya yazmayın.

param(
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres",
    [string]$AppUser = "cin_app",
    [string]$SistemDb = "cin_sistem_deneme",
    [string]$FirmaDb = "cin_firma_deneme",
    [string]$ListenHint = "LAN_IP_BURAYA"  # örn. 192.168.1.114 — DHCP değişebilir; sabitlemeyin
)

$ErrorActionPreference = "Stop"
Write-Host "=== Cin Muhasebe DENEME sunucu hazırlık ===" -ForegroundColor Cyan
Write-Host "Bu makine hostname: $env:COMPUTERNAME"
Write-Host "Beklenen ana makine: DESKTOP-CGSE5GK"
if ($env:COMPUTERNAME -ne "DESKTOP-CGSE5GK") {
    Write-Warning "Hostname ana makine değil. İşyeri sunucusunu yanlış PC'ye kurmayın. Devam yalnızca bilinçli DENEME içindir."
}

function Find-Psql {
    $adaylar = @(
        "C:\Program Files\PostgreSQL\17\bin\psql.exe",
        "C:\Program Files\PostgreSQL\16\bin\psql.exe",
        "C:\Program Files\PostgreSQL\18\bin\psql.exe"
    )
    foreach ($a in $adaylar) { if (Test-Path $a) { return $a } }
    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$psql = Find-Psql
if (-not $psql) {
    Write-Host "PostgreSQL bulunamadı. Önce kararlı 64-bit PostgreSQL 17 kurun (winget: PostgreSQL.PostgreSQL.17)."
    Write-Host "Kurulumdan sonra bu scripti yeniden çalıştırın."
    exit 2
}
Write-Host "psql: $psql"

$env:PGPASSWORD = $env:MUHASEBE_PG_SUPER_PASSWORD
if (-not $env:PGPASSWORD) {
    $secure = Read-Host "PostgreSQL superuser ($SuperUser) parolası" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
}

Write-Host "Bağlantı deneniyor $PgHost:$Port ..."
& $psql -h $PgHost -p $Port -U $SuperUser -d postgres -c "SELECT version();" | Out-Host
if ($LASTEXITCODE -ne 0) { throw "psql bağlantısı başarısız" }

$appPass = $env:MUHASEBE_PG_PASSWORD
if (-not $appPass) {
    $secure2 = Read-Host "cin_app uygulama parolası (yeni veya mevcut)" -AsSecureString
    $bstr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure2)
    $appPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr2)
    $env:MUHASEBE_PG_PASSWORD = $appPass
}

$sql = @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$AppUser') THEN
    CREATE ROLE $AppUser LOGIN PASSWORD '$appPass';
  END IF;
END
`$`$;
SELECT 'db_check' AS adim, datname FROM pg_database WHERE datname IN ('$SistemDb','$FirmaDb');
"@
# Parolayı SQL'e gömmek riskli; rol yoksa ayrı createuser tercih edilir — aşağıdaki basit yol:
& $psql -h $PgHost -p $Port -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -c "SELECT 1 FROM pg_roles WHERE rolname='$AppUser'" | Out-Null

$rolVar = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$AppUser'"
if ($rolVar -notmatch "1") {
    & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE $AppUser LOGIN PASSWORD '$appPass';"
    Write-Host "Rol oluşturuldu: $AppUser"
} else {
    Write-Host "Rol mevcut: $AppUser (parola güncellenmedi)"
}

foreach ($db in @($SistemDb, $FirmaDb)) {
    $var = & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'"
    if ($var -notmatch "1") {
        & $psql -h $PgHost -p $Port -U $SuperUser -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $db OWNER $AppUser;"
        Write-Host "Veritabanı oluşturuldu: $db"
    } else {
        Write-Host "Veritabanı zaten var (dokunulmadı): $db"
    }
}

Write-Host ""
Write-Host "SONRAKI ADIMLAR (manuel, gerçek IP ile):" -ForegroundColor Yellow
Write-Host "1) postgresql.conf: listen_addresses — yalnız LAN arayüzü"
Write-Host "2) pg_hba.conf: hostssl ... scram-sha-256  (trust / 0.0.0.0/0 YOK)"
Write-Host "3) Windows Güvenlik Duvarı: TCP $Port yalnız Özel ağ + yetkili terminaller"
Write-Host "4) Test-NetConnection -ComputerName <ANA_LAN_IP> -Port $Port"
Write-Host "5) Kaynak makinede: tools\_sqlite_to_postgres_gecis.py --uygula"
Write-Host "6) Bağlantı Ayarları: Yerel ağ, host=<ANA_LAN_IP>, ortam=DENEME"
Write-Host "DHCP rezervasyonu modemde henüz yoksa IP değişebilir; $ListenHint sabit kodlanmasın."
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
Write-Host "Tamam." -ForegroundColor Green
