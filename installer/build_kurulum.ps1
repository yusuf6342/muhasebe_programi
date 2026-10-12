# Cin Muhasebe - kurulum dosyasini derler (Inno Setup 6 gerekir).
# Once EXE (OneDrive disinda):
#   .venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath C:\CinMuhasebeDerleme\<ts>\dist --workpath C:\CinMuhasebeDerleme\<ts>\build CinMuhasebe.spec
# Sonra:
#   powershell -NoProfile -ExecutionPolicy Bypass -File installer\build_kurulum.ps1 -DistDir C:\CinMuhasebeDerleme\<ts>\dist\CinMuhasebe
# Cikti: C:\CinMuhasebeKurulum\CinMuhasebe_Setup_<surum>_<yyyyMMdd>.exe (+ .sha256.txt)

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DistDir,
    [string]$Cikti = "C:\CinMuhasebeKurulum",
    [string]$Iscc = ""
)

$ErrorActionPreference = "Stop"
$burasi = $PSScriptRoot
$root = (Resolve-Path (Join-Path $burasi "..")).Path

$m = Select-String -LiteralPath (Join-Path $root "branding.py") -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $m) { throw "branding.py icinde APP_VERSION bulunamadi." }
$surum = $m.Matches[0].Groups[1].Value
$tarih = Get-Date -Format "yyyyMMdd"

$dist = (Resolve-Path -LiteralPath $DistDir).Path
$exe = Join-Path $dist "CinMuhasebe.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "EXE yok: $dist" }

# Pakete veri / parola / konum dosyasi girmesin (iss Excludes ile de dislanir; burada ayrica denetlenir)
$yasak = Get-ChildItem -LiteralPath $dist -Recurse -File | Where-Object {
    $_.Name -match '\.db(-wal|-shm)?$' -or $_.Name -in @("ILK_YONETICI_SIFRE.txt", "veri_konumu.txt", "test_kurulumu.txt", "VERITABANI_KONUMU.txt")
}
if ($yasak) { Write-Warning ("dist icinde pakete ALINMAYACAK dosyalar var: " + ($yasak.FullName -join ", ")) }

if (-not $Iscc) {
    foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path -LiteralPath $c) { $Iscc = $c; break }
    }
}
if (-not $Iscc) { throw "ISCC.exe bulunamadi. Inno Setup 6 kurun: https://jrsoftware.org/isdl.php" }

# Inno Setup Turkce karakterleri UTF-8 BOM ile okur
$bom = New-Object Text.UTF8Encoding($true)
foreach ($f in @("CinMuhasebe_Kurulum.iss", "KURULUM_VE_ILK_GIRIS.txt")) {
    $yol = Join-Path $burasi $f
    [IO.File]::WriteAllText($yol, [IO.File]::ReadAllText($yol, [Text.Encoding]::UTF8), $bom)
}

New-Item -ItemType Directory -Path $Cikti -Force | Out-Null
& $Iscc "/DAppVersion=$surum" "/DDistDir=$dist" "/DBuildDate=$tarih" "/O$Cikti" (Join-Path $burasi "CinMuhasebe_Kurulum.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC hata kodu: $LASTEXITCODE" }

$ad = "CinMuhasebe_Setup_${surum}_$tarih"
$kurulum = Join-Path $Cikti "$ad.exe"
$ozet = @(
    "# Cin Muhasebe kurulum paketi",
    "# Surum: $surum   Derleme: $(Get-Date -Format 'yyyy-MM-dd HH:mm')",
    "# EXE klasoru: $dist",
    "",
    ("{0}  {1}" -f (Get-FileHash -LiteralPath $kurulum -Algorithm SHA256).Hash, "$ad.exe"),
    ("{0}  CinMuhasebe.exe (pakete giren)" -f (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash)
)
$ozet | Set-Content -LiteralPath (Join-Path $Cikti "$ad.sha256.txt") -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $burasi "KURULUM_VE_ILK_GIRIS.txt") -Destination $Cikti -Force

Get-Item -LiteralPath $kurulum | Format-List FullName, Length, LastWriteTime
