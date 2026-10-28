#!/usr/bin/env bash
# Old name, kept so existing shortcuts keep working: it is now scripts/install-everything.sh
exec bash "$(dirname "$(readlink -f "$0")")/install-everything.sh" "$@"
