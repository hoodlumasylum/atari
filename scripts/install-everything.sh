#!/usr/bin/env bash
# Installs everything CodeAque can use - emulators, RetroArch cores and PC apps (Roblox/Sober, Heroic, Lutris, ...) - in plain English, and carries on if one of them fails.
#   atari-install-everything              install everything that is missing (safe to run again)
#   atari-install-everything --list       show what is installed
#   atari-install-everything duckstation pcsx2     install only these
#   atari-install-everything --help       all options
#   atari-install-everything --essentials   only RetroArch+cores, PCSX2, Dolphin, PPSSPP, melonDS, mGBA, Flycast
# DuckStation (its Flatpak is end-of-life) comes as the official AppImage, SHA-256 checked; ffmpeg is installed for the screen recorder.
# (Roblox runs through Sober: unofficial, may break after Roblox updates, and you sign in yourself.)
# It uses Flatpak in your own account (no sudo). Only installing Flatpak itself, or the two apt-only
# emulators (mednafen, mupen64plus), asks for your password - and asks you first.
# CodeAque never includes BIOS files, firmware, keys or games: you must supply your own ("Add BIOS files").
APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="$APP_DIR/.venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
if [ -z "$PY" ]; then echo "python3 was not found - install Python 3 first."; exit 1; fi
export PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m atarilauncher.installer "$@"
