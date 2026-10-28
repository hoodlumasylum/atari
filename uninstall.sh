#!/usr/bin/env bash
# Removes the app, menu entry, 'atari' command and autostart. Your settings and play history are kept.
set -u
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="${ATARI_INSTALL_DIR:-$DATA_HOME/atari-launcher}"
rm -f "$HOME/.local/bin/atari" "$HOME/.local/bin/atari-install-emulators" "$HOME/.local/bin/atari-install-everything" \
      "$DATA_HOME/applications/atari.desktop" \
      "$DATA_HOME/icons/hicolor/scalable/apps/atari-launcher.svg" \
      "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/atari.desktop"
rm -rf "$APP_DIR"
echo "Atari was removed."
echo "Your settings (~/.config/atari), play history and covers (~/.local/share/atari) and games (~/Games/Atari) were kept."
exit 0
