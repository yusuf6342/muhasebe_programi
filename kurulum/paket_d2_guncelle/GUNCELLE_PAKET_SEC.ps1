#Requires -Version 5.1
<#
  USB / paket kökünde geçerli D2 güncelleme paketini seçer.
  Yanlış/eski pakete sessiz düşmez; BUILD_INFO + EXE + 00_D2_GUNCELLE.ps1 doğrular.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Kok,
    [string]$BeklenenSurum = "",
    [switch]$Listele
)

$ErrorActionPreference = "Stop"

function Read-BuildInfo([string]$ExeDir) {
    $p = Join-Path $ExeDir "BUILD_INFO.txt"
    $m = @{ AppVersion = $null; ExeSha = $null; BuildStamp = $null }
    if (-not (Test-Path $p)) { return $m }
    foreach ($line in Get-Content $p -Encoding UTF8 -ErrorAction SilentlyContinue) {
        if ($line -match '^APP_VERSION=(.+)$') { $m.AppVersion = $Matches[1].Trim() }
        if ($line -match '^EXE_SHA256=(.+)$') { $m.ExeSha = $Matches[1].Trim().ToUpperInvariant() }
        if ($line -match '^BUILD_STAMP=(.+)$') { $m.BuildStamp = $Matches[1].Trim() }
    }
    return $m
}

function Read-BeklenenSurum([string]$Root) {
    foreach ($name in @("SHA256.txt", "BEKLENEN_SURUM.txt")) {
        $p = Join-Path $Root $name
        if (-not (Test-Path $p)) { continue }
        foreach ($line in Get-Content $p -Encoding UTF8 -ErrorAction SilentlyContinue) {
            if ($line -match '^APP_VERSION=(.+)$') { return $Matches[1].Trim() }
        }
    }
    return ""
}

$Kok = (Resolve-Path -LiteralPath $Kok).Path
if (-not $BeklenenSurum) {
    $BeklenenSurum = Read-BeklenenSurum $Kok
}

$adayKokler = New-Object System.Collections.Generic.List[string]
foreach ($rel in @("SonGuncelleme\paket", "paket")) {
    $adayKokler.Add((Join-Path $Kok $rel))
}
Get-ChildItem -LiteralPath $Kok -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "CinMuhasebe_DNM_D2_GUNCELLE_*" } |
    ForEach-Object { $adayKokler.Add($_.FullName) }
$surum = Join-Path $Kok "Surumler"
if (Test-Path $surum) {
    Get-ChildItem -LiteralPath $surum -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { $adayKokler.Add($_.FullName) }
}
$adayKokler.Add($Kok)

$gecerli = @()
$gecersiz = @()
$gorulen = @{}
foreach ($cand in $adayKokler) {
    if (-not $cand -or $gorulen.ContainsKey($cand.ToLowerInvariant())) { continue }
    $gorulen[$cand.ToLowerInvariant()] = $true
    $exe = Join-Path $cand "CinMuhasebe\CinMuhasebe.exe"
    $ps1 = Join-Path $cand "kurulum\00_D2_GUNCELLE.ps1"
    if (-not ((Test-Path $exe) -and (Test-Path $ps1))) {
        continue
    }
    $info = Read-BuildInfo (Join-Path $cand "CinMuhasebe")
    $shaDisk = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToUpperInvariant()
    $bekShaPath = Join-Path $cand "kurulum\BEKLENEN_SHA256.txt"
    $bekSha = $null
    if (Test-Path $bekShaPath) {
        $bekSha = ((Get-Content $bekShaPath -Raw -Encoding ASCII).Trim()).ToUpperInvariant()
    }
    $kayit = [pscustomobject]@{
        Path       = $cand
        AppVersion = $info.AppVersion
        BuildStamp = $info.BuildStamp
        ExeSha     = $shaDisk
        BuildSha   = $info.ExeSha
        BeklenenSha = $bekSha
    }
    $neden = $null
    if ($bekSha -and ($bekSha -ne $shaDisk)) {
        $neden = "EXE SHA BEKLENEN_SHA256 ile uyusmuyor"
    }
    elseif ($info.ExeSha -and ($info.ExeSha -ne $shaDisk)) {
        $neden = "EXE SHA BUILD_INFO ile uyusmuyor"
    }
    elseif ($BeklenenSurum -and $info.AppVersion -and ($info.AppVersion -ne $BeklenenSurum)) {
        $neden = "Surum $($info.AppVersion) != beklenen $BeklenenSurum"
    }
    elseif ($BeklenenSurum -and -not $info.AppVersion) {
        $neden = "BUILD_INFO APP_VERSION yok (beklenen $BeklenenSurum)"
    }
    if ($neden) {
        $gecersiz += [pscustomobject]@{ Path = $cand; Neden = $neden; AppVersion = $info.AppVersion }
        continue
    }
    $gecerli += $kayit
}

if ($Listele) {
    $gecerli | ForEach-Object { Write-Host ("OK  {0}  v={1}  stamp={2}" -f $_.Path, $_.AppVersion, $_.BuildStamp) }
    $gecersiz | ForEach-Object { Write-Host ("ELENEN  {0}  ({1})" -f $_.Path, $_.Neden) }
}

if ($gecerli.Count -eq 0) {
    Write-Host "HATA: Gecerli guncelleme paketi bulunamadi. Kok=$Kok" -ForegroundColor Red
    if ($BeklenenSurum) { Write-Host "Beklenen surum: $BeklenenSurum" }
    if ($gecersiz.Count -gt 0) {
        Write-Host "Elenen adaylar:"
        $gecersiz | ForEach-Object { Write-Host ("  - {0} :: {1}" -f $_.Path, $_.Neden) }
    } else {
        Write-Host "Aranan: SonGuncelleme\paket | paket | CinMuhasebe_DNM_D2_GUNCELLE_* | Surumler\* | kok"
        Write-Host "Gerekli: CinMuhasebe\CinMuhasebe.exe + kurulum\00_D2_GUNCELLE.ps1"
    }
    exit 2
}

function PreferansSkoru([string]$p) {
    $n = $p.ToLowerInvariant()
    if ($n -match 'cinmuhasebe_dnm_d2_guncelle_') { return 300 }
    if ($n -match '\\songuncelleme\\paket') { return 200 }
    if ($n -match '\\surumler\\') { return 100 }
    if ($n -match '\\paket$') { return 50 }
    return 0
}

$sec = $gecerli |
    Sort-Object @{ Expression = { PreferansSkoru $_.Path }; Descending = $true },
                @{ Expression = { $_.AppVersion }; Descending = $true },
                @{ Expression = { $_.BuildStamp }; Descending = $true },
                @{ Expression = { $_.Path }; Descending = $true } |
    Select-Object -First 1

# Stdout: yalnız paket yolu (CMD for /f için). Bilgi stderr'e.
[Console]::Error.WriteLine(("SECILEN_PAKET v={0} stamp={1} sha={2}" -f $sec.AppVersion, $sec.BuildStamp, $sec.ExeSha))
[Console]::Error.WriteLine(("SECILEN_YOL {0}" -f $sec.Path))
Write-Output $sec.Path
exit 0
