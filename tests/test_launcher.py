import os
import stat
import sys

import pytest

from atarilauncher import config, launcher
from atarilauncher.library import Game


def cfg_with(**kw):
    cfg = config.default_config()
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_default_retroarch_template(tmp_path):
    cfg = cfg_with(retroarch_command="retroarch", cores_dir=str(tmp_path))
    (tmp_path / "fceumm_libretro.so").write_bytes(b"")
    cmd = launcher.build_rom_command(cfg, cfg.systems["nes"], "/roms/My Game (USA).nes")
    assert cmd == ["retroarch", "-f", "-L", str(tmp_path / "fceumm_libretro.so"), "/roms/My Game (USA).nes"]


def test_flatpak_retroarch_command_expands():
    cfg = cfg_with(retroarch_command="flatpak run org.libretro.RetroArch", cores_dir="/c")
    cmd = launcher.build_rom_command(cfg, cfg.systems["snes"], "/r/x.sfc")
    assert cmd[:3] == ["flatpak", "run", "org.libretro.RetroArch"] and cmd[-1] == "/r/x.sfc"


def test_any_emulator_command_works():
    cfg = cfg_with()
    cfg.systems["gba"].command = 'mgba-qt -f "{rom}" --dir {rom_dir}'
    assert launcher.build_rom_command(cfg, cfg.systems["gba"], "/a b/g.gba") == \
        ["mgba-qt", "-f", "/a b/g.gba", "--dir", "/a b"]


def test_empty_or_invalid_command_gives_friendly_error():
    cfg = cfg_with()
    cfg.systems["gba"].command = ""
    with pytest.raises(launcher.LaunchError):
        launcher.build_rom_command(cfg, cfg.systems["gba"], "/x")
    cfg.systems["gba"].command = 'unterminated "quote'
    with pytest.raises(launcher.LaunchError):
        launcher.build_rom_command(cfg, cfg.systems["gba"], "/x")


def test_steam_command():
    assert launcher.build_steam_command(cfg_with(steam_command="steam"), "620") == ["steam", "steam://rungameid/620"]
    cfg = cfg_with(steam_command="flatpak run com.valvesoftware.Steam")
    assert launcher.build_steam_command(cfg, "730")[-1] == "steam://rungameid/730"


def test_find_steam_pids_in_fake_proc(tmp_path):
    for pid, args in {"100": [b"reaper", b"SteamLaunch", b"AppId=620", b"--", b"game"],
                      "101": [b"reaper", b"SteamLaunch", b"AppId=6200", b"--"],
                      "102": [b"bash"]}.items():
        d = tmp_path / pid
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(args) + b"\0")
    (tmp_path / "self").mkdir()
    assert launcher.find_steam_pids("620", str(tmp_path)) == [100]
    assert launcher.find_steam_pids("1", str(tmp_path)) == []


def test_clean_env_removes_our_python_settings(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/x")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    env = launcher.clean_env()
    assert "PYTHONPATH" not in env and "QT_QPA_PLATFORM" not in env


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path / "conf"))


def fake_emulator(tmp_path, body):
    exe = tmp_path / "fake-emu"
    exe.write_text("#!/bin/sh\n" + body + "\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def test_run_game_measures_play_time(tmp_path, isolated):
    rom = tmp_path / "g.nes"
    rom.write_bytes(b"x")
    exe = fake_emulator(tmp_path, "sleep 1.2")
    cfg = cfg_with()
    cfg.systems["nes"].command = f"{exe} {{rom}}"
    started = []
    secs, err = launcher.run_game(cfg, Game("rom:nes:x", "g", "nes", "NES", rom_path=str(rom)),
                                  on_started=lambda: started.append(1))
    assert err == "" and started == [1] and 1.0 < secs < 3.0


def test_run_game_reports_instant_crash(tmp_path, isolated):
    rom = tmp_path / "g.nes"
    rom.write_bytes(b"x")
    exe = fake_emulator(tmp_path, "echo boom >&2; exit 3")
    cfg = cfg_with()
    cfg.systems["nes"].command = f"{exe} {{rom}}"
    secs, err = launcher.run_game(cfg, Game("g", "g", "nes", "NES", rom_path=str(rom)), on_started=lambda: None)
    assert secs == 0 and "closed right away" in err


def test_run_game_missing_program_and_missing_rom(tmp_path, isolated):
    rom = tmp_path / "g.nes"
    rom.write_bytes(b"x")
    cfg = cfg_with()
    cfg.systems["nes"].command = "definitely-not-installed-xyz {rom}"
    with pytest.raises(launcher.LaunchError, match="Could not find"):
        launcher.run_game(cfg, Game("g", "g", "nes", "NES", rom_path=str(rom)), on_started=lambda: None)
    with pytest.raises(launcher.LaunchError, match="missing"):
        launcher.run_game(cfg, Game("g", "g", "nes", "NES", rom_path=str(tmp_path / "gone.nes")),
                          on_started=lambda: None)


def test_steam_session_tracking_with_fake_steam(tmp_path, isolated, monkeypatch):
    """Fake `steam` that 'starts' a game process (cmdline contains AppId=4242) for ~2 s."""
    game = tmp_path / "reaper"
    game.write_text("#!/bin/sh\nsleep 2\n")
    game.chmod(0o755)
    steam = tmp_path / "steam"
    steam.write_text(f"#!/bin/sh\n(nohup {game} SteamLaunch AppId=4242 -- x >/dev/null 2>&1 &)\n")
    steam.chmod(0o755)
    monkeypatch.setattr(launcher, "find_steam_pids",
                        lambda appid, proc_root="/proc": _pids_for(appid))
    cfg = cfg_with(steam_command=str(steam))
    g = Game("steam:4242", "Fake", "steam", "Steam", steam_appid="4242")
    secs, err = launcher._run_steam(cfg, g, lambda: None, poll=0.1, start_timeout=10, grace=0.5)
    assert err == "" and 1.0 < secs < 4.0


def _pids_for(appid):
    import subprocess
    out = subprocess.run(["pgrep", "-f", f"AppId={appid}"], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if int(p) != os.getpid()]
