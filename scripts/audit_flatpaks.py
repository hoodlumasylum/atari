#!/usr/bin/env python3
"""Check every Flatpak id Atari uses against Flathub: does it exist, is it end-of-life, is its runtime end-of-life?
Usage:  python3 scripts/audit_flatpaks.py          (needs internet; read-only; exit code 1 when something is wrong)"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atarilauncher import apps, appinstall, freegames  # noqa: E402

API = "https://flathub.org/api/v2"
UA = {"User-Agent": "AtariLauncher-audit/0.3.2 (+https://github.com/hoodlumasylum/atari)"}


def get(path: str):
    try:
        with urllib.request.urlopen(urllib.request.Request(API + path, headers=UA), timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"_error": str(exc)}


def main() -> int:
    ids = {t.flatpak for t in (appinstall.target_for(i) for i in appinstall.all_ids()) if t and t.flatpak}
    ids |= {g.ref for g in freegames.GAMES if g.kind == "flatpak"} | {a.flatpak for a in apps.APP_DEFS if a.flatpak}
    bad = 0
    for fid in sorted(ids):
        meta = get(f"/appstream/{fid}")
        if "_error" in meta:
            print(f"MISSING  {fid}  ({meta['_error']})")
            bad += 1
            continue
        eol = bool(meta.get("is_eol")) or bool(meta.get("eol"))
        summ = get(f"/summary/{fid}")
        runtime = ""
        if isinstance(summ, dict):
            runtime = str((summ.get("metadata") or {}).get("runtime", ""))
        flag = "EOL" if eol else "ok"
        print(f"{flag:8} {fid}   runtime={runtime or '?'}")
        bad += eol
    print("\nAll good." if not bad else f"\n{bad} problem(s): replace or flag them in atarilauncher/emulators.py / apps.py.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
