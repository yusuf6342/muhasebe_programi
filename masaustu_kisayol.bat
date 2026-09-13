@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo Muhasebe Programi masaustu kisayolu olusturuluyor...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$target = Join-Path (Get-Location) 'calistir.bat';" ^
  "$lnkPath = Join-Path $desktop 'Muhasebe Programi.lnk';" ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "$s = $w.CreateShortcut($lnkPath);" ^
  "$s.TargetPath = $target;" ^
  "$s.WorkingDirectory = (Get-Location).Path;" ^
  "$s.WindowStyle = 1;" ^
  "$s.Description = 'Muhasebe Programini baslatir';" ^
  "$s.Save();" ^
  "Write-Host ('Hazir: ' + $lnkPath)"

if errorlevel 1 (
  echo Hata: kisayol olusturulamadi.
  pause
  exit /b 1
)

echo.
echo Masaustunde "Muhasebe Programi" kisayolu hazir.
echo Cift tiklayinca program acilir.
pause
