#!/usr/bin/env sh
# Starts Code from this folder. Pass --windowed to run in a normal window.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
if [ ! -x "$DIR/.venv/bin/python" ]; then
    echo "Code is not installed yet. Please run:  $DIR/install.sh" >&2
    exit 1
fi
export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$DIR/.venv/bin/python" -m atarilauncher "$@"
