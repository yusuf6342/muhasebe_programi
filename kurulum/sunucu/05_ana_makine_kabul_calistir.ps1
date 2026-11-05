# DESKTOP-CGSE5GK (ana makine) — izole kopya + ayri hedefe restore
# Yalniz postgres superuser ile. Gunluk/deneme DB uzerine yazmaz.
# Parola: MUHASEBE_PG_SUPER_PASSWORD veya guvenli istem (dosyaya/Git'e yazma).
#
# Ornek (ana makinede PowerShell):
#   cd C:\Users\cigde\OneDrive\Belgeler\GitHub\muhasebe_programi
#   .\kurulum\sunucu\05_ana_makine_kabul_calistir.ps1 `
#     -DumpKlasor "$env:LOCALAPPDATA\CinMuhasebeAktarim\AnaMakine_Kabul_Paket_2026-11-05\yedek"

param(
    [Parameter(Mandatory = $true)][string]$DumpKlasor,
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $Root "kurulum\sunucu\03_pg_kabul_kopya.ps1"))) {
    $Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

Write-Host "=== Ana makine kabul: kopya + restore ===" -ForegroundColor Cyan
Write-Host "Makine: $env:COMPUTERNAME"
Write-Host "Repo:   $Root"
Write-Host "Dump:   $DumpKlasor"

if ($env:COMPUTERNAME -ne "DESKTOP-CGSE5GK") {
    Write-Warning "Hostname DESKTOP-CGSE5GK degil. Yanlis PC'de CREATEDB yapmayin; bilinçli DENEME ise devam."
}

$shaFile = Join-Path $DumpKlasor "SHA256.txt"
if (-not (Test-Path $shaFile)) { throw "SHA256.txt yok: $shaFile" }
$sysDump = Join-Path $DumpKlasor "cin_sistem_deneme.dump"
$frDump = Join-Path $DumpKlasor "cin_firma_deneme.dump"
if (-not (Test-Path $sysDump)) { throw "Yok: $sysDump" }
if (-not (Test-Path $frDump)) { throw "Yok: $frDump" }

Write-Host "SHA-256 dogrulaniyor..."
Get-FileHash $sysDump -Algorithm SHA256 | Format-List
Get-FileHash $frDump -Algorithm SHA256 | Format-List
Get-Content $shaFile -Encoding UTF8 | Write-Host

& (Join-Path $Root "kurulum\sunucu\03_pg_kabul_kopya.ps1") `
    -PgHost $PgHost -Port $Port -SuperUser $SuperUser `
    -SrcSistem "cin_sistem_deneme" -SrcFirma "cin_firma_deneme" `
    -DstSistem "cin_sistem_kabul_20261105" -DstFirma "cin_firma_kabul_20261105"
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    throw "03_pg_kabul_kopya exit=$LASTEXITCODE"
}

& (Join-Path $Root "kurulum\sunucu\04_pg_restore_ayri_hedef.ps1") `
    -DumpKlasor $DumpKlasor `
    -PgHost $PgHost -Port $Port -SuperUser $SuperUser `
    -DstSistem "cin_sistem_restore_20261105" -DstFirma "cin_firma_restore_20261105"
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
    throw "04_pg_restore exit=$LASTEXITCODE"
}

$sonuc = Join-Path $DumpKlasor ("SONUC_" + $env:COMPUTERNAME + "_" + (Get-Date -Format "HHmmss") + ".txt")
@(
    "zaman=$(Get-Date -Format o)"
    "makine=$env:COMPUTERNAME"
    "kabul=cin_sistem_kabul_20261105 / cin_firma_kabul_20261105"
    "restore=cin_sistem_restore_20261105 / cin_firma_restore_20261105"
    "pg_host=$PgHost:$Port"
    "ok=1"
) | Set-Content -Path $sonuc -Encoding UTF8
Write-Host "SONUC: $sonuc" -ForegroundColor Green
Write-Host "Sonraki: ayni EXE SHA ile DENEME profilini kabul ciftine bagla (terminal+ana)." -ForegroundColor Yellow
