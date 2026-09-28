# Cin Muhasebe - veri paketleme (kaynak klasore YAZMAZ, yalnizca okur)
#
# system.db + muhasebe.db + companies\*.db (+ -wal/-shm) ve yardimci klasorleri
# zaman damgali bir zip'e koyar. Program KAPALI olmalidir.
#
# Kullanim:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\veri_paketle.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\veri_paketle.ps1 -Kaynak "D:\veri" -Hedef "E:\"
#   ... -YedeklerDahil   (data\yedekler klasorunu de ekler; buyuk olabilir)
#   ... -AcikProgramiYoksay  (YALNIZCA -Kaynak canli klasor degil de bir yedek kopyasiysa)

[CmdletBinding()]
param(
    [string]$Kaynak = "",
    [string]$Hedef = "",
    [switch]$YedeklerDahil,
    [switch]$AcikProgramiYoksay
)

$ErrorActionPreference = "Stop"

function Test-ProgramAcik {
    $exe = Get-Process -Name "CinMuhasebe" -ErrorAction SilentlyContinue
    if ($exe) { return $true }
    $py = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'main\.py' }
    return [bool]$py
}

if (-not $Kaynak) {
    if ($env:MUHASEBE_DB_DIR) { $Kaynak = $env:MUHASEBE_DB_DIR }
    else { $Kaynak = Join-Path $env:LOCALAPPDATA "MuhasebeProgrami\data" }
}
if (-not $Hedef) { $Hedef = [Environment]::GetFolderPath("Desktop") }

$Kaynak = (Resolve-Path -LiteralPath $Kaynak).Path
Write-Host "Kaynak veri klasoru: $Kaynak"

if (-not (Test-Path -LiteralPath (Join-Path $Kaynak "muhasebe.db") -PathType Leaf)) {
    throw "muhasebe.db bulunamadi: $Kaynak  (dogru klasor mu?)"
}
if ((Test-ProgramAcik) -and -not $AcikProgramiYoksay) {
    throw "Cin Muhasebe (veya python main.py) acik. Once programi kapatin, sonra tekrar calistirin."
}

$damga = Get-Date -Format "yyyyMMdd_HHmmss"
$ad = "CinMuhasebe_Veri_$damga"
$gecici = Join-Path $env:TEMP $ad
New-Item -ItemType Directory -Path $gecici -Force | Out-Null

$desen = '\.db(-wal|-shm)?$'
$dosyalar = @()
$dosyalar += Get-ChildItem -LiteralPath $Kaynak -File | Where-Object { $_.Name -match $desen }
$companies = Join-Path $Kaynak "companies"
if (Test-Path -LiteralPath $companies) {
    New-Item -ItemType Directory -Path (Join-Path $gecici "companies") -Force | Out-Null
    $dosyalar += Get-ChildItem -LiteralPath $companies -File | Where-Object { $_.Name -match $desen }
}

$klasorler = @("invoice_imports", "stok_resimleri")
if ($YedeklerDahil) { $klasorler += "yedekler" }

foreach ($f in $dosyalar) {
    $rel = $f.FullName.Substring($Kaynak.Length).TrimStart('\')
    Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $gecici $rel)
}
foreach ($k in $klasorler) {
    $kp = Join-Path $Kaynak $k
    if (Test-Path -LiteralPath $kp) {
        Copy-Item -LiteralPath $kp -Destination (Join-Path $gecici $k) -Recurse
    }
}

# Manifest: gore-yol, boyut, SHA256 (geri yuklemede dogrulanir)
$satirlar = @("# Cin Muhasebe veri paketi", "# Kaynak: $Kaynak", "# Tarih: $damga", "# Bilgisayar: $env:COMPUTERNAME")
foreach ($f in Get-ChildItem -LiteralPath $gecici -Recurse -File) {
    $rel = $f.FullName.Substring($gecici.Length).TrimStart('\')
    $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
    $satirlar += "$rel|$($f.Length)|$h"
}
$satirlar | Set-Content -LiteralPath (Join-Path $gecici "MANIFEST.txt") -Encoding UTF8

$zip = Join-Path $Hedef "$ad.zip"
Compress-Archive -Path (Join-Path $gecici "*") -DestinationPath $zip -CompressionLevel Optimal
Remove-Item -LiteralPath $gecici -Recurse -Force

$wal = $dosyalar | Where-Object { $_.Name -like "*-wal" -and $_.Length -gt 0 }
Write-Host ""
Write-Host "Paket hazir: $zip  ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
Write-Host "Icerik:"
$dosyalar | ForEach-Object { Write-Host ("  {0}  {1:N0} bayt  {2:yyyy-MM-dd HH:mm}" -f $_.Name, $_.Length, $_.LastWriteTime) }
if ($wal) {
    Write-Host ""
    Write-Warning "Bos olmayan -wal dosyasi var (son kayitlar orada). Pakete eklendi; geri yuklemede .db ile birlikte kullanilir."
}
