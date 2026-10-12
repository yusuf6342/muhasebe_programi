# Cin Muhasebe - Evo Devir Deneme kurulum dosyasini derler (Inno Setup 6 gerekir).
#
# Kaynak veri klasorune YAZMAZ: veri gecici klasore kopyalanir, kopyada WAL birlestirilir,
# integrity_check yapilir ve kurulumun icine konur (yedekler klasoru haric).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File installer\evo_devir\build_evo_kurulum.ps1
#   ... -DistDir C:\...\dist\CinMuhasebe -Kaynak C:\CinMuhasebeEvoDevir\data -Cikti C:\CinMuhasebeEvoDevir\paket

[CmdletBinding()]
param(
    [string]$DistDir = "",
    [string]$Kaynak = "C:\CinMuhasebeEvoDevir\data",
    [string]$Cikti = "C:\CinMuhasebeEvoDevir\paket",
    [string]$Iscc = ""
)

$ErrorActionPreference = "Stop"
$burasi = $PSScriptRoot
$root = (Resolve-Path (Join-Path $burasi "..\..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"

$m = Select-String -LiteralPath (Join-Path $root "branding.py") -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $m) { throw "branding.py icinde APP_VERSION bulunamadi." }
$surum = $m.Matches[0].Groups[1].Value

$dist = if ($DistDir) { (Resolve-Path -LiteralPath $DistDir).Path } else { Join-Path $root "dist\CinMuhasebe" }
if (-not (Test-Path -LiteralPath (Join-Path $dist "CinMuhasebe.exe"))) { throw "EXE yok: $dist" }
$Kaynak = (Resolve-Path -LiteralPath $Kaynak).Path
if (-not (Test-Path -LiteralPath (Join-Path $Kaynak "system.db"))) { throw "system.db yok: $Kaynak" }
if (Get-Process -Name "CinMuhasebe" -ErrorAction SilentlyContinue) {
    throw "Cin Muhasebe acik. Veri kopyasi tutarli olsun diye once programi kapatin."
}
if (-not $Iscc) {
    foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path -LiteralPath $c) { $Iscc = $c; break }
    }
}
if (-not $Iscc) { throw "ISCC.exe bulunamadi. Inno Setup 6 kurun." }

# Inno bilgi sayfasi Turkce karakterleri UTF-8 BOM ile okur
$bilgi = Join-Path $burasi "KURULUM_VE_ILK_GIRIS.txt"
$metin = [IO.File]::ReadAllText($bilgi, [Text.Encoding]::UTF8)
[IO.File]::WriteAllText($bilgi, $metin, (New-Object Text.UTF8Encoding($true)))

$damga = Get-Date -Format "yyyyMMdd_HHmm"
$sahne = Join-Path $env:TEMP "CinMuhasebe_EvoDevir_Veri_$damga"
New-Item -ItemType Directory -Path (Join-Path $sahne "companies") -Force | Out-Null
$desen = '\.db(-wal|-shm)?$'
Get-ChildItem -LiteralPath $Kaynak -File | Where-Object { $_.Name -match $desen -or $_.Name -eq "ILK_YONETICI_SIFRE.txt" } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $sahne }
Get-ChildItem -LiteralPath (Join-Path $Kaynak "companies") -File | Where-Object { $_.Name -match $desen } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $sahne "companies") }

$birlestir = @'
import sqlite3, sys
from pathlib import Path
for db in sorted(Path(sys.argv[1]).rglob("*.db")):
    con = sqlite3.connect(db)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("PRAGMA journal_mode=DELETE")
    sonuc = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.close()
    print(f"{db.relative_to(sys.argv[1])}: {sonuc}")
    if sonuc != "ok":
        sys.exit(1)
'@
$py = Join-Path $env:TEMP "evo_veri_birlestir_$damga.py"
Set-Content -LiteralPath $py -Value $birlestir -Encoding UTF8
& $python $py $sahne
if ($LASTEXITCODE -ne 0) { throw "Veri kopyasi integrity_check basarisiz." }
Remove-Item -LiteralPath $py
Get-ChildItem -LiteralPath $sahne -Recurse -File | Where-Object { $_.Name -match '-(wal|shm)$' } | Remove-Item

New-Item -ItemType Directory -Path $Cikti -Force | Out-Null
$etiket = "_" + $damga
& $Iscc "/DAppVersion=$surum" "/DDistDir=$dist" "/DVeriDir=$sahne" "/DBuildTag=$etiket" "/O$Cikti" (Join-Path $burasi "CinMuhasebe_EvoDevir.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC hata kodu: $LASTEXITCODE" }
$kurulum = Join-Path $Cikti "CinMuhasebe_EvoDevir_Kurulum_$surum$etiket.exe"

$ozet = @("# Cin Muhasebe - Evo Devir Deneme kurulum paketi", "# Derleme: $damga", "# EXE klasoru: $dist",
          "# Veri kaynagi: $Kaynak", "")
$ozet += "{0}  {1}" -f (Get-FileHash -LiteralPath $kurulum -Algorithm SHA256).Hash, (Split-Path -Leaf $kurulum)
$ozet += "{0}  CinMuhasebe.exe (pakete giren)" -f (Get-FileHash -LiteralPath (Join-Path $dist "CinMuhasebe.exe") -Algorithm SHA256).Hash
foreach ($f in Get-ChildItem -LiteralPath $sahne -Recurse -File | Where-Object { $_.Name -like "*.db" }) {
    $ozet += "{0}  veri\{1}" -f (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash, $f.FullName.Substring($sahne.Length + 1)
}
$ozet | Set-Content -LiteralPath (Join-Path $Cikti "CinMuhasebe_EvoDevir_Kurulum_$surum$etiket.sha256.txt") -Encoding UTF8
Copy-Item -LiteralPath $bilgi -Destination $Cikti -Force
Remove-Item -LiteralPath $sahne -Recurse -Force

Get-Item -LiteralPath $kurulum | Format-List FullName, Length, LastWriteTime
