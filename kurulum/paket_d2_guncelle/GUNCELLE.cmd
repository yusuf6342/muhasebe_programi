@echo off
setlocal EnableExtensions
REM Surucu harfinden bagimsiz — kendi klasorunden calisir.
REM Paket: SonGuncelleme\paket | paket | CinMuhasebe_DNM_D2_GUNCELLE_* | Surumler\*
REM Yanlis/eski pakete sessiz dusmez (GUNCELLE_PAKET_SEC.ps1).

set "KOK=%~dp0"
if "%KOK:~-1%"=="\" set "KOK=%KOK:~0,-1%"
set "SECICI=%KOK%\GUNCELLE_PAKET_SEC.ps1"
if not exist "%SECICI%" set "SECICI=%~dp0GUNCELLE_PAKET_SEC.ps1"
if not exist "%SECICI%" (
  echo HATA: GUNCELLE_PAKET_SEC.ps1 bulunamadi:
  echo   %KOK%\GUNCELLE_PAKET_SEC.ps1
  pause
  exit /b 1
)

set "PAKET="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%SECICI%" -Kok "%KOK%"`) do set "PAKET=%%I"
if not defined PAKET (
  echo.
  echo HATA: Gecerli guncelleme paketi secilemedi.
  pause
  exit /b 1
)

set "PS1=%PAKET%\kurulum\00_D2_GUNCELLE.ps1"
if not exist "%PS1%" (
  echo HATA: Guncelleme betigi bulunamadi:
  echo   %PS1%
  pause
  exit /b 1
)
if not exist "%PAKET%\CinMuhasebe\CinMuhasebe.exe" (
  echo HATA: Paket EXE yok:
  echo   %PAKET%\CinMuhasebe\CinMuhasebe.exe
  pause
  exit /b 1
)

echo.
echo  ============================================
echo   Cin Muhasebe — DNM D2 Kurulum / Guncelleme
echo  ============================================
echo   Paket: %PAKET%
echo.
echo   [1] Otomatik  (bu PC'nin kayitli rolune gore)
echo   [2] Ana Makine
echo   [3] Terminal 2
echo   [4] Vazgec
echo.
choice /C 1234 /N /M "Seciminiz"
set "SEC=%ERRORLEVEL%"
if "%SEC%"=="4" exit /b 0

set "ROL=AUTO"
if "%SEC%"=="2" set "ROL=ANA"
if "%SEC%"=="3" set "ROL=TERMINAL2"

echo.
echo Rol=%ROL% — basliyor...
echo Uygulama aciksa kaydedip normal kapatin; zorla kapatilmaz / otomatik kayit yok.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -PaketKok "%PAKET%" -Rol %ROL%
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo.
  echo HATA kodu: %ERR%
  echo Onceki program dosyalari korunmaya calisildi. Ayrinti: %%LOCALAPPDATA%%\CinMuhasebe\DNM_D2\GUNCELLEME_LOG.txt
)
echo.
pause
exit /b %ERR%
