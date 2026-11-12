#!/usr/bin/env bash
# anime-overlay kaldırma: ~/.local/bin bağlantısı, menü girdileri, otomatik başlatma
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"

rm -f "$BIN_DIR/anime-overlay"
rm -f "$APPS_DIR/anime-overlay.desktop" "$APPS_DIR/anime-overlay-settings.desktop"
rm -f "$AUTOSTART_DIR/anime-overlay.desktop"

echo "Kaldırıldı: $BIN_DIR/anime-overlay"
echo "Kaldırıldı: $APPS_DIR/anime-overlay.desktop, $APPS_DIR/anime-overlay-settings.desktop"
echo "Kaldırıldı: $AUTOSTART_DIR/anime-overlay.desktop"
echo
echo "Uygulama hâlâ açıksa kapatmak için:  $BIN_DIR/anime-overlay ctl quit"
echo "Yapılandırma ve önbellek korundu. Tamamen silmek için:"
echo "  rm -rf $HOME/.config/anime-overlay $HOME/.cache/anime-overlay"
