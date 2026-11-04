# Merkezî PostgreSQL mantıksal yedek (pg_dump) — tutarlı küme etiketi
# Yazmaları kısa süre durdurmak pilot için önerilir.

param(
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$User = "cin_app",
    [string]$SistemDb = "cin_sistem_deneme",
    [string]$FirmaDb = "cin_firma_deneme",
    [string]$HedefKok = "$env:LOCALAPPDATA\CinMuhasebeTest\yedekler_pg"
)

$ErrorActionPreference = "Stop"
$psqlBin = "C:\Program Files\PostgreSQL\17\bin"
if (-not (Test-Path "$psqlBin\pg_dump.exe")) {
    throw "pg_dump bulunamadı. PostgreSQL 17 bin yolunu kontrol edin."
}
$etiket = Get-Date -Format "yyyy-MM-dd_HHmmss"
$klasor = Join-Path $HedefKok "pg_kume_$etiket"
New-Item -ItemType Directory -Force -Path $klasor | Out-Null
$meta = @{
    zaman = $etiket
    host = $PgHost
    port = $Port
    sistem_db = $SistemDb
    firma_db = $FirmaDb
    not = "Aynı etiket = aynı tutarlı küme; ayrı dump dosyalarını rastgele birleştirme"
} | ConvertTo-Json
Set-Content -Path (Join-Path $klasor "KUME.json") -Value $meta -Encoding UTF8

if (-not $env:MUHASEBE_PG_PASSWORD) {
    $s = Read-Host "cin_app parolası" -AsSecureString
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
} else {
    $env:PGPASSWORD = $env:MUHASEBE_PG_PASSWORD
}

& "$psqlBin\pg_dump.exe" -h $PgHost -p $Port -U $User -Fc -f (Join-Path $klasor "$SistemDb.dump") $SistemDb
& "$psqlBin\pg_dump.exe" -h $PgHost -p $Port -U $User -Fc -f (Join-Path $klasor "$FirmaDb.dump") $FirmaDb
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
Write-Host "Yedek kümesi: $klasor"
Write-Host "Geri yüklemeyi canlıya değil ayrı DENEME DB'ye uygulayın."
