#!/usr/bin/env bash
# Removes the menu entry, the 'atari' command and autostart. Your settings and play history are kept.
set -u
APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
rm -f "$HOME/.local/bin/atari" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/applications/atari.desktop" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/atari-launcher.svg" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/atari.desktop"
rm -rf "$APP_DIR/.venv"
echo "Atari's menu entry and private environment were removed."
echo "Your settings (~/.config/atari) and play history (~/.local/share/atari) were kept."
echo "To remove the app completely, delete this folder: $APP_DIR"
