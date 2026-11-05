# Ana makinede 127.0.0.1 uzerinden kabul/restore mutabakati (cin_app).
# Parola: MUHASEBE_PG_PASSWORD veya guvenli istem. Sohbete yazmayin.

param(
    [string]$PgHost = "127.0.0.1",
    [int]$Port = 5432
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

if (-not $env:MUHASEBE_PG_PASSWORD) {
    $s = Read-Host "cin_app parolasi" -AsSecureString
    $env:MUHASEBE_PG_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python yok: $py" }

$env:KABUL_MUTABAKAT_HOST = $PgHost
$env:KABUL_MUTABAKAT_PORT = "$Port"
& $py (Join-Path $Root "tools\_kabul_cift_mutabakat.py")
$code = $LASTEXITCODE
Remove-Item Env:MUHASEBE_PG_PASSWORD -ErrorAction SilentlyContinue
exit $code
