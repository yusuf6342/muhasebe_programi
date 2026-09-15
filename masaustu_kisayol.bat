@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo Cin Muhasebe masaustu kisayolu olusturuluyor...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$target = Join-Path (Get-Location) 'calistir.bat';" ^
  "$lnkPath = Join-Path $desktop 'Cin Muhasebe.lnk';" ^
  "$ico = Join-Path (Get-Location) 'assets\branding\cin_muhasebe.ico';" ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "$s = $w.CreateShortcut($lnkPath);" ^
  "$s.TargetPath = $target;" ^
  "$s.WorkingDirectory = (Get-Location).Path;" ^
  "$s.WindowStyle = 1;" ^
  "$s.Description = 'Cin Muhasebe Programı';" ^
  "if (Test-Path -LiteralPath $ico) { $s.IconLocation = ($ico + ',0') };" ^
  "$s.Save();" ^
  "Write-Host ('Hazir: ' + $lnkPath)"

if errorlevel 1 (
  echo Hata: kisayol olusturulamadi.
  pause
  exit /b 1
)

echo.
echo Masaustunde "Cin Muhasebe" kisayolu hazir.
echo Cift tiklayinca program acilir.
explorer.exe "%USERPROFILE%\Desktop"
pause
