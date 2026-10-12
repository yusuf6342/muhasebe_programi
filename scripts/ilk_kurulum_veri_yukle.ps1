# Cin Muhasebe - ILK KURULUMDA veri paketinden (yedekten) yukleme
#
# Kurulum sihirbazi "Veri paketinden yukle" secildiginde ve Baslat menusundeki
# "Veri Paketinden Yukle" kisayolu ile calisir.
#
# GUVENLIK:
# - Hedef klasorde zaten firma verisi (*.db) varsa HICBIR SEY yazmaz (mevcut
#   veri asla uzerine yazilmaz; dolu klasore yukleme icin once program icinden
#   yedek alip klasoru elle bosaltmak gerekir).
# - OneDrive / esitleme klasorleri ve ag yollari (\\sunucu\...) hedef olamaz.
# - Program acikken calismaz.
# - Paket MANIFEST.txt (dosya|boyut|sha256) ile dogrulanir; yazilan her dosya
#   tekrar dogrulanir.
#
# Cikis kodlari: 0 = tamam, 1 = kullanici iptal etti, 2 = hata / reddedildi
#
# Kullanim:
#   powershell -NoProfile -ExecutionPolicy Bypass -File ilk_kurulum_veri_yukle.ps1
#   ... -Paket "C:\...\CinMuhasebe_Veri_20261008_110000.zip" [-HedefKlasor "C:\...\data"] [-Sessiz]

[CmdletBinding()]
param(
    [string]$Paket = "",
    [string]$HedefKlasor = "",
    [switch]$Sessiz
)

$ErrorActionPreference = "Stop"
$damga = Get-Date -Format "yyyyMMdd_HHmmss"
$gunluk = Join-Path $env:TEMP "CinMuhasebe_VeriYukle_$damga.log"

function Yaz([string]$m) {
    Write-Host $m
    Add-Content -LiteralPath $gunluk -Value $m -Encoding UTF8
}

function Bitir([int]$kod, [string]$mesaj) {
    if ($mesaj) { Yaz $mesaj }
    Yaz "Gunluk: $gunluk"
    if (-not $Sessiz) { Read-Host "Kapatmak icin Enter'a basin" | Out-Null }
    exit $kod
}

function Test-ProgramAcik {
    if (Get-Process -Name "CinMuhasebe" -ErrorAction SilentlyContinue) { return $true }
    $py = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'main\.py' }
    return [bool]$py
}

function Get-TamYol([string]$p) {
    $t = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($p.Trim().Trim('"')))
    if ($t.Length -gt 3) { $t = $t.TrimEnd('\') }
    return $t
}

function Test-EsitlemeVeyaAg([string]$yol) {
    if ($yol.StartsWith('\\')) { return "ag yolu" }
    foreach ($k in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) {
        if ($k -and ($yol.TrimEnd('\') + '\').StartsWith($k.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            return "OneDrive klasoru"
        }
    }
    if ($yol -match '\\(OneDrive|Dropbox|Google Drive|iCloudDrive)[^\\]*\\') { return "esitleme klasoru" }
    $kok = [IO.Path]::GetPathRoot($yol)
    try {
        $surucu = New-Object IO.DriveInfo($kok)
        if ($surucu.DriveType -eq [IO.DriveType]::Network) { return "ag surucusu" }
    } catch { }
    return ""
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

function Select-Paket {
    Add-Type -AssemblyName System.Windows.Forms
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = "Cin Muhasebe veri paketini (.zip) secin"
    $dlg.Filter = "Cin Muhasebe veri paketi (*.zip)|*.zip"
    if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return $null }
    return $dlg.FileName
}

try {
    Yaz "Cin Muhasebe - veri paketinden yukleme ($damga)"
    if (-not $HedefKlasor) { $HedefKlasor = Join-Path $env:LOCALAPPDATA "MuhasebeProgrami\data" }
    $Hedef = Get-TamYol $HedefKlasor

    if (-not $Paket) {
        if ($Sessiz) { Bitir 2 "HATA: -Paket verilmedi." }
        $Paket = Select-Paket
        if (-not $Paket) { Bitir 1 "Paket secilmedi; islem iptal." }
    }
    $Paket = $Paket.Trim().Trim('"')
    if (-not (Test-Path -LiteralPath $Paket -PathType Leaf)) { Bitir 2 "HATA: Paket bulunamadi: $Paket" }

    $neden = Test-EsitlemeVeyaAg $Hedef
    if ($neden) { Bitir 2 "REDDEDILDI: Hedef bir $neden ($Hedef). Veri yerel diskte olmalidir." }

    $mevcutDb = @()
    if (Test-Path -LiteralPath $Hedef) {
        $mevcutDb = @(Get-ChildItem -LiteralPath $Hedef -Filter "*.db" -File -ErrorAction SilentlyContinue)
        $sirketler = Join-Path $Hedef "companies"
        if (Test-Path -LiteralPath $sirketler) {
            $mevcutDb += @(Get-ChildItem -LiteralPath $sirketler -Filter "*.db" -File -ErrorAction SilentlyContinue)
        }
    }
    if ($mevcutDb.Count -gt 0) {
        Bitir 2 ("REDDEDILDI: $Hedef klasorunde zaten firma verisi var ($($mevcutDb.Count) veritabani). " +
            "Mevcut veri korunur; hicbir sey yazilmadi.")
    }

    Yaz "Paket : $Paket"
    Yaz "Hedef : $Hedef"
    if (-not $Sessiz) {
        $cevap = Read-Host "Veri paketi bu klasore yuklenecek. Devam? (E/H)"
        if ($cevap -notmatch '^(e|evet|y|yes)$') { Bitir 1 "Iptal edildi; hicbir sey yazilmadi." }
    }

    if (Test-ProgramAcik) { Bitir 2 "HATA: Cin Muhasebe acik. Programi kapatip tekrar deneyin." }

    $acik = Join-Path $env:TEMP "CinMuhasebe_IlkYukle_$damga"
    Expand-Archive -LiteralPath $Paket -DestinationPath $acik
    try {
        if (-not (Test-Path -LiteralPath (Join-Path $acik "MANIFEST.txt"))) { Bitir 2 "HATA: MANIFEST.txt yok; bu bir Cin Muhasebe veri paketi degil." }
        if (-not (Test-Path -LiteralPath (Join-Path $acik "muhasebe.db"))) { Bitir 2 "HATA: Pakette muhasebe.db yok." }
        $manifest = Get-Manifest $acik
        foreach ($rel in $manifest.Keys) {
            $f = Join-Path $acik $rel
            if (-not (Test-Path -LiteralPath $f)) { Bitir 2 "HATA: Pakette eksik dosya: $rel" }
            if ((Get-FileHash -LiteralPath $f).Hash -ne $manifest[$rel].Hash) { Bitir 2 "HATA: Paket bozuk (hash): $rel" }
        }
        Yaz "Paket dogrulandi: $($manifest.Count) dosya."

        New-Item -ItemType Directory -Path $Hedef -Force | Out-Null
        Get-ChildItem -LiteralPath $acik -Force | Where-Object { $_.Name -ne "MANIFEST.txt" } |
            ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $Hedef -Recurse -Force }
        foreach ($rel in $manifest.Keys) {
            $h = Join-Path $Hedef $rel
            if ((Get-FileHash -LiteralPath $h).Hash -ne $manifest[$rel].Hash) { Bitir 2 "HATA: Yazilan dosya uyusmuyor: $h" }
        }
        Copy-Item -LiteralPath (Join-Path $acik "MANIFEST.txt") -Destination (Join-Path $Hedef "SON_GERI_YUKLEME_MANIFEST.txt") -Force
    } finally {
        Remove-Item -LiteralPath $acik -Recurse -Force -ErrorAction SilentlyContinue
    }

    Yaz ""
    Yaz "Yukleme tamam: $Hedef"
    Yaz "Programi acin ve paketteki firmanin kullanici adi / sifresi ile giris yapin."
    Bitir 0 ""
} catch {
    Bitir 2 ("HATA: " + $_.Exception.Message)
}
