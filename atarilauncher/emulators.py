"""The table of consoles and emulators (data-driven) + detection of what is installed.

Every console lists its emulators in order of preference. Each emulator can be a program on your PATH
or a Flatpak; Atari picks the first one that is installed (or the one you chose in Settings > Emulators).
Nothing here bundles emulators, firmware/BIOS, keys or games - you bring your own.

Flatpak IDs below were checked against Flathub (https://flathub.org/api/v2/appstream/<id>) on 2026-10-28;
apt names against the Ubuntu 22.04 / 24.04 archives (Linux Mint 21 / 22).
Run  scripts/install-everything.sh --help  (or Settings > Emulators > Install emulators and apps) to install them.
"""
from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import paths


# ---------------------------------------------------------------- emulator programs
@dataclass(frozen=True)
class Emu:
    id: str
    name: str
    exes: tuple          # program names to look for on PATH
    flatpak: str         # Flatpak app id ("" = none known)
    apt: str             # Debian/Ubuntu/Mint package ("" = none)
    template: str        # {exe} {rom} {rom_dir} {rom_name} {rom_text} {core_path}
    flatpak_opts: tuple = ()
    note: str = ""
    appimage: str = ""   # "owner/repo|release tag|file name": official AppImage on GitHub (checked against GitHub's SHA256)


EMUS: dict[str, Emu] = {e.id: e for e in [
    Emu("retroarch", "RetroArch", ("retroarch",), "org.libretro.RetroArch", "retroarch",
        "{exe} -f -L {core_path} {rom}"),
    Emu("duckstation", "DuckStation", ("duckstation-qt", "duckstation", "DuckStation-x64.AppImage"),
        "", "", "{exe} -batch -fullscreen -- {rom}",
        note="Needs your own PS1 BIOS (set up once inside DuckStation). Its Flathub package is end-of-life, so Atari "
             "installs the official AppImage from DuckStation's GitHub into ~/.local/share/atari/emulators.",
        appimage="stenzek/duckstation|latest|DuckStation-x64.AppImage"),
    Emu("pcsx2", "PCSX2", ("pcsx2-qt", "pcsx2"), "net.pcsx2.PCSX2", "", "{exe} -batch -fullscreen -- {rom}",
        note="Needs your own PS2 BIOS (set up once inside PCSX2)."),
    Emu("rpcs3", "RPCS3", ("rpcs3",), "net.rpcs3.RPCS3", "", "{exe} --no-gui {rom}",
        note="Needs your own PS3 firmware and games. Very heavy on integrated graphics."),
    Emu("ppsspp", "PPSSPP", ("PPSSPPSDL", "ppsspp", "PPSSPPQt"), "org.ppsspp.PPSSPP", "", "{exe} {rom} --fullscreen"),
    Emu("dolphin", "Dolphin", ("dolphin-emu",), "org.DolphinEmu.dolphin-emu", "", "{exe} -b -e {rom}"),
    Emu("cemu", "Cemu", ("cemu", "Cemu"), "info.cemu.Cemu", "", "{exe} -f -g {rom}",
        note="Needs your own Wii U keys/online files if a game requires them."),
    Emu("ryujinx", "Ryujinx (Ryubing)", ("ryujinx", "Ryujinx"), "io.github.ryubing.Ryujinx", "", "{exe} {rom}",
        note="Needs your own Switch firmware and keys (use Add BIOS files for prod.keys)."),
    Emu("switchfork", "Eden (Switch)", ("eden", "citron", "suyu", "yuzu"), "dev.eden_emu.eden", "",
        "{exe} -f -g {rom}", note="Needs your own Switch firmware and keys (use Add BIOS files for prod.keys)."),
    Emu("azahar", "Azahar / Lime3DS / Citra", ("azahar", "azahar-qt", "lime3ds", "lime3ds-gui", "citra-qt", "citra"),
        "org.azahar_emu.Azahar", "", "{exe} {rom}"),
    Emu("melonds", "melonDS", ("melonDS", "melonds"), "net.kuribo64.melonDS", "", "{exe} -f {rom}"),
    Emu("desmume", "DeSmuME", ("desmume", "desmume-cli"), "org.desmume.DeSmuME", "desmume", "{exe} {rom}"),
    Emu("mgba", "mGBA", ("mgba-qt",), "io.mgba.mGBA", "mgba-qt", "{exe} -f {rom}"),
    Emu("xemu", "xemu", ("xemu",), "app.xemu.xemu", "", "{exe} -dvd_path {rom}",
        note="Needs your own Xbox BIOS and hard-disk image (set up once inside xemu) and your own games."),
    Emu("mednafen", "Mednafen", ("mednafen",), "", "mednafen", "{exe} -video.fs 1 {rom}",
        note="Sega Saturn needs your own Saturn BIOS in ~/.mednafen/firmware."),
    Emu("flycast", "Flycast", ("flycast",), "org.flycast.Flycast", "", "{exe} {rom}"),
    Emu("rmg", "Rosalie's Mupen GUI", ("RMG",), "com.github.Rosalie241.RMG", "", "{exe} -f {rom}"),
    Emu("mupen64plus", "mupen64plus", ("mupen64plus",), "", "mupen64plus-ui-console", "{exe} --fullscreen {rom}"),
    Emu("mame", "MAME", ("mame",), "org.mamedev.MAME", "mame", "{exe} -rompath {rom_dir} {rom_name}",
        note="MAME needs the matching ROM sets; keep them together in one folder."),
    Emu("dosbox", "DOSBox", ("dosbox", "dosbox-staging"), "io.github.dosbox-staging", "dosbox",
        "{exe} -fullscreen {rom}"),
    Emu("scummvm", "ScummVM", ("scummvm",), "org.scummvm.ScummVM", "scummvm",
        "{exe} -f --path={rom_dir} {rom_text}",
        note="Put a small <game>.scummvm text file in the game folder containing the ScummVM game id."),
    Emu("fsuae", "FS-UAE", ("fs-uae",), "net.fsuae.FS-UAE", "fs-uae", "{exe} --fullscreen --floppy_drive_0={rom}",
        note="Needs your own Amiga Kickstart ROM."),
    Emu("vice", "VICE", ("x64sc", "x64"), "net.sf.VICE", "vice", "{exe} -fullscreen -autostart {rom}"),
]}


# ---------------------------------------------------------------- consoles
@dataclass(frozen=True)
class SystemDef:
    id: str
    name: str
    extensions: tuple
    aliases: tuple = ()
    core: str = ""                 # RetroArch core (when "retroarch" is among the emulators)
    emus: tuple = ()               # emulator ids in order of preference
    note: str = ""


def _s(id, name, exts, aliases=(), core="", emus=None, note=""):
    emus = emus if emus is not None else (("retroarch",) if core else ())
    return SystemDef(id, name, tuple(exts), tuple(aliases), core, tuple(emus), note)


Z = ("zip", "7z")
SYSTEMS: list[SystemDef] = [
    _s("atari2600", "Atari 2600", ("a26", "bin") + Z, ("2600", "atari-2600"), "stella_libretro"),
    _s("atari5200", "Atari 5200", ("a52", "bin", "car", "rom") + Z, ("5200", "atari-5200"), "atari800_libretro"),
    _s("atari7800", "Atari 7800", ("a78",) + Z, ("7800", "atari-7800"), "prosystem_libretro"),
    _s("atarilynx", "Atari Lynx", ("lnx",) + Z, ("lynx",), "handy_libretro"),
    _s("atarijaguar", "Atari Jaguar", ("j64", "jag") + Z, ("jaguar",), "virtualjaguar_libretro"),
    _s("nes", "Nintendo NES", ("nes", "fds", "unf", "unif") + Z, ("famicom",), "fceumm_libretro"),
    _s("snes", "Super Nintendo", ("sfc", "smc", "swc", "fig") + Z, ("superfamicom", "sfc"), "snes9x_libretro"),
    _s("n64", "Nintendo 64", ("n64", "z64", "v64") + Z, (), "mupen64plus_next_libretro",
       ("rmg", "mupen64plus", "retroarch")),
    _s("gb", "Game Boy / Color", ("gb", "gbc") + Z, ("gbc", "gameboy"), "gambatte_libretro", ("mgba", "retroarch")),
    _s("gba", "Game Boy Advance", ("gba",) + Z, ("gameboyadvance",), "mgba_libretro", ("mgba", "retroarch")),
    _s("nds", "Nintendo DS", ("nds",) + Z, ("ds",), "melonds_libretro", ("melonds", "desmume", "retroarch")),
    _s("n3ds", "Nintendo 3DS", ("3ds", "cci", "cxi", "3dsx"), ("3ds", "nintendo3ds"), "", ("azahar",)),
    _s("gamecube", "GameCube", ("iso", "gcm", "ciso", "gcz", "rvz"), ("gc",), "", ("dolphin",)),
    _s("wii", "Nintendo Wii", ("wbfs", "wad", "rvz", "iso"), ("nintendowii",), "", ("dolphin",)),
    _s("wiiu", "Nintendo Wii U", ("wud", "wux", "rpx", "wua"), ("wii-u", "nintendowiiu"), "", ("cemu",)),
    _s("switch", "Nintendo Switch", ("nsp", "xci", "nca", "nro"), ("nintendoswitch", "nswitch"), "",
       ("ryujinx", "switchfork")),
    _s("genesis", "Sega Genesis", ("md", "gen", "smd") + Z, ("megadrive", "md"), "genesis_plus_gx_libretro"),
    _s("mastersystem", "Sega Master System", ("sms",) + Z, ("sms",), "genesis_plus_gx_libretro"),
    _s("gamegear", "Sega Game Gear", ("gg",) + Z, ("gg", "sega-game-gear"), "genesis_plus_gx_libretro"),
    _s("segacd", "Sega CD", ("cue", "chd", "iso"), ("megacd", "sega-cd", "mega-cd"), "genesis_plus_gx_libretro"),
    _s("saturn", "Sega Saturn", ("cue", "chd", "iso", "mdf"), ("sega-saturn",), "mednafen_saturn_libretro",
       ("mednafen", "retroarch")),
    _s("dreamcast", "Dreamcast", ("gdi", "cdi", "chd", "cue"), ("dc", "sega-dreamcast"), "flycast_libretro",
       ("flycast", "retroarch")),
    _s("pce", "PC Engine", ("pce", "sgx") + Z, ("turbografx", "tg16"), "mednafen_pce_fast_libretro"),
    _s("neogeo", "Neo Geo", ("zip", "7z", "neo"), ("neo-geo", "aes", "mvs"), "fbneo_libretro"),
    _s("arcade", "Arcade (MAME)", ("zip", "7z"), ("mame", "fbneo", "fba"), "mame2003_plus_libretro",
       ("mame", "retroarch")),
    _s("ps1", "PlayStation", ("cue", "chd", "pbp", "iso", "m3u"), ("psx", "playstation"), "pcsx_rearmed_libretro",
       ("duckstation", "retroarch")),
    _s("ps2", "PlayStation 2", ("iso", "chd", "cso", "gz"), ("playstation2", "playstation-2"), "", ("pcsx2",)),
    _s("ps3", "PlayStation 3", ("iso", "pkg"), ("playstation3", "playstation-3"), "", ("rpcs3",),
       "PS3 needs your own firmware and games (RPCS3), and is very demanding on integrated graphics."),
    _s("psp", "PlayStation Portable", ("iso", "cso", "pbp"), ("playstationportable",), "ppsspp_libretro",
       ("ppsspp", "retroarch")),
    _s("xbox", "Xbox Classic", ("iso", "xiso"), ("xboxclassic", "originalxbox", "xbox-classic", "xiso"), "",
       ("xemu",), "Xbox Classic needs your own BIOS, hard-disk image and games (xemu)."),
    _s("dos", "DOS", ("bat", "conf", "dosz"), ("msdos", "pc"), "dosbox_pure_libretro", ("dosbox", "retroarch")),
    _s("scummvm", "ScummVM", ("scummvm",), ("scumm",), "", ("scummvm",)),
    _s("amiga", "Amiga", ("adf", "ipf", "lha", "hdf", "uae", "dms"), ("commodoreamiga",), "puae_libretro",
       ("retroarch", "fsuae")),
    _s("c64", "Commodore 64", ("d64", "t64", "prg", "crt", "tap", "x64", "d71", "d81"), ("commodore64", "c-64"),
       "vice_x64_libretro", ("retroarch", "vice")),
    _s("msx", "MSX", ("rom", "mx1", "mx2", "dsk", "cas"), (), "bluemsx_libretro"),
    _s("zxspectrum", "ZX Spectrum", ("tzx", "tap", "z80", "sna", "szx"), ("spectrum", "zx"), "fuse_libretro"),
    _s("amstradcpc", "Amstrad CPC", ("dsk", "sna", "cdt", "cpr"), ("cpc",), "cap32_libretro"),
    _s("wonderswan", "WonderSwan", ("ws", "wsc"), ("wswan",), "mednafen_wswan_libretro"),
    _s("ngp", "Neo Geo Pocket", ("ngp", "ngc"), ("neogeopocket",), "mednafen_ngp_libretro"),
    _s("vb", "Virtual Boy", ("vb", "vboy"), ("virtualboy",), "mednafen_vb_libretro"),
    _s("3do", "3DO", ("iso", "chd", "cue"), ("3d0",), "opera_libretro"),
]
SYSTEM_BY_ID = {s.id: s for s in SYSTEMS}

# Consoles that cannot be launched from a file list (shown on the Emulators page only).
NOTES = [
    ("PlayStation Vita", "Vita3K is not on Flathub. Download it from vita3k.org if you want it; it installs games "
                         "inside its own window, so Atari cannot start Vita games by file."),
    ("Xbox 360", "The Xbox 360 emulator (Xenia) only runs on Windows, so it is not supported on Linux."),
]


# ---------------------------------------------------------------- detection
def flatpak_installed(app_id: str, home: Path | None = None) -> bool:
    """True when the Flatpak is really installed (per-user or system-wide). The ~/.var/app/<id> data folder is NOT
    a sign of an install (Atari's "Add BIOS files" can create it before the emulator is installed)."""
    home = home or Path.home()
    for base in (Path("/var/lib/flatpak/app"), home / ".local/share/flatpak/app"):
        p = base / app_id
        try:
            if p.is_dir() and any(p.iterdir()):  # a real install has x86_64/ and current inside
                return True
        except OSError:
            pass
    return False


def cores_dirs(cfg, home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    if cfg.cores_dir.strip():
        return [Path(cfg.cores_dir).expanduser()]
    return [home / ".config/retroarch/cores",
            home / ".var/app/org.libretro.RetroArch/config/retroarch/cores",
            home / "snap/retroarch/current/.config/retroarch/cores",
            Path("/usr/lib/x86_64-linux-gnu/libretro"), Path("/usr/lib64/libretro"),
            Path("/usr/lib/libretro"), Path("/usr/local/lib/libretro")]


def resolve_core_path(cfg, core: str, home: Path | None = None) -> str:
    if not core:
        return ""
    name = core if core.endswith(".so") else core + ".so"
    dirs = cores_dirs(cfg, home)
    for d in dirs:
        if (d / name).is_file():
            return str(d / name)
    return str(dirs[0] / name)  # best guess; RetroArch will explain if missing


def core_installed(cfg, core: str, home: Path | None = None) -> bool:
    return bool(core) and Path(resolve_core_path(cfg, core, home)).is_file()


def configured_command(cfg, emu_id: str) -> str:
    if emu_id == "retroarch":
        return cfg.retroarch_command.strip()
    return cfg.emulator_commands.get(emu_id, "").strip()


def appimage_dir(home: Path | None = None) -> Path:
    """Where Atari puts AppImages it installed (per user, no root)."""
    return (home / ".local/share/atari/emulators") if home is not None else paths.data_dir() / "emulators"


def appimage_path(emu: Emu, home: Path | None = None) -> str:
    """Path of the AppImage Atari installed for this emulator, or ''."""
    if not emu.appimage:
        return ""
    p = appimage_dir(home) / emu.appimage.split("|")[2]
    return str(p) if p.is_file() else ""


def find_emu(cfg, emu_id: str, home: Path | None = None) -> tuple[list[str], str]:
    """(command that starts the program, how) where how is 'custom', 'native', 'flatpak' or '' (not installed).
    When it is not installed the command is the best guess (the plain program name)."""
    emu = EMUS[emu_id]
    custom = configured_command(cfg, emu_id)
    if custom:
        return shlex.split(custom), "custom"
    for exe in emu.exes:
        if shutil.which(exe):
            return [exe], "native"
    if emu.flatpak and shutil.which("flatpak") and flatpak_installed(emu.flatpak, home):
        return ["flatpak", "run", *emu.flatpak_opts, emu.flatpak], "flatpak"
    ai = appimage_path(emu, home)
    if ai:
        return [ai], "native"
    return [emu.exes[0]], ""


@dataclass
class Choice:
    emu: Emu
    cmd: list[str]
    how: str            # custom | native | flatpak | "" (missing)
    core: str = ""
    ready: bool = False  # program found (and, for RetroArch, the core file too)
    problem: str = ""


def candidates(cfg, system, home: Path | None = None) -> list[Choice]:
    """All emulators for a console (system = SystemConfig) with their install state, in preference order."""
    sd = SYSTEM_BY_ID.get(system.id)
    out: list[Choice] = []
    for eid in (sd.emus if sd else ()):
        cmd, how = find_emu(cfg, eid, home)
        emu = EMUS[eid]
        core = ""
        ready = bool(how)
        problem = "" if how else "not installed"
        if eid == "retroarch":
            core = system.core or (sd.core if sd else "")
            if how and core and not core_installed(cfg, core, home) and how != "custom":
                ready, problem = False, f"RetroArch is installed but the core {core.replace('_libretro', '')} is missing"
        out.append(Choice(emu, cmd, how, core, ready, problem))
    return out


def choose(cfg, system, home: Path | None = None) -> Choice | None:
    """The emulator Atari will use for this console (your choice, else the first installed one)."""
    cands = candidates(cfg, system, home)
    if not cands:
        return None
    if system.emulator:
        for c in cands:
            if c.emu.id == system.emulator:
                return c
    for c in cands:
        if c.ready:
            return c
    # retroarch with a custom core path always counts as usable
    return cands[0]


def install_hint(system, home: Path | None = None) -> str:
    """Plain-language instructions for installing the first emulator of a console."""
    sd = SYSTEM_BY_ID.get(system.id)
    if not sd or not sd.emus:
        return ""
    emu = EMUS[sd.emus[0]]
    bits = []
    if emu.flatpak:
        bits.append(f"flatpak install flathub {emu.flatpak}")
    if emu.apt:
        bits.append(f"sudo apt install {emu.apt}")
    if sd.emus[0] == "retroarch" and sd.core:
        core = sd.core.replace("_libretro", "")
        text = (f"Install RetroArch and its {core} core: open Settings > Emulators > Install emulators and apps "
                f"(or run:  flatpak install flathub org.libretro.RetroArch)")
    elif bits:
        text = f"Install {emu.name}: open Settings > Emulators > Install emulators and apps  (or run:  " + "   or   ".join(bits) + ")"
    else:
        text = f"Install {emu.name} (see its website) or set its command in Settings > Emulators"
    return text + ". " + (emu.note or sd.note)


def status_line(cfg, system, home: Path | None = None) -> tuple[bool, str, str]:
    """(ready, short status like 'DuckStation (Flatpak)', detail/hint) for the Emulators page."""
    sd = SYSTEM_BY_ID.get(system.id)
    if system.command.strip():
        return True, "Custom command", system.command.strip()
    ch = choose(cfg, system, home)
    if ch is None:
        return False, "No emulator", "Set a launch command in config.toml (this console is not in the built-in list)."
    how = {"native": "installed", "flatpak": "Flatpak", "custom": "your command"}.get(ch.how, "")
    if ch.ready:
        label = f"{ch.emu.name} ({how})"
        if ch.emu.id == "retroarch":
            label += f" - {(ch.core or '').replace('_libretro', '')} core"
        others = [c for c in candidates(cfg, system, home) if c is not ch and c.ready]
        extra = ("Also available: " + ", ".join(c.emu.name for c in others) + ". ") if others else ""
        pick = "You chose this emulator. " if system.emulator else ""
        return True, label, (pick + extra + (ch.emu.note or (sd.note if sd else ""))).strip()
    return False, "Not installed", (install_hint(system, home))


def expand(template: str, cfg, system, rom: str, exe: list[str], core: str = "", home: Path | None = None) -> list[str]:
    """Fill a launch template: {exe} (or {retroarch}/{rpcs3}/{xemu}/{<emulator id>}) and the {rom...} words."""
    from . import paths  # noqa: F401
    p = Path(rom)
    rom_text = p.stem
    if p.suffix.lower() == ".scummvm":
        try:
            first = p.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            rom_text = first[0].strip() if first and first[0].strip() else p.stem
        except OSError:
            pass
    repl = {
        "{rom}": rom, "{rom_dir}": str(p.parent), "{rom_name}": p.stem, "{rom_text}": rom_text,
        "{core}": core or system.core, "{core_path}": resolve_core_path(cfg, core or system.core, home),
        "{cores_dir}": str(cores_dirs(cfg, home)[0]),
    }
    out: list[str] = []
    for tok in shlex.split(template):
        if tok == "{exe}":
            out += exe
            continue
        if tok.startswith("{") and tok.endswith("}") and tok[1:-1] in EMUS:
            out += find_emu(cfg, tok[1:-1], home)[0]
            continue
        for k, v in repl.items():
            tok = tok.replace(k, v)
        out.append(tok)
    return out


def grant_rom_access(cmd: list[str], rom: str) -> list[str]:
    """A Flatpak emulator can only see folders it was given. Several (DuckStation, PCSX2, Rosalie's Mupen GUI, Eden)
    have no access to ~/Games or a USB drive, so give it read access to the game's folder for this launch only."""
    if len(cmd) >= 2 and cmd[0] == "flatpak" and cmd[1] == "run" and rom and not any(
            a.startswith("--filesystem=") for a in cmd[2:4]):
        folder = str(Path(rom).parent)
        if folder not in ("", ".", "/") and ":" not in folder and "," not in folder:
            return [cmd[0], cmd[1], f"--filesystem={folder}:ro", *cmd[2:]]
    return cmd


def next_preference(cfg, system, home: Path | None = None) -> str:
    """Cycle the chosen emulator for a console: auto -> each emulator -> auto."""
    ids = [c.emu.id for c in candidates(cfg, system, home)]
    if len(ids) < 2:
        return ""
    if not system.emulator or system.emulator not in ids:
        return ids[0]
    i = ids.index(system.emulator)
    return ids[i + 1] if i + 1 < len(ids) else ""


# ---------------------------------------------------------------- command line helper
def _cli(argv=None) -> int:
    from .installer import main
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(_cli())
