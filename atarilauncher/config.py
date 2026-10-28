"""Configuration: ~/.config/atari/config.toml (created on first run)."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Ubuntu 22.04 / Mint 21 ship Python 3.10
    import tomli as tomllib  # type: ignore

from . import paths

# Default launch template. {retroarch} expands to the RetroArch command,
# {core_path} to the full path of the core file. Any other emulator works too,
# e.g.  command = "mgba-qt -f {rom}"
RETROARCH_TEMPLATE = "{retroarch} -f -L {core_path} {rom}"

# id, display name, file extensions, RetroArch core, search aliases for folder guessing
DEFAULT_SYSTEMS = [
    ("nes", "Nintendo NES", ["nes", "fds", "unf", "unif", "zip", "7z"], "fceumm_libretro", ["famicom"]),
    ("snes", "Super Nintendo", ["sfc", "smc", "swc", "fig", "zip", "7z"], "snes9x_libretro", ["superfamicom", "sfc"]),
    ("genesis", "Sega Genesis", ["md", "gen", "smd", "zip", "7z"], "genesis_plus_gx_libretro", ["megadrive", "md"]),
    ("mastersystem", "Sega Master System", ["sms", "zip", "7z"], "genesis_plus_gx_libretro", ["sms"]),
    ("atari2600", "Atari 2600", ["a26", "bin", "zip", "7z"], "stella_libretro", ["2600", "atari-2600"]),
    ("atari7800", "Atari 7800", ["a78", "zip", "7z"], "prosystem_libretro", ["7800", "atari-7800"]),
    ("gb", "Game Boy / Color", ["gb", "gbc", "zip", "7z"], "gambatte_libretro", ["gbc", "gameboy"]),
    ("gba", "Game Boy Advance", ["gba", "zip", "7z"], "mgba_libretro", []),
    ("n64", "Nintendo 64", ["n64", "z64", "v64", "zip", "7z"], "mupen64plus_next_libretro", []),
    ("ps1", "PlayStation", ["cue", "chd", "pbp", "iso", "m3u"], "pcsx_rearmed_libretro", ["psx", "playstation"]),
    ("pce", "PC Engine", ["pce", "zip", "7z"], "mednafen_pce_fast_libretro", ["turbografx", "tg16"]),
    ("nds", "Nintendo DS", ["nds", "zip", "7z"], "melonds_libretro", ["ds"]),
]


@dataclass
class SystemConfig:
    id: str
    name: str
    extensions: list[str]
    core: str = ""
    command: str = RETROARCH_TEMPLATE
    roms: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)


@dataclass
class Config:
    fullscreen: bool = True
    steam_enabled: bool = True
    steam_root: str = ""  # empty = auto-detect
    steam_extra_libraries: list[str] = field(default_factory=list)
    steam_command: str = ""  # empty = auto ("steam" or Flatpak)
    retroarch_command: str = ""  # empty = auto ("retroarch" or Flatpak)
    cores_dir: str = ""  # empty = auto
    systems: dict[str, SystemConfig] = field(default_factory=dict)
    first_run: bool = False
    path: Path | None = None


def default_config() -> Config:
    cfg = Config()
    for sid, name, exts, core, aliases in DEFAULT_SYSTEMS:
        cfg.systems[sid] = SystemConfig(sid, name, list(exts), core, RETROARCH_TEMPLATE, [], list(aliases))
    return cfg


def _as_list(v) -> list[str]:
    if isinstance(v, str):
        return [v] if v else []
    return [str(x) for x in v] if isinstance(v, list) else []


def load_config(path: Path | None = None) -> Config:
    """Load config; a missing/broken file yields defaults (first_run=True if missing)."""
    path = path or paths.config_file()
    cfg = default_config()
    cfg.path = path
    if not path.is_file():
        cfg.first_run = True
        return cfg
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"[atari] could not read {path}: {exc} - using defaults")
        return cfg
    g = data.get("general", {})
    cfg.fullscreen = bool(g.get("fullscreen", cfg.fullscreen))
    s = data.get("steam", {})
    cfg.steam_enabled = bool(s.get("enabled", True))
    cfg.steam_root = str(s.get("root", ""))
    cfg.steam_extra_libraries = _as_list(s.get("extra_libraries", []))
    cfg.steam_command = str(s.get("command", ""))
    r = data.get("retroarch", {})
    cfg.retroarch_command = str(r.get("command", ""))
    cfg.cores_dir = str(r.get("cores_dir", ""))
    for sid, sd in (data.get("systems", {}) or {}).items():
        if not isinstance(sd, dict):
            continue
        sc = cfg.systems.get(sid) or SystemConfig(sid, sd.get("name", sid), [], "", RETROARCH_TEMPLATE)
        sc.name = str(sd.get("name", sc.name))
        if "extensions" in sd:
            sc.extensions = [e.lstrip(".").lower() for e in _as_list(sd["extensions"])]
        sc.core = str(sd.get("core", sc.core))
        sc.command = str(sd.get("command", sc.command))
        sc.roms = _as_list(sd.get("roms", sc.roms))
        cfg.systems[sid] = sc
    return cfg


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _ql(items) -> str:
    return "[" + ", ".join(_q(i) for i in items) + "]"


def dump_config(cfg: Config) -> str:
    out = [
        "# Atari launcher settings. Safe to edit by hand; restart Atari afterwards.",
        "# Lines starting with # are comments.",
        "",
        "[general]",
        "fullscreen = " + ("true" if cfg.fullscreen else "false"),
        "",
        "[steam]",
        "enabled = " + ("true" if cfg.steam_enabled else "false"),
        '# root = ""  means "find Steam automatically" (~/.steam, ~/.local/share/Steam, Flatpak).',
        "root = " + _q(cfg.steam_root),
        "# Extra Steam library folders (normally found automatically from Steam itself).",
        "extra_libraries = " + _ql(cfg.steam_extra_libraries),
        '# command = ""  means: use `steam`, or the Flatpak version if that is what you have.',
        "command = " + _q(cfg.steam_command),
        "",
        "[retroarch]",
        '# Leave empty to auto-detect. Example: command = "flatpak run org.libretro.RetroArch"',
        "command = " + _q(cfg.retroarch_command),
        "cores_dir = " + _q(cfg.cores_dir),
        "",
        "# One section per console. `roms` is a list of folders to scan.",
        "# `command` is the launch command: {rom} = the game file, {retroarch} = RetroArch,",
        "# {core_path} = full path of the core. Any emulator works, e.g.",
        '#   command = "mgba-qt -f {rom}"',
    ]
    for sc in cfg.systems.values():
        out += [
            "",
            f"[systems.{sc.id if re.fullmatch(r'[A-Za-z0-9_-]+', sc.id) else _q(sc.id)}]",
            "name = " + _q(sc.name),
            "roms = " + _ql(sc.roms),
            "extensions = " + _ql(sc.extensions),
            "core = " + _q(sc.core),
            "command = " + _q(sc.command),
        ]
    return "\n".join(out) + "\n"


def save_config(cfg: Config, path: Path | None = None) -> Path:
    path = path or cfg.path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dump_config(cfg), encoding="utf-8")
    tmp.replace(path)
    cfg.path = path
    cfg.first_run = False
    return path


def clone(cfg: Config) -> Config:
    return copy.deepcopy(cfg)
