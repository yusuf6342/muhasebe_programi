# Cin Muhasebe - test kurulum dosyasini derler (Inno Setup 6 gerekir).
# Once EXE: .venv\Scripts\python.exe -m PyInstaller --noconfirm CinMuhasebe.spec
# Sonra:    powershell -NoProfile -ExecutionPolicy Bypass -File installer\build_installer.ps1
# Cikti:    Output\CinMuhasebe_Test_Kurulum_<surum>.exe
# OneDrive dist\ klasorunu kilitliyorsa EXE'yi disarida derleyip -DistDir verin:
#   .venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath C:\CinMuhasebeBuild3\dist --workpath C:\CinMuhasebeBuild3\build CinMuhasebe.spec
#   ... build_installer.ps1 -DistDir C:\CinMuhasebeBuild3\dist\CinMuhasebe

[CmdletBinding()]
param(
    [string]$Iscc = "",
    [string]$DistDir = "",
    # OneDrive disinda cikti icin, orn. -OutputDir C:\CinMuhasebeKurulum
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$m = Select-String -LiteralPath (Join-Path $root "branding.py") -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $m) { throw "branding.py icinde APP_VERSION bulunamadi." }
$surum = $m.Matches[0].Groups[1].Value

$dist = if ($DistDir) { $DistDir } else { Join-Path $root "dist\CinMuhasebe" }
$dist = (Resolve-Path -LiteralPath $dist).Path
$exe = Join-Path $dist "CinMuhasebe.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "EXE yok: $dist. Once PyInstaller ile derleyin."
}
$enYeniPy = Get-ChildItem -LiteralPath $root -Filter *.py -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($enYeniPy -and (Get-Item $exe).LastWriteTime -lt $enYeniPy.LastWriteTime) {
    Write-Warning "EXE ($((Get-Item $exe).LastWriteTime)) kaynak koddan eski ($($enYeniPy.Name) $($enYeniPy.LastWriteTime)). Once yeniden derleyin."
}
$db = Get-ChildItem -LiteralPath $dist -Recurse -File | Where-Object { $_.Name -match '\.db(-wal|-shm)?$' }
if ($db) { Write-Warning "dist icinde DB dosyasi var (kuruluma ALINMAZ): $($db.FullName -join ', ')" }

if (-not $Iscc) {
    foreach ($c in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )) { if (Test-Path -LiteralPath $c) { $Iscc = $c; break } }
}
if (-not $Iscc) { throw "ISCC.exe bulunamadi. Inno Setup 6 kurun: https://jrsoftware.org/isdl.php" }

Write-Host "Surum: $surum"
Write-Host "EXE klasoru: $dist"
$cikti = if ($OutputDir) { [IO.Path]::GetFullPath($OutputDir) } else { Join-Path $root "Output" }
New-Item -ItemType Directory -Path $cikti -Force | Out-Null
& $Iscc "/DAppVersion=$surum" "/DDistDir=$dist" "/O$cikti" (Join-Path $PSScriptRoot "CinMuhasebe.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC hata kodu: $LASTEXITCODE" }
Get-Item (Join-Path $cikti "CinMuhasebe_Test_Kurulum_$surum.exe") | Format-List FullName, Length, LastWriteTime
