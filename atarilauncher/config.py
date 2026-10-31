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
from .emulators import SYSTEM_BY_ID, SYSTEMS

# Old (0.1.0) default launch template. Today an empty `command` means "use the emulator table" (see
# emulators.py); a command written in the config file always wins (a "custom" command).
# Words usable in a command: {rom} {rom_dir} {rom_name} {core_path} and {retroarch} / {<emulator id>}.
RETROARCH_TEMPLATE = "{retroarch} -f -L {core_path} {rom}"


@dataclass
class SystemConfig:
    id: str
    name: str
    extensions: list[str]
    core: str = ""
    command: str = ""  # empty = automatic (emulators.py); anything else = your own launch command
    roms: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    emulator: str = ""  # empty = automatic; or the id of an emulator from the table (Settings > Emulators)


@dataclass
class Config:
    fullscreen: bool = True
    steam_enabled: bool = True
    steam_root: str = ""  # empty = auto-detect
    steam_extra_libraries: list[str] = field(default_factory=list)
    steam_command: str = ""  # empty = auto ("steam" or Flatpak)
    steam_proton_default: bool = True  # CodeAque-only mode: Steam Play (proton-experimental) for all games unless a tool was already chosen
    retroarch_command: str = ""  # empty = auto ("retroarch" or Flatpak)
    cores_dir: str = ""  # empty = auto
    emulator_commands: dict[str, str] = field(default_factory=dict)  # e.g. {"rpcs3": "flatpak run net.rpcs3.RPCS3"}
    systems: dict[str, SystemConfig] = field(default_factory=dict)
    update_check: bool = True  # look for a newer CodeAque release at most once a day (Settings)
    covers_auto: bool = True  # download missing cover art in the background after a scan (Settings)
    sound_effects: bool = True  # little UI sounds (Settings > Sound effects)
    music: bool = False         # soft ambient loop (Settings > Music), off unless asked for
    volume: float = 0.6         # 0.0 - 1.0 for sounds and music
    rec_audio: str = "desktop"     # none | desktop | mic | both
    rec_quality: str = "medium"    # low | medium | high
    rec_fps: int = 30              # 30 | 60
    rec_dir: str = ""              # "" = ~/Videos/Atari Recordings
    rec_encoder: str = "x264"      # x264 | vaapi (hardware, needs a working VAAPI driver)
    steamgriddb_key: str = ""      # optional free SteamGridDB API key for extra covers (Settings)
    cover_wikipedia: bool = True   # Wikipedia's article picture as a last-resort cover source
    fullscreen_games: bool = True  # emulators open full screen (each one's own flag)
    esc_exit: bool = True          # Esc twice / hold Esc / Ctrl+Esc / Guide+B quits a web app or Kodi and returns to CodeAque
    intro_enabled: bool = True     # play the intro video you chose (~/.local/share/atari/intro.mp4 ...) when CodeAque starts
    intro_default: bool = True     # with no video of your own: CodeAque's own short start-up animation
    intro_sound: bool = True       # the intro plays WITH its sound (independent of "sound effects")
    steam_bigpicture: bool = True  # the Steam tile opens Steam full screen in Big Picture (controller-friendly) mode
    reduce_animations: bool = False  # Settings > Reduce animations: no moving background, bobbing or fades
    first_run: bool = False
    path: Path | None = None


def default_config() -> Config:
    cfg = Config()
    for sd in SYSTEMS:
        cfg.systems[sd.id] = SystemConfig(sd.id, sd.name, list(sd.extensions), sd.core, "", [], list(sd.aliases))
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
    cfg.steam_proton_default = bool(s.get("proton_default", True))
    cv = data.get("covers", {})
    if isinstance(cv, dict):
        cfg.covers_auto = bool(cv.get("auto", True))
        cfg.steamgriddb_key = str(cv.get("steamgriddb_key", "")).strip()
        cfg.cover_wikipedia = bool(cv.get("wikipedia", True))
    up = data.get("updates", {})
    if isinstance(up, dict):
        cfg.update_check = bool(up.get("check", True))
    ui = data.get("ui", {})
    if isinstance(ui, dict):
        cfg.sound_effects = bool(ui.get("sound_effects", True))
        cfg.music = bool(ui.get("music", False))
        try:
            cfg.volume = max(0.0, min(1.0, float(ui.get("volume", 0.6))))
        except (TypeError, ValueError):
            cfg.volume = 0.6
        cfg.reduce_animations = bool(ui.get("reduce_animations", False))
        cfg.esc_exit = bool(ui.get("esc_exit", True))
        cfg.fullscreen_games = bool(ui.get("fullscreen_games", True))
        cfg.steam_bigpicture = bool(ui.get("steam_bigpicture", True))
        cfg.intro_enabled = bool(ui.get("intro_enabled", True))
        cfg.intro_default = bool(ui.get("intro_default", True))
        cfg.intro_sound = bool(ui.get("intro_sound", True))
    rc = data.get("recording", {})
    if isinstance(rc, dict):
        cfg.rec_audio = rc.get("audio", "desktop") if rc.get("audio") in ("none", "desktop", "mic", "both") else "desktop"
        cfg.rec_quality = rc.get("quality", "medium") if rc.get("quality") in ("low", "medium", "high") else "medium"
        cfg.rec_fps = 60 if rc.get("fps") == 60 else 30
        cfg.rec_dir = str(rc.get("folder", ""))
        cfg.rec_encoder = "vaapi" if rc.get("encoder") == "vaapi" else "x264"
    r = data.get("retroarch", {})
    cfg.retroarch_command = str(r.get("command", ""))
    cfg.cores_dir = str(r.get("cores_dir", ""))
    em = data.get("emulators", {})
    if isinstance(em, dict):
        cfg.emulator_commands = {str(k): str(v) for k, v in em.items() if isinstance(v, str) and v.strip()}
    for sid, sd in (data.get("systems", {}) or {}).items():
        if not isinstance(sd, dict):
            continue
        sc = cfg.systems.get(sid) or SystemConfig(sid, sd.get("name", sid), [], "", RETROARCH_TEMPLATE)
        sc.name = str(sd.get("name", sc.name))
        if "extensions" in sd:
            sc.extensions = [e.lstrip(".").lower() for e in _as_list(sd["extensions"])]
        sc.core = str(sd.get("core", sc.core))
        sc.command = str(sd.get("command", sc.command))
        if sid in SYSTEM_BY_ID and sc.command.strip() in ("", RETROARCH_TEMPLATE):
            sc.command = ""  # 0.1.0 wrote the default command into the file: that just means "automatic"
        sc.emulator = str(sd.get("emulator", sc.emulator))
        sc.roms = _as_list(sd.get("roms", sc.roms))
        cfg.systems[sid] = sc
    return cfg


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _ql(items) -> str:
    return "[" + ", ".join(_q(i) for i in items) + "]"


def dump_config(cfg: Config) -> str:
    out = [
        "# CodeAque launcher settings. Safe to edit by hand; restart CodeAque afterwards.",
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
        "# CodeAque-only mode: turn on Steam Play (Proton) for all games by default, only if you have not chosen a tool yourself.",
        "proton_default = " + ("true" if cfg.steam_proton_default else "false"),
        "",
        "[covers]",
        "# Download missing box art from the internet in the background after a scan (Settings > Covers).",
        "auto = " + ("true" if cfg.covers_auto else "false"),
        "# Optional: a free SteamGridDB API key (steamgriddb.com > Preferences > API) adds more cover sources. Leave empty to skip.",
        "steamgriddb_key = " + _q(cfg.steamgriddb_key),
        "# Wikipedia's article picture as a last-resort cover (only the page image, no other data).",
        "wikipedia = " + ("true" if cfg.cover_wikipedia else "false"),
        "",
        "[recording]",
        "# Screen recorder (F9, or Guide + X on a controller). audio = none | desktop | mic | both; quality = low | medium | high.",
        "audio = " + _q(cfg.rec_audio),
        "quality = " + _q(cfg.rec_quality),
        "fps = " + str(cfg.rec_fps),
        '# folder = ""  means ~/Videos/Atari Recordings',
        "folder = " + _q(cfg.rec_dir),
        '# encoder = "x264" (works everywhere) or "vaapi" (hardware, if your graphics driver supports it)',
        "encoder = " + _q(cfg.rec_encoder),
        "",
        "[updates]",
        "# Look for a newer CodeAque release (once a day, quietly) and show a badge (Settings > Updates).",
        "check = " + ("true" if cfg.update_check else "false"),
        "",
        "[ui]",
        "# Sounds and animations (Settings). Volume is 0.0 - 1.0. Turn animations off on a slow computer.",
        "sound_effects = " + ("true" if cfg.sound_effects else "false"),
        "music = " + ("true" if cfg.music else "false"),
        "volume = " + f"{cfg.volume:.2f}",
        "reduce_animations = " + ("true" if cfg.reduce_animations else "false"),
        "# Esc twice (or hold Esc 1 s, Ctrl+Esc, gamepad Guide+B) closes Netflix / YouTube / Kodi and returns to CodeAque.",
        "esc_exit = " + ("true" if cfg.esc_exit else "false"),
        "fullscreen_games = " + ("true" if cfg.fullscreen_games else "false"),
        "# The Steam tile opens Steam full screen in Big Picture mode (steam -gamepadui). false = normal window.",
        "steam_bigpicture = " + ("true" if cfg.steam_bigpicture else "false"),
        "# Start-up intro: your own video (intro.mp4 / .webm / .mkv / .mov in ~/.local/share/atari) and CodeAque's own short animation.",
        "intro_enabled = " + ("true" if cfg.intro_enabled else "false"),
        "intro_default = " + ("true" if cfg.intro_default else "false"),
        "intro_sound = " + ("true" if cfg.intro_sound else "false"),
        "",
        "[retroarch]",
        '# Leave empty to auto-detect. Example: command = "flatpak run org.libretro.RetroArch"',
        "command = " + _q(cfg.retroarch_command),
        "cores_dir = " + _q(cfg.cores_dir),
        "",
        "# Emulator programs. Leave a line out to auto-detect (a program on your PATH or a Flatpak).",
        "# Use it to point at your own copy, e.g.   rpcs3 = \"flatpak run net.rpcs3.RPCS3\"",
        "# Emulator ids: see Settings > Emulators, or run scripts/install-everything.sh --list",
        "[emulators]",
    ]
    for eid, cmd in sorted(cfg.emulator_commands.items()):
        out.append(f"{eid} = {_q(cmd)}")
    out += [
        "",
        "# One section per console you changed. `roms` is a list of folders to scan. `emulator` picks one from",
        "# the built-in list (empty = automatic). `command` is your own launch command (empty = automatic):",
        "# {rom} = the game file, {rom_dir}, {rom_name}, {retroarch}, {core_path}. Example:",
        '#   command = "mgba-qt -f {rom}"',
    ]
    for sc in cfg.systems.values():
        sd = SYSTEM_BY_ID.get(sc.id)
        touched = (sd is None or sc.roms or sc.command or sc.emulator or sc.core != sd.core
                   or sc.name != sd.name or list(sc.extensions) != list(sd.extensions))
        if not touched:
            continue
        out += [
            "",
            f"[systems.{sc.id if re.fullmatch(r'[A-Za-z0-9_-]+', sc.id) else _q(sc.id)}]",
            "name = " + _q(sc.name),
            "roms = " + _ql(sc.roms),
            "extensions = " + _ql(sc.extensions),
            "core = " + _q(sc.core),
            "emulator = " + _q(sc.emulator),
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
