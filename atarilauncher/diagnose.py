"""Plain-English checks for "Fix my game", the first-run checklist and the Help page. Nothing here changes anything."""
from __future__ import annotations

import glob
import os
import shutil
from pathlib import Path

from . import apps, bios, emulators, paths, webapps, windows

OK, BAD, NOTE = "ok", "bad", "note"


def controllers(sys_class: str = "/sys/class/input") -> list[str]:
    """Names of game controllers the system can see (joystick devices)."""
    names = []
    for js in sorted(glob.glob(os.path.join(sys_class, "js[0-9]*"))):
        try:
            names.append(Path(js, "device", "name").read_text(errors="replace").strip() or Path(js).name)
        except OSError:
            names.append(Path(js).name)
    return names


def controller_text(sys_class: str = "/sys/class/input") -> str:
    names = controllers(sys_class)
    if not names:
        return ("No game controller found. Plug one in (or turn it on over Bluetooth) and it shows up here - "
                "the keyboard works the whole time.")
    return "Controller found: " + ", ".join(names) + ". It works in Atari's menus, and inside most emulators."


def check_game(cfg, game, sys_class: str = "/sys/class/input") -> list[dict]:
    """Rows {state, title, advice} for one game."""
    rows: list[dict] = []

    def add(state, title, advice=""):
        rows.append({"state": state, "title": title, "advice": advice})

    if game.platform == "steam":
        add(OK if shutil.which("steam") or Path.home().joinpath(".steam").exists() else BAD,
            "Steam", "Steam starts this game. If it does not start, open Steam once and check it is signed in.")
    elif game.platform == windows.PLATFORM:
        exe = Path(game.rom_path)
        add(OK if exe.is_file() else BAD, "Game file (.exe)",
            "" if exe.is_file() else "The .exe is missing: " + game.rom_path + ". Is the drive plugged in, or was the "
            "folder moved? Add the game again with Options > Add Windows game.")
        ok, label = windows.runner_status(cfg)
        add(OK if ok else BAD, "Windows helper" + (": " + label if ok else ""), "" if ok else label)
    elif game.gid.startswith("web:"):
        wa = webapps.BY_ID.get(game.gid.split(":", 1)[-1])
        ok, text = webapps.status(cfg, wa) if wa else (False, "Unknown web app.")
        add(OK if ok else BAD, "Web browser", text if ok or not wa else text)
        if wa and wa.drm:
            add(NOTE, "Widevine DRM", webapps.DRM_NOTE)
        add(NOTE, "Signing in", "Sign in once inside the app - it remembers you. A mouse or touch screen can help in web pages.")
    elif game.platform in apps.NON_GAME or game.launch:
        add(NOTE, "This is a PC app or a store game.", "If nothing opens, install the app: Options > Emulators.")
    else:
        rom = Path(game.rom_path)
        add(OK if rom.is_file() else BAD, "Game file",
            "" if rom.is_file() else "The game file is missing: " + game.rom_path + ". Is the USB stick plugged in? "
            "Options > Rescan library after fixing it.")
        sc = cfg.systems.get(game.platform)
        if sc is not None:
            ready, label, hint = emulators.status_line(cfg, sc)
            add(OK if ready else BAD, "Emulator: " + label,
                "" if ready else hint + "  Easiest: Options > Emulators > Install emulators and apps.")
            state, text = bios.missing_for(sc.id)
            if state == "ok":
                add(OK, "BIOS / firmware", text)
            elif state in ("missing", "recommended"):
                add(BAD if state == "missing" else NOTE, "BIOS / firmware",
                    text + "  Options > Add BIOS files, with the files from your own console.")
            elif state == "note":
                add(NOTE, "Firmware", text)
    names = controllers(sys_class)
    add(OK if names else NOTE, "Controller", (names[0] + " found.") if names else
        "No controller found - you can play with the keyboard (Options > Controls shows the keys).")
    return rows


def summary(rows: list[dict]) -> str:
    bad = [r for r in rows if r["state"] == BAD]
    if not bad:
        return "Everything Atari can check looks fine. If the game still misbehaves, try Options > Copy log and ask for help."
    return "Found " + str(len(bad)) + (" problem" if len(bad) == 1 else " problems") + " - the fix is written under each."


def checklist(cfg, store_has_games: bool, sys_class: str = "/sys/class/input") -> list[dict]:
    """The four getting-started steps with a done/not-done mark."""
    ready = [s for s in cfg.systems.values() if emulators.status_line(cfg, s)[0]]
    need_bios = [s for s in cfg.systems.values() if bios.missing_for(s.id)[0] == "missing"]
    return [
        {"id": "emus", "title": "1. Install emulators",
         "done": bool(ready), "detail": "Programs that run old console games. One press installs them (needs internet)."},
        {"id": "games", "title": "2. Add games from a USB stick",
         "done": store_has_games, "detail": "Plug in the stick with your own game files, then choose it."},
        {"id": "bios", "title": "3. Add BIOS files (only if a console needs them)",
         "done": not need_bios, "detail": "Some consoles (PlayStation, Saturn...) need a BIOS file from your own console."},
        {"id": "covers", "title": "4. Download covers",
         "done": False, "detail": "Pictures for your games (needs internet)."},
    ]
