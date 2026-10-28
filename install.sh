#!/usr/bin/env bash
# Atari installer: copies the app to ~/.local/share/atari-launcher, makes a private Python
# environment and adds an app-menu entry. No root needed (except optionally for a few system
# libraries, and it asks first). Safe to run again to upgrade: your settings, favourites and
# play history (~/.config/atari, ~/.local/share/atari) are never touched.
#
#   ./install.sh                 normal install / upgrade
#   ./install.sh --autostart     also start Atari automatically when you log in
#   ./install.sh --yes           don't ask questions (install missing system libraries automatically)
#   ./install.sh --no-gamepad    skip the controller library
#   ./install.sh --no-studio     skip numpy (only needed by the music Studio)
#   ./install.sh --no-system-packages   never use sudo / the package manager (used by Atari's own updater)
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="${ATARI_INSTALL_DIR:-$DATA_HOME/atari-launcher}"
AUTOSTART=0; ASSUME_YES=0; GAMEPAD=1; SYSPKGS=1; STUDIO=1
for arg in "$@"; do
    case "$arg" in
        --autostart) AUTOSTART=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        --no-gamepad) GAMEPAD=0 ;;
        --no-studio) STUDIO=0 ;;
        --no-system-packages) SYSPKGS=0 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

say()  { printf '\n\033[1;33m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; }
ask()  { [ "$ASSUME_YES" = 1 ] && return 0; [ -t 0 ] || return 1; read -r -p "$1 [Y/n] " a; case "${a:-y}" in [Yy]*) return 0 ;; *) return 1 ;; esac; }

if [ "$(id -u)" = 0 ]; then
    warn "Please run this as your normal user, not with sudo. (It will ask for your password only if it needs to.)"
    exit 1
fi

# ---------------------------------------------------------------- system libraries
say "Checking system libraries"
if [ "$SYSPKGS" = 0 ]; then
    echo "Skipping system packages (already set up)."
elif command -v apt-get >/dev/null 2>&1; then
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

# ---------------------------------------------------------------- copy the app
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC_DIR/atarilauncher/__init__.py")"
OLD_VERSION=""
[ -f "$APP_DIR/atarilauncher/__init__.py" ] && OLD_VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$APP_DIR/atarilauncher/__init__.py")"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
    if [ -n "$OLD_VERSION" ]; then say "Upgrading Atari $OLD_VERSION -> ${VERSION:-new} (your settings and favourites are kept)"
    else say "Installing Atari ${VERSION:-} into $APP_DIR"; fi
    mkdir -p "$APP_DIR"
    rm -rf "$APP_DIR/atarilauncher" "$APP_DIR/scripts" "$APP_DIR/packaging"
    for item in atarilauncher scripts packaging run.sh install.sh uninstall.sh requirements.txt requirements-gamepad.txt requirements-studio.txt pyproject.toml README.md LICENSE; do
        [ -e "$SRC_DIR/$item" ] && cp -a "$SRC_DIR/$item" "$APP_DIR/"
    done
    find "$APP_DIR" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
fi
chmod +x "$APP_DIR/run.sh" "$APP_DIR/install.sh" "$APP_DIR/uninstall.sh" "$APP_DIR"/scripts/*.sh 2>/dev/null || true

# ---------------------------------------------------------------- virtual environment
say "Creating a private Python environment"
if [ -x "$APP_DIR/.venv/bin/python" ] && "$APP_DIR/.venv/bin/python" -c "import sys" >/dev/null 2>&1; then
    echo "Re-using the existing environment."
elif ! python3 -m venv --clear "$APP_DIR/.venv"; then
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

if [ "$STUDIO" = 1 ]; then
    say "Installing music Studio support (numpy, about 20 MB)"
    "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements-studio.txt" \
        || warn "Studio support could not be installed. Everything else works; the Studio will say how to add it."
fi

say "Testing that the app can start"
if ! QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software ATARI_NO_GAMEPAD=1 ATARI_NO_COVERS=1 ATARI_NO_UPDATE_CHECK=1 PYTHONPATH="$APP_DIR" \
        "$APP_DIR/.venv/bin/python" -m atarilauncher --demo --windowed --selftest >/dev/null; then
    warn "The start-up test failed - see the messages above. (Missing system libraries are the usual cause; see the README.)"
    exit 1
fi
# the first-start screen must be leavable with Esc (a bug in 0.2.0): start with an empty private config, press Esc, expect config.toml
ST_DIR="$(mktemp -d)"
if QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software ATARI_NO_GAMEPAD=1 ATARI_NO_COVERS=1 ATARI_NO_UPDATE_CHECK=1 PYTHONPATH="$APP_DIR" \
        HOME="$ST_DIR" ATARI_CONFIG_DIR="$ST_DIR/conf" ATARI_DATA_DIR="$ST_DIR/data" \
        "$APP_DIR/.venv/bin/python" -m atarilauncher --windowed --selftest --screenshot-keys "wait:200,back,wait:300" >/dev/null \
        && [ -f "$ST_DIR/conf/config.toml" ]; then
    rm -rf "$ST_DIR"
else
    rm -rf "$ST_DIR"
    warn "The first-start screen test failed - see the messages above."
    exit 1
fi
echo "OK"

# ---------------------------------------------------------------- app menu entry
say "Adding Atari to your application menu"
chmod +x "$APP_DIR/run.sh"
BIN_DIR="$HOME/.local/bin"; APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
ln -sf "$APP_DIR/run.sh" "$BIN_DIR/atari"
ln -sf "$APP_DIR/scripts/install-everything.sh" "$BIN_DIR/atari-install-everything"
ln -sf "$APP_DIR/scripts/install-emulators.sh" "$BIN_DIR/atari-install-emulators"
cp "$APP_DIR/packaging/atari-launcher.svg" "$ICON_DIR/atari-launcher.svg"
sed "s|@RUN@|$APP_DIR/run.sh|g" "$APP_DIR/packaging/atari.desktop.in" > "$APPS_DIR/atari.desktop"
chmod +x "$APPS_DIR/atari.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true

if [ "$AUTOSTART" = 1 ]; then
    mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    cp "$APPS_DIR/atari.desktop" "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/atari.desktop"
    echo "Atari will now start automatically when you log in."
fi

say "Done!"
cat <<EOT
Atari ${VERSION:-} is installed. Start it from your application menu (look for "Atari" under Games),
or in a terminal with:   atari      (or add --windowed to run in a window)
You can now delete the folder you extracted - the app lives in $APP_DIR.
The first start shows a setup screen; "Add Games" copies games from a USB stick.
Need emulators or apps (PlayStation, Nintendo, Xbox, Roblox, ...)?  Open Settings > Emulators > Install emulators and apps,
or run in a terminal:   atari-install-everything
To start Atari at login:  ./install.sh --autostart
EOT
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Note: $BIN_DIR is not on your PATH yet; log out/in to use the 'atari' command." ;; esac
