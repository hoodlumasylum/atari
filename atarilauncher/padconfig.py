"""Controllers that just work in every emulator: before each game CodeAque quietly writes "player 1 = the first SDL pad" into the
emulator's own settings (no button to press, no emulator settings screen). The bindings use SDL's standard controller names
(south button, d-pad up ...), so any pad SDL knows works the same - a PS4 DualShock 4 ("Wireless Controller"), Xbox pads, 8BitDo,
Switch Pro. A binding someone set by hand to another pad (an SDL-1 / other-device value) is never overwritten; keyboard keys and
empty slots are replaced. A copy of each file is kept once (<file>.codeaque.bak).

Covered: RetroArch (SDL2 joypad driver + autoconfig), DuckStation, PCSX2 (DualShock 2 on port 1), Dolphin (GameCube port 1),
xemu (port 1), PPSSPP / Flycast / DOSBox / mGBA / melonDS (already use SDL pads by themselves: nothing to write).
Not written (honest): Cemu, Ryujinx/Eden, Azahar, RPCS3 - their pad files are tied to each device and version; they auto-detect a
pad on their own in most cases. Untested with the real emulators on the user's computer."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from . import inifile

PS_BINDS = {
    "Up": "DPadUp", "Down": "DPadDown", "Left": "DPadLeft", "Right": "DPadRight",
    "Cross": "A", "Circle": "B", "Square": "X", "Triangle": "Y", "Select": "Back", "Start": "Start",
    "L1": "LeftShoulder", "R1": "RightShoulder", "L2": "+LeftTrigger", "R2": "+RightTrigger", "L3": "LeftStick", "R3": "RightStick",
    "LUp": "-LeftY", "LDown": "+LeftY", "LLeft": "-LeftX", "LRight": "+LeftX",
    "RUp": "-RightY", "RDown": "+RightY", "RLeft": "-RightX", "RRight": "+RightX", "Analog": "Guide",
}

DOLPHIN_GC = {
    "Buttons/A": "`Button S`", "Buttons/B": "`Button W`", "Buttons/X": "`Button E`", "Buttons/Y": "`Button N`",
    "Buttons/Z": "`Shoulder R`", "Buttons/Start": "`Start`",
    "Main Stick/Up": "`Left Y-`", "Main Stick/Down": "`Left Y+`", "Main Stick/Left": "`Left X-`", "Main Stick/Right": "`Left X+`",
    "C-Stick/Up": "`Right Y-`", "C-Stick/Down": "`Right Y+`", "C-Stick/Left": "`Right X-`", "C-Stick/Right": "`Right X+`",
    "Triggers/L": "`Trigger L`", "Triggers/R": "`Trigger R`", "Triggers/L-Analog": "`Trigger L`", "Triggers/R-Analog": "`Trigger R`",
    "D-Pad/Up": "`Pad N`", "D-Pad/Down": "`Pad S`", "D-Pad/Left": "`Pad W`", "D-Pad/Right": "`Pad E`",
}

NOTHING_NEEDED = {"ppsspp", "flycast", "dosbox", "mgba", "melonds", "mupen64plus", "rmg", "mednafen", "scummvm", "vice", "fsuae", "mame",
                  "desmume"}
NOT_WRITTEN = {"cemu", "ryujinx", "switchfork", "azahar", "rpcs3"}


def _home(home):
    return Path(home) if home else Path.home()


def paths(emu_id: str, how: str, home=None) -> list[Path]:
    h = _home(home)
    fp = how == "flatpak"
    return {
        "pcsx2": [h / ".var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini" if fp else h / ".config/PCSX2/inis/PCSX2.ini"],
        "duckstation": [h / ".local/share/duckstation/settings.ini"],
        "dolphin": [h / ".var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu/GCPadNew.ini" if fp else h / ".config/dolphin-emu/GCPadNew.ini"],
        "retroarch": [h / ".var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg" if fp else h / ".config/retroarch/retroarch.cfg"],
    }.get(emu_id, [])


def _keep(cur: str | None, ours: str, own_prefix: str) -> bool:
    """True = leave cur alone (it is bound to some other pad on purpose)."""
    if not cur:
        return False
    cur = cur.strip()
    return cur != ours and cur.startswith(("SDL-", "SDL/", "`")) and not cur.startswith(own_prefix)


def _merge(text: str, section: str, want: dict, own_prefix: str, sep=" = ") -> str:
    vals = {k: v for k, v in want.items() if not _keep(inifile.get_value(text, section, k), v, own_prefix)}
    return inifile.set_values(text, section, vals, sep) if vals else text


def pcsx2_text(text: str) -> str:
    text = inifile.set_values(text, "InputSources", {"SDL": "true"})
    text = _merge(text, "Pad1", {"Type": "DualShock2"}, "")
    return _merge(text, "Pad1", {k: "SDL-0/" + v for k, v in PS_BINDS.items()}, "SDL-0/")


def duckstation_text(text: str) -> str:
    text = inifile.set_values(text, "InputSources", {"SDL": "true"})
    text = _merge(text, "ControllerPorts", {}, "")
    text = _merge(text, "Pad1", {"Type": "AnalogController"}, "")
    return _merge(text, "Pad1", {k: "SDL-0/" + v for k, v in PS_BINDS.items()}, "SDL-0/")


def dolphin_text(text: str, pad_name: str) -> str:
    dev = f"SDL/0/{pad_name}"
    cur = inifile.get_value(text, "GCPad1", "Device")
    if cur and cur.startswith("SDL/") and cur != dev and not cur.startswith("SDL/0/"):
        return text                                   # set by hand to another pad
    return inifile.set_values(text, "GCPad1", {"Device": dev, **DOLPHIN_GC})


def retroarch_text(text: str) -> str:
    out, seen = [], set()
    want = {"input_joypad_driver": '"sdl2"', "input_autodetect_enable": '"true"', "input_player1_joypad_index": '"0"'}
    for line in text.splitlines():
        k = line.split("=", 1)[0].strip()
        if k in want:
            out.append(f"{k} = {want[k]}")
            seen.add(k)
        else:
            out.append(line)
    out += [f"{k} = {v}" for k, v in want.items() if k not in seen]
    return "\n".join(out) + "\n"


def _write(path: Path, new: str, old: str | None) -> bool:
    if old is not None and new == old:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if old is not None:
        bak = path.with_name(path.name + ".codeaque.bak")
        if not bak.exists():
            shutil.copyfile(path, bak)
    tmp = path.with_name(path.name + ".codeaque.tmp")
    tmp.write_text(new)
    tmp.replace(path)
    return True


def apply(emu_id: str, how: str = "native", home=None, pad_list: Callable | None = None) -> tuple[list[str], str]:
    """Write player 1's pad into this emulator's settings. -> (files written, short note). Never raises."""
    from . import pads as _pads
    try:
        found = (pad_list or _pads.detect)()
    except Exception:
        found = []
    if not found:
        return [], "no pad connected"
    if emu_id in NOTHING_NEEDED:
        return [], "uses SDL pads by itself"
    if emu_id in NOT_WRITTEN:
        return [], "not written by CodeAque (the emulator picks the pad itself)"
    written: list[str] = []
    try:
        if emu_id == "xemu":
            from . import xemuconfig
            ok, files, _t = xemuconfig.set_pad(found[0].guid, home=Path(home) if home else None)
            return files, "xemu port 1"
        for p in paths(emu_id, how, home):
            old = p.read_text(errors="replace") if p.is_file() else None
            base = old or ""
            new = {"pcsx2": pcsx2_text, "duckstation": duckstation_text, "retroarch": retroarch_text}.get(emu_id)
            new = new(base) if new else dolphin_text(base, found[0].name) if emu_id == "dolphin" else None
            if new is not None and _write(p, new, old):
                written.append(str(p))
    except OSError as exc:
        return written, f"could not write: {exc}"
    return written, f"player 1 = {found[0].name}"


ALL = ("retroarch", "duckstation", "pcsx2", "dolphin", "xemu")


def apply_all(home=None, how_for: Callable[[str], str] = lambda e: "native", pad_list=None) -> dict:
    return {e: apply(e, how_for(e), home, pad_list) for e in ALL}
