#!/usr/bin/env bash
# Linux / macOS: masaüstüne Muhasebe Programı kısayolu kurar
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
chmod +x "$ROOT/calistir.sh" "$ROOT/calistir.command" "$ROOT/masaustu_kisayol.sh" 2>/dev/null || true

if [[ "$(uname -s)" == "Darwin" ]]; then
  DEST="${HOME}/Desktop/Muhasebe Programi.command"
  cat > "$DEST" <<EOF
#!/bin/bash
cd "$ROOT"
exec ./calistir.command
EOF
  chmod +x "$DEST"
  echo "Hazır: $DEST"
  echo "Finder’da masaüstündeki “Muhasebe Programi” dosyasına çift tıklayın."
  exit 0
fi

DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
mkdir -p "$DESKTOP_DIR" "$HOME/.local/share/applications"

DESKTOP_FILE="$DESKTOP_DIR/Muhasebe-Programi.desktop"
APP_FILE="$HOME/.local/share/applications/muhasebe-programi.desktop"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Muhasebe Programı
Comment=Stok, cari, fatura ve finans uygulaması
Exec=$ROOT/calistir.sh
Path=$ROOT
Icon=accessories-calculator
Terminal=false
Categories=Office;Finance;
EOF

cp "$DESKTOP_FILE" "$APP_FILE"
chmod +x "$DESKTOP_FILE" "$APP_FILE"

if command -v gio >/dev/null 2>&1; then
  gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
fi

echo "Hazır: $DESKTOP_FILE"
echo "Masaüstündeki “Muhasebe Programı” simgesine çift tıklayın."
