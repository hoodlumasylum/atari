"""Keyboard controls per emulator: a cheat sheet for the "Controls" screen, the short hint shown when a game
starts, and sane default keyboard bindings for emulators that need a file for them.

Rule: CodeAque only ever writes a binding file when the emulator has none yet. A file that already exists (the
emulator made it, or you changed keys in the emulator) is never touched.
"""
from __future__ import annotations

from pathlib import Path

from .emulators import SYSTEM_BY_ID

# --------------------------------------------------------------------------- Flycast (verified against the Flycast source:
# core/input/mapping.cpp + keyboard_device.h + gamepad_device.cpp). Values are SDL scancodes.
FLYCAST_KEYBOARD_NAME = "SDL_Keyboard.cfg"          # <api name>_<device name>.cfg  (no "-<id>" = any keyboard)
FLYCAST_KEYBOARD_INSTANCE = "SDL_Keyboard-sdl_keyboard.cfg"
SC = {"A": 4, "C": 6, "D": 7, "E": 8, "Q": 20, "S": 22, "V": 25, "W": 26, "X": 27, "Z": 29, "RETURN": 40,
      "TAB": 43, "SPACE": 44, "F12": 69, "RIGHT": 79, "LEFT": 80, "DOWN": 81, "UP": 82, "KP_ENTER": 88}
FLYCAST_BINDINGS = [  # (Flycast name, key)
    ("btn_dpad1_up", "UP"), ("btn_dpad1_down", "DOWN"), ("btn_dpad1_left", "LEFT"), ("btn_dpad1_right", "RIGHT"),
    ("btn_a", "Z"), ("btn_b", "X"), ("btn_x", "C"), ("btn_y", "V"),
    ("btn_start", "RETURN"),
    ("btn_analog_up", "W"), ("btn_analog_down", "S"), ("btn_analog_left", "A"), ("btn_analog_right", "D"),
    ("btn_trigger_left", "Q"), ("btn_trigger_right", "E"),
    ("btn_menu", "TAB"), ("btn_fforward", "SPACE"), ("btn_screenshot", "F12"),
]


def flycast_mapping_text() -> str:
    """The same file format Flycast writes itself (version 4), so Flycast reads it as its own."""
    lines = ["[digital]"]
    for i, (name, key) in enumerate(FLYCAST_BINDINGS):
        lines.append(f"bind{i} = {SC[key]}:{name}")
    lines += ["", "[emulator]", "dead_zone = 10", "mapping_name = Keyboard", "rumble_power = 100",
              "saturation = 100", "triggers = ", "version = 4", ""]
    return "\n".join(lines)


def flycast_mappings_dir(how: str, home: Path | None = None) -> Path:
    home = home or Path.home()
    if how == "flatpak":
        return home / ".var/app/org.flycast.Flycast/config/flycast/mappings"
    return home / ".config/flycast/mappings"


def ensure_flycast_keyboard(how: str = "native", home: Path | None = None) -> Path | None:
    """Write Flycast's keyboard mapping unless Flycast already has one. Returns the path written, else None."""
    d = flycast_mappings_dir(how, home)
    try:
        if d.is_dir() and any(d.glob("SDL_Keyboard*.cfg")):
            return None
        d.mkdir(parents=True, exist_ok=True)
        target = d / FLYCAST_KEYBOARD_NAME
        if target.exists():
            return None
        tmp = target.with_name(target.name + ".part")
        tmp.write_text(flycast_mapping_text(), encoding="utf-8")
        tmp.replace(target)
        return target
    except OSError:
        return None


def ensure_keyboard_defaults(emu_id: str, how: str = "native", home: Path | None = None) -> list[str]:
    """Called just before an emulator is started. Returns the files it created (usually none)."""
    if emu_id == "flycast" and how in ("native", "flatpak"):
        p = ensure_flycast_keyboard(how, home)
        return [str(p)] if p else []
    return []


# --------------------------------------------------------------------------- cheat sheet
# Defaults of each emulator for a keyboard. "source" says where each came from.
ARROWS = "Arrow keys"
SHEETS: dict[str, dict] = {
    "flycast": {
        "name": "Flycast", "systems": ("dreamcast",),
        "keys": [("Move / D-pad", ARROWS), ("A  /  B  /  X  /  Y", "Z  /  X  /  C  /  V"), ("Start", "Enter"),
                 ("Analog stick", "W A S D"), ("Triggers L / R", "Q  /  E"), ("Flycast menu (and Exit)", "Tab"),
                 ("Fast-forward", "Space")],
        "note": "CodeAque sets these up the first time Flycast starts, unless you already have your own keys."},
    "retroarch": {
        "name": "RetroArch", "systems": (),
        "keys": [("Move / D-pad", ARROWS), ("A  /  B", "X  /  Z"), ("X  /  Y", "S  /  A"), ("L  /  R", "Q  /  W"),
                 ("Start  /  Select", "Enter  /  Right Shift"), ("RetroArch menu", "F1"), ("Quit game", "Esc"),
                 ("Save / Load state", "F2  /  F4")],
        "note": "RetroArch's built-in keyboard defaults (nothing to set up)."},
    "duckstation": {
        "name": "DuckStation", "systems": ("ps1",),
        "keys": [("D-pad", ARROWS), ("Triangle / Square / Circle / Cross", "I  /  J  /  L  /  K"),
                 ("L1 / R1", "Q  /  E"), ("L2 / R2", "1  /  3"), ("Left stick", "W A S D"),
                 ("Start  /  Select", "Enter  /  Backspace"), ("Pause menu", "Esc")],
        "note": "From DuckStation's README (default bindings)."},
    "pcsx2": {
        "name": "PCSX2", "systems": ("ps2",),
        "keys": [("D-pad", ARROWS), ("Triangle / Square / Circle / Cross", "I  /  J  /  L  /  K"),
                 ("L1 / R1", "Q  /  E"), ("L2 / R2", "1  /  3"), ("Left stick", "W A S D"),
                 ("Start  /  Select", "Enter  /  Backspace")],
        "note": "PCSX2's usual defaults; change them in PCSX2: Settings > Controllers."},
    "ppsspp": {
        "name": "PPSSPP", "systems": ("psp",),
        "keys": [("D-pad", ARROWS), ("Cross / Circle", "Z  /  X"), ("Square / Triangle", "A  /  S"),
                 ("L / R", "Q  /  W"), ("Start  /  Select", "Space  /  Enter"), ("Analog stick", "I J K L"),
                 ("Pause menu", "Esc")],
        "note": "From PPSSPP's default key map (QWERTY keyboards)."},
    "dolphin": {
        "name": "Dolphin", "systems": ("gamecube", "wii"),
        "keys": [("A  /  B  /  X  /  Y", "X  /  Z  /  C  /  S"), ("Z", "D"), ("Start", "Enter"),
                 ("Control stick", ARROWS), ("C-stick", "I J K L"), ("L / R", "Q  /  W"), ("D-pad", "T F G H")],
        "note": "Dolphin's usual GameCube defaults. Wii games may need setup: Dolphin > Controllers."},
    "mgba": {
        "name": "mGBA", "systems": ("gba", "gb"),
        "keys": [("D-pad", ARROWS), ("A  /  B", "X  /  Z"), ("L  /  R", "A  /  S"),
                 ("Start  /  Select", "Enter  /  Backspace")],
        "note": "From the mGBA README (default keyboard controls)."},
    "melonds": {
        "name": "melonDS", "systems": ("nds",),
        "keys": [("Keys", "Set once in melonDS: Config > Input and hotkeys")],
        "note": "melonDS needs its keys set once; CodeAque cannot do it for you yet."},
}


def sheet_for_emulator(emu_id: str) -> dict | None:
    return SHEETS.get(emu_id)


def hint_for(emu_id: str, system_id: str = "") -> str:
    """Short one-line summary shown when a game starts."""
    s = SHEETS.get(emu_id)
    if not s:
        return ""
    keys = s["keys"]
    parts = [f"{a}: {b}" for a, b in keys[:4]]
    return f"{s['name']} keys - " + "   |   ".join(parts)


def cheat_rows() -> list[dict]:
    """Rows for the Controls screen (MenuList format)."""
    rows = [
        {"kind": "info", "title": "Keys in CodeAque itself: Arrow keys move, Enter plays, Esc goes back, F = favourite, "
                                  "Tab = next console, Q / E = previous / next tab, / = search, F10 = options.",
         "value": "", "detail": ""},
        {"kind": "info", "title": "Back from Netflix, YouTube, Kodi...: press Esc twice quickly, or hold Esc for 1 second (Ctrl+Esc also works). "
                                  "On a controller hold Guide / Home and press B. One Esc still leaves video full screen as normal.",
         "value": "", "detail": ""},
        {"kind": "info", "title": "Inside a game the emulator's own keys apply (below). CodeAque steps aside (its window "
                                  "is minimised) while a game runs, and comes back when you quit the game.",
         "value": "", "detail": ""},
    ]
    for eid, s in SHEETS.items():
        sys_names = ", ".join(SYSTEM_BY_ID[x].name for x in s["systems"] if x in SYSTEM_BY_ID)
        title = s["name"] + (f"  -  {sys_names}" if sys_names else "  -  most retro consoles")
        detail = "     ".join(f"{a}: {b}" for a, b in s["keys"])
        rows.append({"kind": "ctl", "title": title, "value": "", "detail": detail + ("     (" + s["note"] + ")" if s["note"] else "")})
    rows.append({"kind": "back", "title": "Back", "value": "", "detail": ""})
    return rows
