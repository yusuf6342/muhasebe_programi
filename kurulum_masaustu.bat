@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Cin Muhasebe - Kurulum

rem Bu dosya cift tiklayinca metin aciliyorsa PowerShell'de sunu calistirin:
rem irm https://raw.githubusercontent.com/yusuf6342/muhasebe_programi/main/kurulum_masaustu.ps1 | iex

echo.
echo  Cin Muhasebe kuruluyor...
echo  (GitHub'dan indirilecek, masaustune kisayol eklenecek)
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$dest = Join-Path $env:USERPROFILE 'CinMuhasebe';" ^
  "$zip = Join-Path $env:TEMP 'muhasebe_programi.zip';" ^
  "$url = 'https://github.com/yusuf6342/muhasebe_programi/archive/refs/heads/main.zip';" ^
  "Write-Host 'Indiriliyor...';" ^
  "Invoke-WebRequest -Uri $url -OutFile $zip;" ^
  "if (Test-Path $dest) { Remove-Item -Recurse -Force $dest };" ^
  "New-Item -ItemType Directory -Path $dest | Out-Null;" ^
  "Write-Host 'Aciliyor...';" ^
  "Expand-Archive -Path $zip -DestinationPath $dest -Force;" ^
  "$inner = Get-ChildItem -Path $dest -Directory | Select-Object -First 1;" ^
  "Get-ChildItem -Path $inner.FullName | Move-Item -Destination $dest -Force;" ^
  "Remove-Item -Recurse -Force $inner.FullName;" ^
  "Remove-Item -Force $zip;" ^
  "$bat = Join-Path $dest 'calistir.bat';" ^
  "if (-not (Test-Path $bat)) { throw 'calistir.bat bulunamadi' };" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$lnkPath = Join-Path $desktop 'Cin Muhasebe.lnk';" ^
  "$ico = Join-Path $dest 'assets\branding\cin_muhasebe.ico';" ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "$s = $w.CreateShortcut($lnkPath);" ^
  "$s.TargetPath = $bat;" ^
  "$s.WorkingDirectory = $dest;" ^
  "$s.WindowStyle = 1;" ^
  "$s.Description = 'Cin Muhasebe Programı';" ^
  "if (Test-Path -LiteralPath $ico) { $s.IconLocation = ($ico + ',0') };" ^
  "$s.Save();" ^
  "Write-Host '';" ^
  "Write-Host ('Kurulum klasoru: ' + $dest);" ^
  "Write-Host ('Masaustu kisayol: ' + $lnkPath);" ^
  "explorer.exe $desktop;" ^
  "Write-Host '';" ^
  "Write-Host 'Masaustunde Cin Muhasebe kisayolunu goreceksiniz.';"

if errorlevel 1 (
  echo.
  echo Hata: kurulum basarisiz. Internet baglantisini ve Python kurulumunu kontrol edin.
  pause
  exit /b 1
)

echo.
echo Bitti. Masaustunde "Cin Muhasebe" kisayoluna cift tiklayin.
pause
