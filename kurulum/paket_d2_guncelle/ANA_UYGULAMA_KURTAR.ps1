#Requires -Version 5.1
<#
  Ana makine ACIL kurtarma — yalniz uygulama dosyalari.
  DB / PostgreSQL / baglanti_ayari.json KORUNUR.
  Force kill YOK. Calisma dizini TEMP.
#>
param(
    [string]$PaketKok = "",
    [switch]$AcmaYok
)

$ErrorActionPreference = "Stop"
$cwd = Join-Path $env:TEMP ("CinAnaKurtar_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $cwd | Out-Null
Set-Location $cwd
[Environment]::CurrentDirectory = $cwd

if (-not $PaketKok) { $PaketKok = Split-Path -Parent $PSScriptRoot }
if (-not (Test-Path (Join-Path $PaketKok "CinMuhasebe\CinMuhasebe.exe"))) {
    $PaketKok = $PSScriptRoot
}
$PaketKok = (Resolve-Path $PaketKok).Path
$Src = Join-Path $PaketKok "CinMuhasebe"
$SrcExe = Join-Path $Src "CinMuhasebe.exe"
if (-not (Test-Path $SrcExe)) { throw "Kaynak EXE yok: $SrcExe" }
if (-not (Test-Path (Join-Path $Src "_internal"))) { throw "Kaynak _internal yok" }

$HedefKok = Join-Path $env:LOCALAPPDATA "CinMuhasebe\DNM_D2"
$HedefApp = Join-Path $HedefKok "CinMuhasebe"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Geri = Join-Path $env:LOCALAPPDATA ("CinMuhasebe\DNM_D2_GERI_KURTAR_" + $Stamp)
$Log = Join-Path $HedefKok "KURTARMA_LOG.txt"

function L([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    Write-Host $line
    New-Item -ItemType Directory -Force -Path $HedefKok | Out-Null
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

# Host kontrolu — Ana beklenir (uyari; Force yok)
$pc = $env:COMPUTERNAME
L "PC=$pc Kurtarma paket=$PaketKok hedef=$HedefApp"

$acik = @(Get-Process CinMuhasebe -ErrorAction SilentlyContinue)
if ($acik.Count -gt 0) {
    Write-Host ""
    Write-Host "CinMuhasebe acik (PID $($acik.Id -join ',')). Kaydedip NORMAL kapatin; zorla kapatma yok."
    Write-Host "Kapaninca Enter'a basin."
    Write-Host ""
    [void][Console]::ReadLine()
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-Process CinMuhasebe -ErrorAction SilentlyContinue).Count -eq 0) { break }
        Start-Sleep 2
    }
    if (@(Get-Process CinMuhasebe -ErrorAction SilentlyContinue).Count -gt 0) {
        throw "CinMuhasebe hala acik — kurtarma iptal. Zorla kapatma yapilmaz."
    }
}

# Korunan ayarlar
$Korunan = Join-Path $Geri "_korunan"
New-Item -ItemType Directory -Force -Path $Korunan | Out-Null
if (Test-Path $HedefApp) {
    L "Mevcut uygulama yedekleniyor -> $Geri"
    robocopy $HedefApp (Join-Path $Geri "CinMuhasebe") /E /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
}
foreach ($rel in @(
    "CinMuhasebe\baglanti_ayari.json", "baglanti_ayari.json",
    "CinMuhasebe\kullanici_ayarlari.json", "CinMuhasebe\ayarlar.json"
)) {
    $p = Join-Path $HedefKok $rel
    if (Test-Path $p) {
        $d = Join-Path $Korunan $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $d) | Out-Null
        Copy-Item -Force $p $d
        L "Korundu: $rel"
    }
}

# Yerinde MIR — klasor Rename-Item yok
New-Item -ItemType Directory -Force -Path $HedefApp | Out-Null
$xf = @(
    "baglanti_ayari.json", "kullanici_ayarlari.json", "ayarlar.json",
    "credentials.json", "evo_credentials.json", "evobulut_credentials.json",
    "veri_konumu.txt", "VERITABANI_KONUMU.txt", "ILK_YONETICI_SIFRE.txt"
)
$args = @($Src, $HedefApp, "/MIR", "/R:2", "/W:2", "/NFL", "/NDL", "/NJH", "/NJS", "/XF") + $xf
L "Yerinde uygulama geri yukleme (MIR)..."
$rc = Start-Process -FilePath "$env:SystemRoot\System32\robocopy.exe" -WorkingDirectory $cwd `
    -ArgumentList $args -Wait -PassThru -NoNewWindow
if ($rc.ExitCode -ge 8) { throw "robocopy exit $($rc.ExitCode)" }

# Korunanlari geri yaz
Get-ChildItem $Korunan -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    $rel = $_.FullName.Substring($Korunan.Length).TrimStart('\')
    $dest = Join-Path $HedefKok $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    Copy-Item -Force $_.FullName $dest
    L "Geri yazildi: $rel"
}

$sha = (Get-FileHash (Join-Path $HedefApp "CinMuhasebe.exe") -Algorithm SHA256).Hash
L "KURTARMA TAMAM SHA=$sha yedek=$Geri"
Write-Host "BAGLANTI ve DB dokunulmadi. Masaustu kisayolu ayni kaldi."
if (-not $AcmaYok) {
    Start-Process -FilePath (Join-Path $HedefApp "CinMuhasebe.exe") -WorkingDirectory $HedefApp
}
