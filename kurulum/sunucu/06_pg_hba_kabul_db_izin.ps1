# Ana makine (DESKTOP-CGSE5GK): yeni kabul/restore DB adlarina LAN + SSL izin
# Mevcut deneme satirlarini silmez; yoksa ekler; pg_ctl reload.
# Yonetici PowerShell onerilir. Parola gerektirmez (dosya duzenleme).

param(
    [string]$PgData = "C:\Program Files\PostgreSQL\17\data",
    [string]$Cidr = "192.168.1.0/24",
    [string]$AppUser = "cin_app"
)

$ErrorActionPreference = "Stop"
$hba = Join-Path $PgData "pg_hba.conf"
if (-not (Test-Path $hba)) { throw "pg_hba.conf yok: $hba" }

$dbs = @(
    "cin_sistem_kabul_20261105",
    "cin_firma_kabul_20261105",
    "cin_sistem_restore_20261105",
    "cin_firma_restore_20261105"
)

$mevcut = Get-Content $hba -Raw -Encoding UTF8
$ekler = @()
foreach ($db in $dbs) {
    $satir = "hostssl  $db  $AppUser  $Cidr  scram-sha-256"
    if ($mevcut -match [regex]::Escape($db)) {
        Write-Host "Zaten var (atlandi): $db"
    } else {
        $ekler += $satir
    }
}

if ($ekler.Count -eq 0) {
    Write-Host "Eklenecek satir yok."
} else {
    $yedek = "$hba.bak_kabul_" + (Get-Date -Format "yyyyMMdd_HHmmss")
    Copy-Item $hba $yedek -Force
    Write-Host "Yedek: $yedek"
    Add-Content -Path $hba -Value ""
    Add-Content -Path $hba -Value "# CinMuhasebe kabul/restore DENEME $(Get-Date -Format o)"
    foreach ($s in $ekler) {
        Add-Content -Path $hba -Value $s
        Write-Host "Eklendi: $s"
    }
}

$pgCtl = "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe"
if (Test-Path $pgCtl) {
    & $pgCtl reload -D $PgData
    Write-Host "pg_ctl reload OK (exit=$LASTEXITCODE)"
} else {
    Write-Warning "pg_ctl bulunamadi; servisi elle reload edin: Restart-Service postgresql*"
}

Write-Host "Sonra terminalden cin_app ile kabul DB baglantisini deneyin." -ForegroundColor Green
