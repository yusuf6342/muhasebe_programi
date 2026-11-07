#Requires -Version 5.1
<#
  Ana makine D2 pg_hba — dar terminal izni.
  Tercihen tasinabilir paket: kurulum\paket_d2_erisim (CIN_D2_ERISIM_*.zip)

  Kapsam: DESKTOP-CGSE5GK | 192.168.1.133/32 | cin_app |
          cin_sistem_dnm_d2_20260901 + cin_firma_dnm_d2_20260901 |
          hostssl + scram-sha-256

  Bu dosya paket 01_HBA_D2_IZIN.ps1 ile ayni politikayi izler.
  Tam surum icin paketi kullanin (on kontrol + geri alma + CMD).
#>
param(
    [string]$BeklenenMakine = "DESKTOP-CGSE5GK",
    [string]$PgData = "",
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432,
    [string]$SuperUser = "postgres",
    [string]$AppUser = "cin_app",
    [string]$TerminalCidr = "192.168.1.133/32"
)

$ErrorActionPreference = "Stop"
$Paket = Join-Path $PSScriptRoot "..\paket_d2_erisim\01_HBA_D2_IZIN.ps1"
if (Test-Path -LiteralPath $Paket) {
    & $Paket -BeklenenMakine $BeklenenMakine -PgData $PgData -PgHost $PgHost -Port $Port `
        -SuperUser $SuperUser -AppUser $AppUser -TerminalCidr $TerminalCidr
    exit $LASTEXITCODE
}
throw "Paket betigi yok: $Paket — CIN_D2_ERISIM ZIP / kurulum\paket_d2_erisim kullanin."
