#!/usr/bin/env bash
# Lists which emulators Atari can use and installs the ones you pick (via Flatpak, per-user,
# no sudo). Run it in a terminal:   atari-install-emulators --list              (show the status)
#                                   atari-install-emulators duckstation pcsx2   (install some)
#                                   atari-install-emulators --all               (install all with a Flatpak)
# Atari never includes BIOS files, firmware, keys or games: you must supply your own.
APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="$APP_DIR/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
export PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m atarilauncher.emulators "$@"
