@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>&1
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    echo Hata: Python bulunamadi.
    echo https://www.python.org/downloads/ adresinden Python 3 kurun.
    echo Kurulumda "Add Python to PATH" secenegini isaretleyin.
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Sanal ortam olusturuluyor...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Hata: sanal ortam olusturulamadi.
    pause
    exit /b 1
  )
)

echo Bagimliliklar kontrol ediliyor...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Hata: bagimliliklar yuklenemedi.
  pause
  exit /b 1
)

echo Cin Muhasebe baslatiliyor...
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  echo.
  echo Program hata ile kapandi.
  pause
  exit /b 1
)
