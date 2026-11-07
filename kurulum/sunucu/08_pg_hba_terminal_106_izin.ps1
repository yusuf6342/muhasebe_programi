#Requires -Version 5.1
<#
.SYNOPSIS
  Ana makine (DESKTOP-CGSE5GK): yalniz 192.168.1.106/32 icin dort kabul/restore DB hostssl izni.

.DESCRIPTION
  - Veritabani OLUSTURMAZ / SILMEZ.
  - Mevcut 192.168.1.133 (ve diger) satirlari KORUR.
  - Once pg_hba.conf yedegi alir.
  - v2 dosya duzeltmesi: Add-Content/Set-Content KULLANMAZ (UTF-16 BOM riski yok).
    Okuma/yazma UTF-8 BOM'suz veya mevcut bayt duzeniyle AppendAllText.
  - Eklenen satirlari dogrular; pg_ctl reload.

.PARAMETER PgData
  PostgreSQL data dizini (varsayilan 17).

.PARAMETER Cidr
  Izin verilecek istemci (varsayilan 192.168.1.106/32).

.PARAMETER KorunanCidr
  Dokunulmayacak mevcut terminal (bilgi/dogrulama; varsayilan 192.168.1.133).
#>
param(
    [string]$PgData = "C:\Program Files\PostgreSQL\17\data",
    [string]$Cidr = "192.168.1.106/32",
    [string]$KorunanCidr = "192.168.1.133",
    [string]$AppUser = "cin_app"
)

$ErrorActionPreference = "Stop"
$hba = Join-Path $PgData "pg_hba.conf"
if (-not (Test-Path -LiteralPath $hba)) {
    throw "pg_hba.conf yok: $hba — bu betik ANA MAKINEDE (PostgreSQL sunucusu) calismali."
}

$dbs = @(
    "cin_sistem_kabul_20261105",
    "cin_firma_kabul_20261105",
    "cin_sistem_restore_20261105",
    "cin_firma_restore_20261105"
)

# --- v2: guvenli okuma (BOM / encoding) ---
function Read-HbaText([string]$path) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        return [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    }
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        throw "pg_hba.conf UTF-16 LE BOM ile basliyor — PostgreSQL bunu okuyamayabilir. Yedekten duzeltin."
    }
    if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        throw "pg_hba.conf UTF-16 BE BOM ile basliyor — duzeltin."
    }
    # Tipik PG Windows: UTF-8 veya ASCII
    return [System.Text.Encoding]::UTF8.GetString($bytes)
}

function Append-HbaLines([string]$path, [string[]]$lines) {
    # v2: Set-Content/Add-Content YOK — UTF-8 BOM'suz ekle
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $block = "`r`n" + ($lines -join "`r`n") + "`r`n"
    [System.IO.File]::AppendAllText($path, $block, $utf8)
}

Write-Host "=== pg_hba: terminal $Cidr (kabul/restore x4) ===" -ForegroundColor Cyan
Write-Host "HBA : $hba"
Write-Host "Korunan istemci ornegi: $KorunanCidr (silinmez/degistirilmez)"

$once = Read-HbaText $hba
$yedek = "$hba.bak_terminal106_" + (Get-Date -Format "yyyyMMdd_HHmmss")
Copy-Item -LiteralPath $hba -Destination $yedek -Force
Write-Host "Yedek: $yedek" -ForegroundColor Green

$ekler = @()
$zaten = @()
foreach ($db in $dbs) {
    $satir = "hostssl  $db  $AppUser  $Cidr  scram-sha-256"
    # Ayni DB + ayni CIDR zaten varsa atla
    $pattern = [regex]::Escape("hostssl") + "\s+" + [regex]::Escape($db) + "\s+" +
        [regex]::Escape($AppUser) + "\s+" + [regex]::Escape($Cidr)
    if ($once -match $pattern) {
        $zaten += $satir
        Write-Host "Zaten var (atlandi): $satir"
    } else {
        $ekler += $satir
    }
}

$header = @(
    "# CinMuhasebe — ikinci terminal DENEME $(Get-Date -Format o)",
    "# istemci=$Cidr bilgisayar=DESKTOP-NB7SBPA — mevcut $KorunanCidr satirlari korunur"
)

if ($ekler.Count -gt 0) {
    Append-HbaLines $hba ($header + $ekler)
    foreach ($s in $ekler) { Write-Host "Eklendi: $s" -ForegroundColor Green }
} else {
    Write-Host "Eklenecek yeni satir yok."
}

$sonra = Read-HbaText $hba
$hata = 0
foreach ($db in $dbs) {
    $pattern = [regex]::Escape("hostssl") + "\s+" + [regex]::Escape($db) + "\s+" +
        [regex]::Escape($AppUser) + "\s+" + [regex]::Escape($Cidr) + "\s+scram-sha-256"
    if ($sonra -notmatch $pattern) {
        Write-Host "DOGRULAMA BASARISIZ: $db + $Cidr" -ForegroundColor Red
        $hata++
    }
}
# Korunan 133 satirlarinin kaybolmadigini kontrol et (varsa)
$korunanOrnek = 0
foreach ($db in $dbs) {
    if ($once -match ([regex]::Escape($KorunanCidr)) -and $sonra -match ([regex]::Escape($KorunanCidr))) {
        $korunanOrnek++
        break
    }
}
if ($once -match [regex]::Escape($KorunanCidr)) {
    if ($sonra -notmatch [regex]::Escape($KorunanCidr)) {
        Write-Host "KRITIK: $KorunanCidr satirlari kaybolmus gorunuyor — yedekten geri yukleyin: $yedek" -ForegroundColor Red
        $hata++
    } else {
        Write-Host "Korunan istemci ($KorunanCidr) satirlari duruyor." -ForegroundColor Green
    }
} else {
    Write-Host "Not: HBA metninde $KorunanCidr bulunamadi (farkli CIDR yazilmis olabilir); yine de mevcut satirlar silinmedi." -ForegroundColor Yellow
}

$pgCtl = "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe"
if (Test-Path $pgCtl) {
    & $pgCtl reload -D $PgData
    Write-Host "pg_ctl reload exit=$LASTEXITCODE"
} else {
    Write-Warning "pg_ctl yok; Restart-Service postgresql* veya pg_ctl reload elle."
}

$rapor = [ordered]@{
    zaman            = (Get-Date -Format o)
    makine           = $env:COMPUTERNAME
    hba              = $hba
    yedek            = $yedek
    cidr             = $Cidr
    korunan_cidr     = $KorunanCidr
    eklenen          = $ekler
    zaten_var        = $zaten
    dogrulama_hata   = $hata
    not              = "DB olusturulmadi. Yalniz hostssl+scram. v2: AppendAllText UTF8 no BOM."
}
$raporYol = Join-Path $env:TEMP ("pg_hba_terminal106_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".json")
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($raporYol, (($rapor | ConvertTo-Json -Depth 5) + "`n"), $utf8)
Write-Host "Rapor: $raporYol"
if ($hata -gt 0) {
    Write-Host "HBA dogrulama hatali — exit 2" -ForegroundColor Red
    exit 2
}
Write-Host "TAMAM — $Cidr icin 4 DB hostssl hazir (veya zaten vardi)." -ForegroundColor Green
exit 0
