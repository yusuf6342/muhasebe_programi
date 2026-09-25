@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Cin Muhasebe - Kurulum

rem Bu dosya cift tiklayinca metin aciliyorsa PowerShell'de sunu calistirin:
rem irm https://raw.githubusercontent.com/yusuf6342/muhasebe_programi/main/kurulum_masaustu.ps1 | iex

echo.
echo  Cin Muhasebe kuruluyor...
echo  (GitHub'dan indirilecek, masaustune EXE kisayolu eklenecek)
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
  "$py = Get-Command py -ErrorAction SilentlyContinue;" ^
  "if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue };" ^
  "if (-not $py) { throw 'Python bulunamadi' };" ^
  "$exe = Join-Path $dest 'dist\CinMuhasebe\CinMuhasebe.exe';" ^
  "if (-not (Test-Path $exe)) { $exe = Join-Path $dest 'dist\CinMuhasebe.exe' };" ^
  "if (-not (Test-Path $exe)) { Write-Host 'EXE olusturuluyor...'; & $py.Source -m pip install PyInstaller; & $py.Source -m PyInstaller (Join-Path $dest 'CinMuhasebe.spec') --noconfirm; $exe = Join-Path $dest 'dist\CinMuhasebe\CinMuhasebe.exe'; if (-not (Test-Path $exe)) { $exe = Join-Path $dest 'dist\CinMuhasebe.exe' } };" ^
  "if (-not (Test-Path $exe)) { throw 'CinMuhasebe.exe olusturulamadi' };" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$lnkPath = Join-Path $desktop 'Cin Muhasebe.lnk';" ^
  "$ico = Join-Path $dest 'assets\branding\CinLogo.ico';" ^
  "if (-not (Test-Path -LiteralPath $ico)) { $ico = Join-Path $dest 'assets\branding\cin_muhasebe.ico' };" ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "$s = $w.CreateShortcut($lnkPath);" ^
  "$s.TargetPath = $exe;" ^
  "$s.WorkingDirectory = (Split-Path -Parent $exe);" ^
  "$s.WindowStyle = 1;" ^
  "$s.Description = 'Cin Muhasebe Programı';" ^
  "if (Test-Path -LiteralPath $ico) { $s.IconLocation = ($ico + ',0') };" ^
  "$s.Save();" ^
  "Write-Host '';" ^
  "Write-Host ('Kurulum klasoru: ' + $dest);" ^
  "Write-Host ('Masaustu kisayol: ' + $lnkPath);" ^
  "Write-Host '' ;" ^
  "Write-Host 'Masaustunde Cin Muhasebe kisayolunu goreceksiniz.';" ^
  "explorer.exe $desktop;"

if errorlevel 1 (
  echo.
  echo Hata: kurulum basarisiz. Internet baglantisini, Python kurulumunu ve PyInstaller yapilandirmasini kontrol edin.
  pause
  exit /b 1
)

echo.
echo Bitti. Masaustunde "Cin Muhasebe" kisayoluna cift tiklayin.
echo EXE bazli acilis kullaniliyor.
pause
