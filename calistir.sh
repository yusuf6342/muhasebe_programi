#!/usr/bin/env bash
# Muhasebe programı — kurulum + çalıştırma
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "Hata: Python bulunamadı. https://www.python.org/downloads/"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Sanal ortam oluşturuluyor..."
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Bağımlılıklar kontrol ediliyor..."
pip install -q -r requirements.txt

echo "Cin Muhasebe başlatılıyor..."
exec python main.py
