"""Settings > Picture shape, written into each emulator's own settings before every game (like the pad set-up):
  fill     - stretch the picture to the whole screen, full height, no side bars (default)
  wide     - the emulator's widescreen hack where it has one (real 16:9 picture; can show glitches in some games), else fill
  original - the game's own shape (4:3 for most PS1 / PS2 / GameCube games: bars at the sides)
Only these keys are touched; a copy of each file is kept once (*.codeaque.bak). Untested with every emulator version."""
from __future__ import annotations

from pathlib import Path

from . import inifile
from .padconfig import _write, retroarch_text  # noqa: F401

SHAPES = ("fill", "wide", "original")
NAMES = {"fill": "Fill screen", "wide": "Widescreen hack (where available)", "original": "Original"}


def _h(home):
    return Path(home) if home else Path.home()


def files(emu_id: str, how: str, home=None) -> list[Path]:
    h, fp = _h(home), how == "flatpak"
    return {
        "pcsx2": [h / ".var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini" if fp else h / ".config/PCSX2/inis/PCSX2.ini"],
        "duckstation": [h / ".local/share/duckstation/settings.ini"],
        "dolphin": [h / ".var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu/GFX.ini" if fp else h / ".config/dolphin-emu/GFX.ini"],
        "ppsspp": [h / ".var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM/ppsspp.ini" if fp else h / ".config/ppsspp/PSP/SYSTEM/ppsspp.ini"],
        "retroarch": [h / ".var/app/org.libretro.RetroArch/config/retroarch/retroarch.cfg" if fp else h / ".config/retroarch/retroarch.cfg"],
    }.get(emu_id, [])


def ini_changes(emu_id: str, shape: str) -> list[tuple[str, dict]]:
    fill, wide = shape == "fill", shape == "wide"
    if emu_id == "pcsx2":
        return [("EmuCore/GS", {"AspectRatio": "Stretch" if fill else "16:9" if wide else "Auto 4:3/3:2"}),
                ("EmuCore", {"EnableWideScreenPatches": "true" if wide else "false"})]
    if emu_id == "duckstation":
        return [("Display", {"AspectRatio": "Stretch To Fill" if fill else "16:9" if wide else "Auto (Game Native)",
                             "IntegerScaling": "false"}),
                ("GPU", {"WidescreenHack": "true" if wide else "false"})]
    if emu_id == "dolphin":
        return [("Settings", {"AspectRatio": "3" if fill else "1" if wide else "0", "wideScreenHack": "True" if wide else "False"})]
    if emu_id == "ppsspp":
        return [("Graphics", {"DisplayStretch": "True" if shape != "original" else "False"})]
    return []


def retroarch_shape(text: str, shape: str) -> str:
    want = {"video_scale_integer": '"false"', "video_aspect_ratio_auto": '"false"' if shape != "original" else '"true"'}
    if shape != "original":
        want["aspect_ratio_index"] = '"24"'      # "Full" (stretch to the window) in RetroArch 1.10+
    out, seen = [], set()
    for line in text.splitlines():
        k = line.split("=", 1)[0].strip()
        if k in want:
            out.append(f"{k} = {want[k]}")
            seen.add(k)
        else:
            out.append(line)
    out += [f"{k} = {v}" for k, v in want.items() if k not in seen]
    return "\n".join(out) + "\n"


def apply(emu_id: str, shape: str, how: str = "native", home=None) -> list[str]:
    if shape not in SHAPES:
        shape = "fill"
    written: list[str] = []
    try:
        if emu_id == "xemu":
            from . import xemuconfig
            fit = {"fill": "stretch", "wide": "scale_16_9", "original": "scale"}[shape]
            for toml in xemuconfig.config_files(Path(home) if home else None):
                old = toml.read_text() if toml.is_file() else None
                new = xemuconfig.set_section_values(old or "", "display.ui", {"fit": fit})
                if _write(toml, new, old):
                    written.append(str(toml))
            return written
        for p in files(emu_id, how, home):
            old = p.read_text(errors="replace") if p.is_file() else None
            if emu_id == "retroarch":
                new = retroarch_shape(old or "", shape)
            else:
                new = old or ""
                for sec, vals in ini_changes(emu_id, shape):
                    new = inifile.set_values(new, sec, vals)
            if _write(p, new, old):
                written.append(str(p))
    except OSError:
        pass
    return written
