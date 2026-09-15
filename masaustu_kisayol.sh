#!/usr/bin/env bash
# Linux / macOS: masaüstüne Cin Muhasebe kısayolu kurar
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
chmod +x "$ROOT/calistir.sh" "$ROOT/calistir.command" "$ROOT/masaustu_kisayol.sh" 2>/dev/null || true

ICO="$ROOT/assets/branding/cin_muhasebe_icon_256.png"
if [[ ! -f "$ICO" ]]; then
  ICO="$ROOT/assets/branding/cin_muhasebe_icon.png"
fi
if [[ ! -f "$ICO" ]]; then
  ICO="accessories-calculator"
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  DEST="${HOME}/Desktop/Cin Muhasebe.command"
  cat > "$DEST" <<EOF
#!/bin/bash
cd "$ROOT"
exec ./calistir.command
EOF
  chmod +x "$DEST"
  echo "Hazır: $DEST"
  echo "Finder’da masaüstündeki “Cin Muhasebe” dosyasına çift tıklayın."
  exit 0
fi

DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
mkdir -p "$DESKTOP_DIR" "$HOME/.local/share/applications"

DESKTOP_FILE="$DESKTOP_DIR/Cin-Muhasebe.desktop"
APP_FILE="$HOME/.local/share/applications/cin-muhasebe.desktop"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Cin Muhasebe
Comment=Güvenli ve Düzenli İşletme Yönetimi
Exec=$ROOT/calistir.sh
Path=$ROOT
Icon=$ICO
Terminal=false
Categories=Office;Finance;
EOF

cp "$DESKTOP_FILE" "$APP_FILE"
chmod +x "$DESKTOP_FILE" "$APP_FILE"

if command -v gio >/dev/null 2>&1; then
  gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
fi

echo "Hazır: $DESKTOP_FILE"
echo "Masaüstündeki “Cin Muhasebe” simgesine çift tıklayın."
