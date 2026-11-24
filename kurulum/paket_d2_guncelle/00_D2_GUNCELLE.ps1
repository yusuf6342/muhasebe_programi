#Requires -Version 5.1
<#
  D2 program kurulum/güncelleme — PG/DB/Evo/mali kayıt YOK.
  Aktif baglanti_ayari.json, kullanıcı ayarları, sertifika korunur.

  Bilinen PC:
    DESKTOP-CGSE5GK (Ana)     → host 127.0.0.1
    DESKTOP-FL08BVD (T1)      → host 192.168.1.114
    DESKTOP-NB7SBPA (T2)      → host 192.168.1.114

  -Rol ANA | TERMINAL1 | TERMINAL2 | AUTO
  -PaketKok paket kökü (CinMuhasebe\ + kurulum\)
  -HedefKok test için alternatif kurulum kökü
  -Force aynı SHA olsa da yeniden kopyala / SHA uyumsuzluğunu yoksay
  -AcmaYok işlem sonunda programı açma
#>
param(
    [string]$PaketKok = "",
    [ValidateSet("AUTO", "ANA", "TERMINAL1", "TERMINAL2")]
    [string]$Rol = "AUTO",
    [string]$HedefKok = "",
    [switch]$Force,
    [switch]$AcmaYok,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Log([string]$Msg, [string]$Level = "INFO") {
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Msg
    Write-Host $line
    if ($script:LogFile) {
        Add-Content -Path $script:LogFile -Value $line -Encoding UTF8
    }
}

$RolProfil = @{
    ANA = @{
        Rol = "ANA"
        KisayolAdi = "CİN MUHASEBE — DNM D2 — ANA"
        BeklenenHost = "127.0.0.1"
        TerminalKimligi = "DNM-D2-ANA"
        PcAdi = "DESKTOP-CGSE5GK"
    }
    TERMINAL1 = @{
        Rol = "TERMINAL"
        KisayolAdi = "CİN MUHASEBE — DNM D2 — TERMINAL"
        BeklenenHost = "192.168.1.114"
        TerminalKimligi = "DNM-D2-FL08BVD"
        PcAdi = "DESKTOP-FL08BVD"
    }
    TERMINAL2 = @{
        Rol = "TERMINAL"
        KisayolAdi = "CİN MUHASEBE — DNM D2 — TERMINAL"
        BeklenenHost = "192.168.1.114"
        TerminalKimligi = "DNM-D2-NB7SBPA"
        PcAdi = "DESKTOP-NB7SBPA"
    }
}
$PcProfil = @{
    "DESKTOP-CGSE5GK" = "ANA"
    "DESKTOP-FL08BVD" = "TERMINAL1"
    "DESKTOP-NB7SBPA" = "TERMINAL2"
}

$Pc = $env:COMPUTERNAME
if ($Rol -eq "AUTO") {
    if (-not $PcProfil.ContainsKey($Pc)) {
        throw "YANLIS MAKINE / ROL: PC=$Pc. Desteklenen: DESKTOP-CGSE5GK / FL08BVD / NB7SBPA veya -Rol ANA|TERMINAL1|TERMINAL2"
    }
    $Rol = $PcProfil[$Pc]
}
$Prof = $RolProfil[$Rol]
Write-Host "PC=$Pc RolSecim=$Rol Rol=$($Prof.Rol) beklenen_host=$($Prof.BeklenenHost)"

if (-not $PaketKok) {
    $PaketKok = Split-Path -Parent $PSScriptRoot
    if (-not (Test-Path (Join-Path $PaketKok "CinMuhasebe\CinMuhasebe.exe"))) {
        $PaketKok = $PSScriptRoot
    }
}
$PaketKok = (Resolve-Path $PaketKok).Path
$Src = Join-Path $PaketKok "CinMuhasebe"
$SrcExe = Join-Path $Src "CinMuhasebe.exe"
if (-not (Test-Path $SrcExe)) { throw "EXE yok: $SrcExe" }

# Bütünlük: pakette EXE + _internal
$Internal = Join-Path $Src "_internal"
if (-not (Test-Path $Internal)) { throw "Eksik paket: _internal yok ($Internal)" }

$BeklenenSha = Get-Content (Join-Path $PSScriptRoot "BEKLENEN_SHA256.txt") -ErrorAction SilentlyContinue |
    Select-Object -First 1
$SrcSha = (Get-FileHash $SrcExe -Algorithm SHA256).Hash.ToUpperInvariant()
if ($BeklenenSha -and ($SrcSha -ne $BeklenenSha.Trim().ToUpperInvariant()) -and -not $Force) {
    throw "EXE SHA uyusmuyor. Beklenen=$BeklenenSha Gelen=$SrcSha (Force ile gecebilirsiniz)"
}

if (-not $HedefKok) {
    $HedefKok = Join-Path $env:LOCALAPPDATA "CinMuhasebe\DNM_D2"
}
$HedefApp = Join-Path $HedefKok "CinMuhasebe"
$HedefExe = Join-Path $HedefApp "CinMuhasebe.exe"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Geri = Join-Path (Split-Path $HedefKok -Parent) ("DNM_D2_GERI_" + $Stamp)
if ($HedefKok -like "*\CinMuhasebe\DNM_D2") {
    $Geri = Join-Path $env:LOCALAPPDATA "CinMuhasebe\DNM_D2_GERI_$Stamp"
} else {
    $Geri = Join-Path $HedefKok ("_GERI_" + $Stamp)
}
$StageApp = Join-Path $HedefKok ("_stage_yeni_" + $Stamp)
$script:LogFile = Join-Path $HedefKok "GUNCELLEME_LOG.txt"
New-Item -ItemType Directory -Force -Path $HedefKok | Out-Null
Write-Log "Basladi PaketKok=$PaketKok Hedef=$HedefKok SrcSha=$SrcSha Force=$Force DryRun=$DryRun"

$KuruluVar = Test-Path $HedefExe
$MevcutSha = $null
if ($KuruluVar) {
    $MevcutSha = (Get-FileHash $HedefExe -Algorithm SHA256).Hash.ToUpperInvariant()
    Write-Log "Mevcut kurulum SHA=$MevcutSha"
}

# Idempotent: aynı sürüm
if ($KuruluVar -and $MevcutSha -eq $SrcSha -and -not $Force) {
    Write-Log "Ayni surum zaten kurulu — dosya kopyasi atlandi (idempotent)"
    $skipCopy = $true
} else {
    $skipCopy = $false
}

if ($DryRun) {
    Write-Log "DRY-RUN — yazma yok"
    exit 0
}

$Desk = [Environment]::GetFolderPath("Desktop")
$CaDir = Join-Path $env:APPDATA "postgresql"
$CaPath = Join-Path $CaDir "root.crt"
$Korunan = $null

try {
    if ($skipCopy) {
        Write-Log "Idempotent yol: yedek/kopya yok; kisayol dogrulanacak"
        New-Item -ItemType Directory -Force -Path $Geri | Out-Null
    }
    else {
        # Uygulama açıksa kullanıcıdan normal kapanış iste (Force kill / otomatik kayıt YOK)
        $acik = @(Get-Process CinMuhasebe -ErrorAction SilentlyContinue)
        if ($acik.Count -gt 0) {
            Write-Log "CinMuhasebe acik PID=$($acik.Id -join ','); normal kapanis bekleniyor"
            Write-Host ""
            Write-Host "CinMuhasebe acik. Kaydedilmemis makbuz/sepeti kendiniz kaydedip uygulamayi NORMAL kapatin."
            Write-Host "Zorla kapatma ve otomatik kayit YOK. Kapaninca guncelleme devam eder (en fazla ~2 dk)."
            Write-Host ""
            $deadline = (Get-Date).AddSeconds(120)
            while ((Get-Date) -lt $deadline) {
                if (@(Get-Process CinMuhasebe -ErrorAction SilentlyContinue).Count -eq 0) { break }
                Start-Sleep -Seconds 2
            }
            if (@(Get-Process CinMuhasebe -ErrorAction SilentlyContinue).Count -gt 0) {
                throw "CinMuhasebe hala acik. Kaydedip normal kapatip GUNCELLE.cmd'yi yeniden calistirin; zorla kapatma yapilmaz."
            }
            Start-Sleep -Seconds 1
        }

        New-Item -ItemType Directory -Force -Path $Geri | Out-Null
        $Korunan = Join-Path $Geri "_korunan_aktif"
        New-Item -ItemType Directory -Force -Path $Korunan | Out-Null
        if (Test-Path $HedefApp) {
            robocopy $HedefApp (Join-Path $Geri "CinMuhasebe") /E /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
        }
        Get-ChildItem $HedefKok -Filter "baglanti*.json" -ErrorAction SilentlyContinue |
            Copy-Item -Destination $Geri -Force -ErrorAction SilentlyContinue
        Get-ChildItem $Desk -Filter "*.lnk" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "*MUHASEBE*" -or $_.Name -like "*Cin*" -or $_.Name -like "*DNM*" } |
            ForEach-Object { Copy-Item $_.FullName (Join-Path $Geri $_.Name) -Force }

        $KorunanDosyalar = @(
            (Join-Path $HedefApp "baglanti_ayari.json"),
            (Join-Path $HedefKok "baglanti_ayari.json"),
            (Join-Path $HedefApp "kullanici_ayarlari.json"),
            (Join-Path $HedefApp "ayarlar.json"),
            (Join-Path $HedefApp "credentials.json"),
            (Join-Path $HedefApp "evo_credentials.json"),
            (Join-Path $HedefApp "evobulut_credentials.json")
        )
        foreach ($p in $KorunanDosyalar) {
            if (Test-Path $p) {
                $rel = $p.Substring($HedefKok.Length).TrimStart('\')
                $dest = Join-Path $Korunan $rel
                New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
                Copy-Item -Force $p $dest
                Write-Log "Korundu: $rel"
            }
        }
        if (Test-Path $CaPath) { Copy-Item -Force $CaPath (Join-Path $Geri "root.crt") }
    }

    if (-not $skipCopy) {
        # Geçici alana kopyala → bütünlük → swap
        if (Test-Path $StageApp) { Remove-Item -Recurse -Force $StageApp }
        New-Item -ItemType Directory -Force -Path $StageApp | Out-Null
        Write-Log "Stage kopya: $Src -> $StageApp"
        $rc = Start-Process robocopy.exe -ArgumentList @(
            "`"$Src`"", "`"$StageApp`"", "/E", "/R:2", "/W:2", "/NFL", "/NDL", "/NJH", "/NJS",
            "/XF", "baglanti_ayari.json", "kullanici_ayarlari.json", "ayarlar.json",
            "credentials.json", "evo_credentials.json", "evobulut_credentials.json"
        ) -Wait -PassThru -NoNewWindow
        if ($rc.ExitCode -ge 8) { throw "robocopy stage exit $($rc.ExitCode)" }

        $StageExe = Join-Path $StageApp "CinMuhasebe.exe"
        if (-not (Test-Path $StageExe)) { throw "Stage EXE yok" }
        if (-not (Test-Path (Join-Path $StageApp "_internal"))) { throw "Stage _internal yok — eksik paket" }
        $StageSha = (Get-FileHash $StageExe -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($StageSha -ne $SrcSha) { throw "Stage SHA uyusmuyor: $StageSha <> $SrcSha" }

        # Eski uygulamayı kenara al, stage'i yerine koy
        $OldSwapName = "_eski_swap_" + $Stamp
        $OldSwap = Join-Path $HedefKok $OldSwapName
        if (Test-Path $HedefApp) {
            Rename-Item -Path $HedefApp -NewName $OldSwapName
        }
        Rename-Item -Path $StageApp -NewName "CinMuhasebe"
        if (Test-Path $OldSwap) {
            Write-Log "Eski klasor yedek adinda: $OldSwap"
        }
        Write-Log "Program dosyalari guncellendi"
    }

    # Korunan ayarları geri yaz
    if ($Korunan -and (Test-Path $Korunan)) {
        Get-ChildItem $Korunan -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            $rel = $_.FullName.Substring($Korunan.Length).TrimStart('\')
            $dest = Join-Path $HedefKok $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
            Copy-Item -Force $_.FullName $dest
            Write-Log "Geri yazildi: $rel"
        }
    }

    # Örnek profil (aktif dosyaya dokunulmaz)
    $Ornek = @{
        kipi = "yerel_ag_postgres"
        schema_surum = 1
        profil_adi = "DNM İKİNCİ DÖNEM DENEME"
        postgres = @{
            host = $Prof.BeklenenHost
            port = 5432
            sistem_db = "cin_sistem_dnm_d2_20260901"
            firma_db = "cin_firma_dnm_d2_20260901"
            kullanici = "cin_app"
            sslmode = "verify-full"
            ortam = "DENEME"
            terminal_kimligi = $Prof.TerminalKimligi
        }
        otomatik_aktarim = $false
        sqlite_zorlama_yok = $true
    }
    $Ornek | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $HedefKok "baglanti_ayari.D2_ORNEK.json") -Encoding UTF8

    $AktifBag = Join-Path $HedefApp "baglanti_ayari.json"
    if (-not (Test-Path $AktifBag)) { $AktifBag = Join-Path $HedefKok "baglanti_ayari.json" }
    if (Test-Path $AktifBag) {
        try {
            $aktif = Get-Content $AktifBag -Raw -Encoding UTF8 | ConvertFrom-Json
            $h = [string]$aktif.postgres.host
            Write-Log "Aktif baglanti host=$h db=$($aktif.postgres.sistem_db)/$($aktif.postgres.firma_db) terminal=$($aktif.postgres.terminal_kimligi)"
            if ($h -and ($h -ne $Prof.BeklenenHost) -and -not $Force) {
                Write-Warning "Aktif host ($h) beklenen $($Prof.BeklenenHost) degil — DOSYA DEGISTIRILMEDI."
            }
        } catch {
            Write-Warning "baglanti_ayari.json okunamadi: $_"
        }
    } else {
        Write-Warning "Aktif baglanti_ayari.json yok — ornek yazildi. Bilinçli kopyalayın."
    }

    # Sertifika
    $CaSrc = Join-Path $PSScriptRoot "root.crt"
    if (-not (Test-Path $CaPath) -and (Test-Path $CaSrc)) {
        New-Item -ItemType Directory -Force -Path $CaDir | Out-Null
        Copy-Item -Force $CaSrc $CaPath
        Write-Log "root.crt ilk kez kopyalandi"
    } elseif (Test-Path $CaPath) {
        Write-Log "Mevcut root.crt korundu"
    }

    # Kısayollar — yalnız gerçek DNM_D2 kurulumunda masaüstüne yaz
    $GercekKurulum = ($HedefKok -eq (Join-Path $env:LOCALAPPDATA "CinMuhasebe\DNM_D2"))
    $Wsh = New-Object -ComObject WScript.Shell
    $DeskList = @()
    if ($GercekKurulum) {
        $DeskList = @(
            $Desk,
            [Environment]::GetFolderPath('CommonDesktopDirectory'),
            (Join-Path $env:USERPROFILE 'Desktop'),
            (Join-Path $env:USERPROFILE 'OneDrive\Desktop'),
            (Join-Path $env:USERPROFILE 'OneDrive\Masaüstü')
        ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
    } else {
        Write-Log "Test/alternatif HedefKok — masaüstü kisayolu yazilmaz ($HedefKok)"
    }

    function Set-DnmKisayol([string]$LnkPath) {
        try {
            if (Test-Path $LnkPath) {
                Copy-Item $LnkPath (Join-Path $Geri ((Split-Path $LnkPath -Leaf) + '.bak')) -Force -ErrorAction SilentlyContinue
            }
            $Lnk = $Wsh.CreateShortcut($LnkPath)
            $Lnk.TargetPath = $HedefExe
            $Lnk.WorkingDirectory = $HedefApp
            $Lnk.Arguments = ''
            $Lnk.IconLocation = "$HedefExe,0"
            $Lnk.Description = "Cin Muhasebe — DNM_D2 ($($Prof.Rol))"
            $Lnk.Save()
            Write-Log "Kisayol: $LnkPath"
        } catch {
            Write-Warning ("Kisayol yazilamadi: {0} — {1}" -f $LnkPath, $_.Exception.Message)
        }
    }

    $KisayolAdlari = @($Prof.KisayolAdi, 'Cin Muhasebe')
    foreach ($D in $DeskList) {
        foreach ($Ad in $KisayolAdlari) {
            $LnkPath = Join-Path $D "$Ad.lnk"
            if (-not (Test-Path $LnkPath) -and $Ad -ne $Prof.KisayolAdi) { continue }
            Set-DnmKisayol $LnkPath
        }
        Get-ChildItem $D -Filter '*.lnk' -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $cur = $Wsh.CreateShortcut($_.FullName)
                $tp = [string]$cur.TargetPath
                if ($tp -and ($tp -like '*\CinMuhasebe\DNM_D2\*')) {
                    if ($tp -ne $HedefExe -or [string]$cur.WorkingDirectory -ne $HedefApp) {
                        Set-DnmKisayol $_.FullName
                    } else {
                        Write-Log ("Kisayol zaten dogru: {0}" -f $_.FullName)
                    }
                }
            } catch {}
        }
    }
    $LnkPath = Join-Path $Desk "$($Prof.KisayolAdi).lnk"

    $YeniSha = (Get-FileHash $HedefExe -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($YeniSha -ne $SrcSha) { throw "Hedef EXE SHA kaynakla uyusmuyor" }

    $Sonuc = @{
        format = "d2-guncelleme-sonuc-v2"
        zaman = (Get-Date -Format o)
        makine = $Pc
        rol_secim = $Rol
        rol = $Prof.Rol
        hedef_exe = $HedefExe
        exe_sha256 = $YeniSha
        paket_sha_beklenen = if ($BeklenenSha) { $BeklenenSha.Trim() } else { $null }
        yedek = $Geri
        baglanti_korundu = (Test-Path $AktifBag)
        kisayol = $LnkPath
        skip_copy = $skipCopy
        kurulum_modu = $(if ($KuruluVar) { "guncelleme" } else { "ilk_kurulum" })
    }
    ($Sonuc | ConvertTo-Json -Depth 5) | Set-Content (Join-Path $HedefKok "SON_GUNCELLEME.json") -Encoding UTF8
    ($Sonuc | ConvertTo-Json -Depth 5) | Set-Content (Join-Path $Geri "SON_GUNCELLEME.json") -Encoding UTF8

    Write-Log "GUNCELLEME TAMAM EXE=$HedefExe SHA=$YeniSha"
    Write-Host "GUNCELLEME TAMAM"
    Write-Host "EXE: $HedefExe"
    Write-Host "SHA: $YeniSha"
    Write-Host "Yedek: $Geri"

    if (-not $AcmaYok) {
        Write-Log "Program aciliyor..."
        Start-Process -FilePath $HedefExe -WorkingDirectory $HedefApp
    }
}
catch {
    Write-Log ("HATA: {0}" -f $_.Exception.Message) "ERROR"
    # Stage kalıntısını temizle; yedekten geri yükleme dene
    if ((Test-Path $StageApp) -and -not (Test-Path $HedefExe)) {
        Write-Log "Stage temizleniyor (basarisiz)"
        Remove-Item -Recurse -Force $StageApp -ErrorAction SilentlyContinue
    }
    $YedekApp = Join-Path $Geri "CinMuhasebe"
    if ((-not (Test-Path $HedefExe)) -and (Test-Path (Join-Path $YedekApp "CinMuhasebe.exe"))) {
        Write-Log "Geri yukleme deneniyor: $YedekApp"
        if (Test-Path $HedefApp) { Remove-Item -Recurse -Force $HedefApp -ErrorAction SilentlyContinue }
        Copy-Item -Recurse -Force $YedekApp $HedefApp
        if ($Korunan -and (Test-Path $Korunan)) {
            Get-ChildItem $Korunan -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
                $rel = $_.FullName.Substring($Korunan.Length).TrimStart('\')
                $dest = Join-Path $HedefKok $rel
                New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
                Copy-Item -Force $_.FullName $dest
            }
        }
        Write-Log "Onceki program dosyalari geri yuklendi"
    }
    throw
}
