#!/usr/bin/env bash
# Atari installer: private Python environment + app-menu entry. No root needed
# (except optionally for a few system libraries, and it asks first).
#
#   ./install.sh                 normal install
#   ./install.sh --autostart     also start Atari automatically when you log in
#   ./install.sh --yes           don't ask questions (install missing system libraries automatically)
#   ./install.sh --no-gamepad    skip the controller library
set -euo pipefail

APP_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
AUTOSTART=0; ASSUME_YES=0; GAMEPAD=1
for arg in "$@"; do
    case "$arg" in
        --autostart) AUTOSTART=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        --no-gamepad) GAMEPAD=0 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

say()  { printf '\n\033[1;33m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; }
ask()  { [ "$ASSUME_YES" = 1 ] && return 0; read -r -p "$1 [Y/n] " a; case "${a:-y}" in [Yy]*) return 0 ;; *) return 1 ;; esac; }

if [ "$(id -u)" = 0 ]; then
    warn "Please run this as your normal user, not with sudo. (It will ask for your password only if it needs to.)"
    exit 1
fi

# ---------------------------------------------------------------- system libraries
say "Checking system libraries"
if command -v apt-get >/dev/null 2>&1; then
    PKGS="python3 python3-venv python3-pip libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 libfontconfig1 libdbus-1-3 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1"
    MISSING=""
    for p in $PKGS; do dpkg -s "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"; done
    if [ -n "$MISSING" ]; then
        echo "Atari needs these packages:$MISSING"
        if ask "Install them now with sudo apt?"; then
            sudo apt-get update && sudo apt-get install -y $MISSING || warn "Some packages could not be installed; continuing anyway."
        fi
    else
        echo "All needed packages are already installed."
    fi
elif command -v dnf >/dev/null 2>&1; then
    PKGS="python3 python3-pip xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm libxkbcommon-x11 mesa-libEGL mesa-libGL fontconfig dbus-libs"
    MISSING=""
    for p in $PKGS; do rpm -q "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"; done
    if [ -n "$MISSING" ]; then
        echo "Atari needs these packages:$MISSING"
        if ask "Install them now with sudo dnf?"; then
            sudo dnf install -y $MISSING || warn "Some packages could not be installed (on Bazzite/Silverblue-style systems this is normal); continuing."
        fi
    else
        echo "All needed packages are already installed."
    fi
else
    echo "Unknown package manager. If Atari fails to start, install Python 3 with venv/pip, plus the Qt/xcb libraries (see README)."
fi

command -v python3 >/dev/null 2>&1 || { warn "python3 was not found. Install Python 3 and run this again."; exit 1; }
python3 - <<'PY' || { warn "Python 3.9 or newer is required."; exit 1; }
import sys
sys.exit(0 if sys.version_info >= (3, 9) else 1)
PY

# ---------------------------------------------------------------- virtual environment
say "Creating a private Python environment (.venv)"
if ! python3 -m venv "$APP_DIR/.venv"; then
    warn "Could not create the environment. On Ubuntu/Mint run:  sudo apt install python3-venv   then run ./install.sh again."
    exit 1
fi
"$APP_DIR/.venv/bin/python" -m pip install --quiet --upgrade pip

say "Installing Atari's Python libraries (this downloads about 150 MB the first time)"
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
if [ "$GAMEPAD" = 1 ]; then
    say "Installing controller support"
    "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements-gamepad.txt" \
        || warn "Controller support could not be installed. Atari still works with the keyboard."
fi

say "Testing that the app can start"
if ! QT_QPA_PLATFORM=offscreen PYTHONPATH="$APP_DIR" "$APP_DIR/.venv/bin/python" -m atarilauncher --version; then
    warn "The test failed - see the messages above."; exit 1
fi

# ---------------------------------------------------------------- app menu entry
say "Adding Atari to your application menu"
chmod +x "$APP_DIR/run.sh"
BIN_DIR="$HOME/.local/bin"; APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
ln -sf "$APP_DIR/run.sh" "$BIN_DIR/atari"
cp "$APP_DIR/packaging/atari-launcher.svg" "$ICON_DIR/atari-launcher.svg"
sed "s|@RUN@|$APP_DIR/run.sh|g" "$APP_DIR/packaging/atari.desktop.in" > "$APPS_DIR/atari.desktop"
chmod +x "$APPS_DIR/atari.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true

if [ "$AUTOSTART" = 1 ]; then
    mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    cp "$APPS_DIR/atari.desktop" "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/atari.desktop"
    echo "Atari will now start automatically when you log in."
fi

say "Done!"
cat <<EOT
Start Atari from your application menu (look for "Atari" under Games),
or in a terminal with:   $APP_DIR/run.sh
(If you ever move this folder, run ./install.sh again.)
The first start shows a setup screen where you pick your game folders.
To start Atari at login:  ./install.sh --autostart
EOT
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Note: $BIN_DIR is not on your PATH yet; log out/in to use the 'atari' command." ;; esac
