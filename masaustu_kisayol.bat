@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "EXE=%~dp0dist\CinMuhasebe\CinMuhasebe.exe"
if not exist "%EXE%" set "EXE=%~dp0dist\CinMuhasebe.exe"
if not exist "%EXE%" (
  echo EXE bulunamadi: dist\CinMuhasebe\CinMuhasebe.exe
  echo Once PyInstaller ile exe olusturulmasi gerekiyor.
  echo Ornek: .venv\Scripts\python.exe -m PyInstaller --noconfirm CinMuhasebe.spec
  pause
  exit /b 1
)

echo Cin Muhasebe masaustu kisayolu olusturuluyor...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\create_shortcut.ps1"
if errorlevel 1 (
  echo Hata: kisayol olusturulamadi.
  pause
  exit /b 1
)

echo.
echo Masaustunde "Cin Muhasebe" kisayolu hazir.
echo Cift tiklayinca uygulama EXE ile acilir.
explorer.exe "%USERPROFILE%\Desktop"
pause
