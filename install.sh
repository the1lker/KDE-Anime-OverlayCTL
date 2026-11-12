#!/usr/bin/env bash
# anime-overlay kurulumu: ~/.local/bin + otomatik başlatma + menü girdisi
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"

mkdir -p "$BIN_DIR" "$APPS_DIR" "$AUTOSTART_DIR"
chmod +x "$DIR/anime-overlay.py"
ln -sf "$DIR/anime-overlay.py" "$BIN_DIR/anime-overlay"

desktop_entry() {
  cat <<EOF
[Desktop Entry]
Type=Application
Name=Anime Overlay
Comment=Her pencerenin üstünde duran anime GIF/video overlay'i
Exec=$BIN_DIR/anime-overlay
Icon=applications-multimedia
Terminal=false
Categories=Utility;
EOF
}

desktop_entry > "$APPS_DIR/anime-overlay.desktop"

cat > "$APPS_DIR/anime-overlay-settings.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Anime Overlay Ayarları
Comment=Anime overlay ayarlarını aç
Exec=$BIN_DIR/anime-overlay settings
Icon=preferences-system
Terminal=false
Categories=Utility;
EOF

{
  desktop_entry
  echo "X-KDE-autostart-after=panel"
  echo "OnlyShowIn=KDE;"
} > "$AUTOSTART_DIR/anime-overlay.desktop"

echo "Kuruldu: $BIN_DIR/anime-overlay"
echo "Menü girdileri: $APPS_DIR/anime-overlay.desktop, $APPS_DIR/anime-overlay-settings.desktop"
echo "Otomatik başlatma: $AUTOSTART_DIR/anime-overlay.desktop"
echo
echo "Başlatmak için:  $BIN_DIR/anime-overlay  (veya uygulama menüsü → Anime Overlay)"
echo "Ayarlar için:    $BIN_DIR/anime-overlay settings  (veya menü → Anime Overlay Ayarları)"
echo "Kaldırmak için:  rm -f $BIN_DIR/anime-overlay $APPS_DIR/anime-overlay.desktop $APPS_DIR/anime-overlay-settings.desktop $AUTOSTART_DIR/anime-overlay.desktop"
