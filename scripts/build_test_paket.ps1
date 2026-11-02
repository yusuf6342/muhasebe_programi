# TEST EXE paketi — canlı dist\CinMuhasebe üzerine yazmaz.
# Kullanım (repo kökünden):
#   powershell -ExecutionPolicy Bypass -File scripts\build_test_paket.ps1
param(
    [switch]$UpdateShortcut
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "venv python yok: $venvPy" }

Write-Host "Building TEST package (dist\CinMuhasebe_TEST) — live dist\CinMuhasebe untouched ..."
$env:CIN_TEST_BUILD = "1"
try {
    & $venvPy -m PyInstaller --noconfirm CinMuhasebe.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
}
finally {
    Remove-Item Env:CIN_TEST_BUILD -ErrorAction SilentlyContinue
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$src = Join-Path $Root "dist\CinMuhasebe_TEST"
$dst = Join-Path $Root "dist\CinMuhasebe_ISYERI_TEST_$stamp"
if (-not (Test-Path $src)) { throw "TEST build missing: $src" }

Copy-Item -Path $src -Destination $dst -Recurse -Force

# TEST veri işaretleri — önceki paketten veya şablon
$prev = Get-ChildItem (Join-Path $Root "dist") -Directory -Filter "CinMuhasebe_ISYERI_TEST_*" |
    Where-Object { $_.FullName -ne $dst } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
foreach ($f in @("veri_konumu.txt", "test_kurulumu.txt")) {
    $fromPrev = if ($prev) { Join-Path $prev.FullName $f } else { $null }
    if ($fromPrev -and (Test-Path $fromPrev)) {
        Copy-Item $fromPrev (Join-Path $dst $f) -Force
    }
}
if (-not (Test-Path (Join-Path $dst "veri_konumu.txt"))) {
    @"
# Cin Muhasebe TEST kurulumu - veri klasoru.
%LOCALAPPDATA%\CinMuhasebeTest\data
"@ | Set-Content -Path (Join-Path $dst "veri_konumu.txt") -Encoding UTF8
}
if (-not (Test-Path (Join-Path $dst "test_kurulumu.txt"))) {
    @"
# Cin Muhasebe TEST kurulumu isareti.
"@ | Set-Content -Path (Join-Path $dst "test_kurulumu.txt") -Encoding UTF8
}

$exe = Join-Path $dst "CinMuhasebe.exe"
$hash = (Get-FileHash -Algorithm SHA256 $exe).Hash
Write-Host "TEST package: $dst"
Write-Host "SHA256: $hash"
Write-Host "Live package untouched: dist\CinMuhasebe (if present)"

if ($UpdateShortcut) {
    $lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Cin Muhasebe GÜNCEL — İŞYERİ TEST — 02.11.2026.lnk"
    # OneDrive Masaüstü
    $alt = "C:\Users\cigde\OneDrive\Masaüstü\Cin Muhasebe GÜNCEL — İŞYERİ TEST — 02.11.2026.lnk"
    if (Test-Path $alt) { $lnkPath = $alt }
    if (-not (Test-Path $lnkPath)) { Write-Warning "TEST shortcut not found: $lnkPath"; return }
    $sh = New-Object -ComObject WScript.Shell
    $lnk = $sh.CreateShortcut($lnkPath)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $dst
    $lnk.Save()
    Write-Host "Shortcut updated: $lnkPath"
} else {
    Write-Host "Shortcut NOT updated (pass -UpdateShortcut after user approval)."
}
