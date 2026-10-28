"""Look of the system tiles: short name, simple original glyph and a colour pair per system.

Everything here is plain data - the glyphs are drawn from basic shapes in QML (see SystemGlyph.qml).
No third-party logos or artwork are used anywhere.
"""
from __future__ import annotations

import colorsys
import hashlib

# id -> (short name, glyph, colour 1 (top), colour 2 (bottom))
SYSTEM_LOOK = {
    "steam": ("Steam", "monitor", "#1c4f7a", "#0b1a30"),
    "apps": ("PC Apps", "monitor", "#2d6a4a", "#0b2016"),
    "streaming": ("Streaming", "monitor", "#7a5a10", "#241a05"),
    "studio": ("Studio", "bars", "#7a5a10", "#12200a"),
    "free": ("Free Games", "pad", "#2d7a3a", "#0b2410"),
    "windows": ("Windows", "monitor", "#1f5fa8", "#0a1a30"),
    "heroic": ("Heroic", "pad", "#1f3f7a", "#0a1530"),
    "lutris": ("Lutris", "pad", "#8a5a1c", "#2a1a08"),
    "atari2600": ("Atari 2600", "bars", "#9b1b22", "#2a0609"),
    "atari7800": ("Atari 7800", "bars", "#a8381c", "#2d0e06"),
    "atarijaguar": ("Atari Jaguar", "bars", "#a02a2a", "#2b0a0a"),
    "atarilynx": ("Atari Lynx", "handheld", "#8a3a1c", "#2a1008"),
    "gamegear": ("Game Gear", "handheld", "#1d4a7a", "#0a1a2e"),
    "atari5200": ("Atari 5200", "bars", "#8c2418", "#2a0a06"),
    "wii": ("Wii", "disc", "#3a5f7a", "#0c1a24"),
    "wiiu": ("Wii U", "pad", "#1d5f86", "#08202e"),
    "n3ds": ("3DS", "handheld", "#8a2a2a", "#2a0c0c"),
    "switch": ("Switch", "handheld", "#a02632", "#2a0a10"),
    "psp": ("PSP", "handheld", "#2a3550", "#0c111c"),
    "saturn": ("Saturn", "disc", "#4a4a5a", "#12121a"),
    "segacd": ("Sega CD", "disc", "#1d3f73", "#0a1630"),
    "neogeo": ("Neo Geo", "cart", "#8a7a1c", "#2a2408"),
    "arcade": ("Arcade", "pad", "#a0402a", "#2b1008"),
    "dos": ("DOS", "monitor", "#4a4f5c", "#13151c"),
    "scummvm": ("ScummVM", "monitor", "#6a3a7a", "#1c0e24"),
    "amiga": ("Amiga", "console", "#3a4a8a", "#10162c"),
    "c64": ("Commodore 64", "console", "#5a4a8a", "#171230"),
    "msx": ("MSX", "console", "#2a6a6a", "#0a2020"),
    "zxspectrum": ("ZX Spectrum", "console", "#7a2a2a", "#240c0c"),
    "amstradcpc": ("Amstrad CPC", "console", "#8a5a1c", "#281a08"),
    "wonderswan": ("WonderSwan", "handheld", "#3a6a8a", "#0e1e28"),
    "ngp": ("Neo Geo Pocket", "handheld", "#6a5a2a", "#201a0a"),
    "vb": ("Virtual Boy", "monitor", "#8a1c1c", "#280808"),
    "3do": ("3DO", "disc", "#5a5a2a", "#1a1a0a"),
    "nes": ("NES", "cart", "#6b2430", "#1b0a10"),
    "snes": ("SNES", "pad", "#5b4d9a", "#1a1438"),
    "genesis": ("Genesis", "console", "#1d3f73", "#0a1630"),
    "mastersystem": ("Master System", "console", "#2a5a86", "#0c1b2c"),
    "gb": ("Game Boy", "handheld", "#4d6b2d", "#142010"),
    "gba": ("Game Boy Advance", "handheld", "#4b3f8f", "#171236"),
    "n64": ("Nintendo 64", "cart", "#2d7a58", "#0b2218"),
    "ps1": ("PlayStation", "disc", "#4a5570", "#12151f"),
    "ps2": ("PlayStation 2", "console", "#1d4f8f", "#08142b"),
    "ps3": ("PlayStation 3", "console", "#23406b", "#080f1e"),
    "xbox": ("Xbox Classic", "disc", "#2f6b2a", "#0a1d0a"),
    "dreamcast": ("Dreamcast", "rings", "#b8561a", "#2f1204"),
    "gamecube": ("GameCube", "cube", "#5a3fb0", "#190f3c"),
    "pce": ("PC Engine", "cart", "#9a5230", "#2a1409"),
    "nds": ("Nintendo DS", "handheld", "#5c6070", "#16181f"),
}
GLYPHS = ["bars", "cart", "pad", "console", "handheld", "disc", "rings", "cube", "monitor"]


def _hsl_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def system_look(sid: str, name: str = "") -> dict:
    """{short, glyph, c1, c2} for a system id (made-up but stable colours for custom systems)."""
    if sid in SYSTEM_LOOK:
        short, glyph, c1, c2 = SYSTEM_LOOK[sid]
        return {"short": short, "glyph": glyph, "c1": c1, "c2": c2}
    digest = hashlib.sha1(sid.encode()).digest()
    hue = digest[0] / 255.0
    return {"short": name or sid, "glyph": GLYPHS[digest[1] % len(GLYPHS)],
            "c1": _hsl_hex(hue, 0.45, 0.32), "c2": _hsl_hex(hue, 0.5, 0.10)}
