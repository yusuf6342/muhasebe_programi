# Cin Muhasebe - veri paketini KULLANICININ SECTIGI TEST veri klasorune geri yukleme
#
# 1) Hedef klasoru kullanici acikca secer (-HedefKlasor verilmezse klasor secme
#    penceresi acilir; varsayilan %LOCALAPPDATA%\CinMuhasebeTest\data) ve
#    tam yol ekranda gosterilip E/H ile onaylanir.
# 2) Paket MANIFEST ile dogrulanir.
# 3) Hedef klasorde var olan her sey once _onceki_veri_<tarih> klasorune
#    kopyalanir ve dogrulanir (hicbir sey yedeksiz silinmez).
# 4) Sonra paket hedefe yazilir ve tekrar dogrulanir.
# Program KAPALI olmalidir.
#
# GERCEK VERI KORUMASI: %LOCALAPPDATA%\MuhasebeProgrami ve altindaki her klasor
# (gercek veri + yedekler) ile bu klasoru iceren ust klasorler (orn. %LOCALAPPDATA%,
# C:\) HEDEF OLAMAZ. Bunu asan bir anahtar YOKTUR.
#
# Kullanim:
#   powershell -NoProfile -ExecutionPolicy Bypass -File veri_geri_yukle.ps1
#   ... -Paket "C:\...\CinMuhasebe_Veri_20260928_110000.zip" -HedefKlasor "C:\...\data"
#   ... -DenemeModu   (hicbir sey yazmadan ne yapilacagini gosterir)
#   ... -Onayli       (yalnizca -HedefKlasor ile: E/H sorusunu atlar; otomasyon icin)
#   ... -AcikProgramiYoksay  (YALNIZCA acik program hedef klasoru kullanmiyorsa)

[CmdletBinding()]
param(
    [string]$Paket = "",
    [Alias("Hedef")]
    [string]$HedefKlasor = "",
    [switch]$DenemeModu,
    [switch]$Onayli,
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

function Get-TamYol([string]$p) {
    $t = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($p.Trim().Trim('"')))
    if ($t.Length -gt 3) { $t = $t.TrimEnd('\') }
    return $t
}

function Test-Altinda([string]$yol, [string]$klasor) {
    # $yol == $klasor veya $klasor'un altinda mi (buyuk/kucuk harf duyarsiz)
    $a = $yol.TrimEnd('\') + '\'
    $k = $klasor.TrimEnd('\') + '\'
    return $a.StartsWith($k, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-GuvenliHedef([string]$hedef) {
    $gercekKok = Get-TamYol (Join-Path $env:LOCALAPPDATA "MuhasebeProgrami")
    if (Test-Altinda $hedef $gercekKok) {
        throw "REDDEDILDI: Hedef gercek veri/yedek klasoru ($gercekKok) icinde: $hedef. Bu klasore geri yukleme yapilamaz."
    }
    if (Test-Altinda $gercekKok $hedef) {
        throw "REDDEDILDI: Hedef gercek veri klasorunu iceren bir ust klasor: $hedef. Bir alt test klasoru secin."
    }
}

function Select-HedefKlasor([string]$varsayilan) {
    Add-Type -AssemblyName System.Windows.Forms
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "Veri paketinin yuklenecegi TEST veri klasorunu secin (gercek veri klasoru secilemez)"
    $dlg.ShowNewFolderButton = $true
    New-Item -ItemType Directory -Path $varsayilan -Force | Out-Null
    $dlg.SelectedPath = $varsayilan
    if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return $null }
    return $dlg.SelectedPath
}

function Get-Manifest([string]$kok) {
    $m = @{}
    foreach ($s in Get-Content -LiteralPath (Join-Path $kok "MANIFEST.txt") -Encoding UTF8) {
        if (-not $s -or $s.StartsWith("#")) { continue }
        $p = $s.Split("|")
        if ($p.Count -eq 3) { $m[$p[0]] = @{ Boyut = [int64]$p[1]; Hash = $p[2] } }
    }
    return $m
}

function Test-Kopya([string]$kaynakKok, [string]$hedefKok) {
    foreach ($f in Get-ChildItem -LiteralPath $kaynakKok -Recurse -File) {
        $rel = $f.FullName.Substring($kaynakKok.Length).TrimStart('\')
        $h = Join-Path $hedefKok $rel
        if (-not (Test-Path -LiteralPath $h)) { throw "Kopya eksik: $h" }
        if ((Get-FileHash -LiteralPath $f.FullName).Hash -ne (Get-FileHash -LiteralPath $h).Hash) {
            throw "Kopya uyusmuyor: $h"
        }
    }
}

if (-not $Paket) { $Paket = Read-Host "Veri paketi (.zip) yolu" }
$Paket = $Paket.Trim().Trim('"')
if (-not (Test-Path -LiteralPath $Paket -PathType Leaf)) { throw "Paket bulunamadi: $Paket" }

$hedefVerildi = [bool]$HedefKlasor
if (-not $hedefVerildi) {
    $HedefKlasor = Select-HedefKlasor (Join-Path $env:LOCALAPPDATA "CinMuhasebeTest\data")
    if (-not $HedefKlasor) { Write-Host "Klasor secilmedi; islem iptal."; exit 1 }
}
$Hedef = Get-TamYol $HedefKlasor
Assert-GuvenliHedef $Hedef

Write-Host "Paket : $Paket"
Write-Host "Hedef : $Hedef"
if (-not ($Onayli -and $hedefVerildi)) {
    $cevap = Read-Host "Veri paketi YALNIZCA bu klasore yuklenecek: $Hedef  Devam? (E/H)"
    if ($cevap -notmatch '^(e|evet|y|yes)$') { Write-Host "Iptal edildi; hicbir sey yazilmadi."; exit 1 }
}

if ((Test-ProgramAcik) -and -not $AcikProgramiYoksay) { throw "Cin Muhasebe (veya python main.py) acik. Once programi kapatin." }

# 1) Paketi gecici klasore ac ve dogrula
$damga = Get-Date -Format "yyyyMMdd_HHmmss"
$acik = Join-Path $env:TEMP "CinMuhasebe_GeriYukle_$damga"
Expand-Archive -LiteralPath $Paket -DestinationPath $acik
if (-not (Test-Path -LiteralPath (Join-Path $acik "MANIFEST.txt"))) { throw "MANIFEST.txt yok; bu bir Cin Muhasebe veri paketi degil." }
if (-not (Test-Path -LiteralPath (Join-Path $acik "muhasebe.db"))) { throw "Pakette muhasebe.db yok." }
$manifest = Get-Manifest $acik
foreach ($rel in $manifest.Keys) {
    $f = Join-Path $acik $rel
    if (-not (Test-Path -LiteralPath $f)) { throw "Pakette eksik dosya: $rel" }
    if ((Get-FileHash -LiteralPath $f).Hash -ne $manifest[$rel].Hash) { throw "Paket bozuk (hash): $rel" }
}
Write-Host "Paket dogrulandi: $($manifest.Count) dosya."

# 2) Hedefte mevcut veri varsa once yedekle
$mevcut = @()
if (Test-Path -LiteralPath $Hedef) { $mevcut = @(Get-ChildItem -LiteralPath $Hedef -Recurse -File) }
$yedek = Join-Path (Split-Path -Parent $Hedef) ("_onceki_veri_" + $damga)
Assert-GuvenliHedef $yedek
if ($mevcut.Count -gt 0) {
    Write-Host "Hedefte $($mevcut.Count) dosya var; yedek: $yedek"
    if (-not $DenemeModu) {
        Copy-Item -LiteralPath $Hedef -Destination $yedek -Recurse
        Test-Kopya $Hedef $yedek
        Write-Host "Mevcut veri yedeklendi ve dogrulandi."
    }
}

# Eski -wal/-shm yeni .db ile karisirsa veri bozulur: yedeklenen DB dosyalarini kaldir
$eskiDb = @($mevcut | Where-Object { $_.Name -match '\.db(-wal|-shm)?$' -and $_.FullName -notmatch '\\yedekler\\' })
Write-Host "Degistirilecek eski DB dosyasi: $($eskiDb.Count)"
if ($DenemeModu) {
    $eskiDb | ForEach-Object { Write-Host "  (deneme) kaldirilacak: $($_.FullName)" }
    Get-ChildItem -LiteralPath $acik -Recurse -File | ForEach-Object { Write-Host "  (deneme) yazilacak: $($_.FullName.Substring($acik.Length))" }
    Remove-Item -LiteralPath $acik -Recurse -Force
    Write-Host "Deneme modu: hicbir sey yazilmadi."
    exit 0
}
foreach ($f in $eskiDb) { Remove-Item -LiteralPath $f.FullName -Force }

# 3) Paketi hedefe yaz ve dogrula
New-Item -ItemType Directory -Path $Hedef -Force | Out-Null
Get-ChildItem -LiteralPath $acik -Force | Where-Object { $_.Name -ne "MANIFEST.txt" } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $Hedef -Recurse -Force }
foreach ($rel in $manifest.Keys) {
    $h = Join-Path $Hedef $rel
    if ((Get-FileHash -LiteralPath $h).Hash -ne $manifest[$rel].Hash) { throw "Yazilan dosya uyusmuyor: $h" }
}
Copy-Item -LiteralPath (Join-Path $acik "MANIFEST.txt") -Destination (Join-Path $Hedef "SON_GERI_YUKLEME_MANIFEST.txt") -Force
Remove-Item -LiteralPath $acik -Recurse -Force

Write-Host ""
Write-Host "Geri yukleme tamam: $Hedef"
if ($mevcut.Count -gt 0) { Write-Host "Onceki veri yedegi: $yedek" }
Write-Host "Programi acin; alt durum cubugunda 'Veri:' yolunun bu klasor oldugunu kontrol edin."
