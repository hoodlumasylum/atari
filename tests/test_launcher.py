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
    cfg.systems["custom"] = config.SystemConfig("custom", "My Console", ["x"])  # not in the built-in table
    with pytest.raises(launcher.LaunchError):
        launcher.build_rom_command(cfg, cfg.systems["custom"], "/x")
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
    secs, err = launcher._run_steam(cfg, g, lambda: None, poll=0.1, start_timeout=10, grace=0.5,
                                     steam_running=lambda: True, ui_ready=lambda: True, settle=0)
    assert err == "" and 1.0 < secs < 4.0


def _pids_for(appid):
    import subprocess
    out = subprocess.run(["pgrep", "-f", f"AppId={appid}"], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if int(p) != os.getpid()]


def test_table_picks_installed_emulator_native_or_flatpak(tmp_path, monkeypatch):
    from atarilauncher import emulators
    cfg = cfg_with()
    home = tmp_path / "home"
    monkeypatch.setattr(emulators.shutil, "which", lambda n: "/usr/bin/flatpak" if n == "flatpak" else None)
    # nothing installed: best guess + friendly status
    ready, label, hint = emulators.status_line(cfg, cfg.systems["ps2"], home)
    assert not ready and "flatpak install flathub net.pcsx2.PCSX2" in hint
    # Flatpak installed: detected automatically
    # a data folder alone (e.g. created by "Add BIOS files") is NOT an install
    (home / ".var/app/net.pcsx2.PCSX2").mkdir(parents=True)
    assert not emulators.status_line(cfg, cfg.systems["ps2"], home)[0]
    (home / ".local/share/flatpak/app/net.pcsx2.PCSX2/current").mkdir(parents=True)
    cmd = launcher.build_rom_command(cfg, cfg.systems["ps2"], "/g/x.iso", home)
    # the Flatpak is given read access to the game's folder for this launch only
    assert cmd == ["flatpak", "run", "--filesystem=/g:ro", "net.pcsx2.PCSX2", "-batch", "-fullscreen", "--", "/g/x.iso"]
    assert emulators.status_line(cfg, cfg.systems["ps2"], home)[:2] == (True, "PCSX2 (Flatpak)")
    # a program on PATH wins over nothing; user override wins over detection
    monkeypatch.setattr(emulators.shutil, "which", lambda n: f"/usr/bin/{n}" if n in ("rpcs3", "xemu") else None)
    assert launcher.build_rom_command(cfg, cfg.systems["ps3"], "/g/x.iso", home) == ["rpcs3", "--no-gui", "/g/x.iso"]
    assert launcher.build_rom_command(cfg, cfg.systems["xbox"], "/g/x.iso", home) == ["xemu", "-dvd_path", "/g/x.iso"]
    cfg.emulator_commands["xemu"] = "flatpak run app.xemu.xemu"
    assert launcher.build_rom_command(cfg, cfg.systems["xbox"], "/g/x.iso", home)[:3] == ["flatpak", "run", "app.xemu.xemu"]


def test_user_choice_of_emulator_and_cycle(tmp_path, monkeypatch):
    from atarilauncher import emulators
    cfg = cfg_with(retroarch_command="retroarch", cores_dir=str(tmp_path))
    (tmp_path / "mgba_libretro.so").write_bytes(b"")
    monkeypatch.setattr(emulators.shutil, "which", lambda n: "/usr/bin/mgba-qt" if n == "mgba-qt" else None)
    gba = cfg.systems["gba"]
    assert launcher.build_rom_command(cfg, gba, "/g.gba")[0] == "mgba-qt"
    gba.emulator = emulators.next_preference(cfg, gba)
    assert gba.emulator == "mgba"
    gba.emulator = emulators.next_preference(cfg, gba)
    assert gba.emulator == "retroarch"
    assert launcher.build_rom_command(cfg, gba, "/g.gba")[:2] == ["retroarch", "-f"]
    gba.emulator = emulators.next_preference(cfg, gba)
    assert gba.emulator == ""


def test_scummvm_uses_game_id_from_file(tmp_path):
    cfg = cfg_with()
    f = tmp_path / "Monkey.scummvm"
    f.write_text("monkey\n")
    cmd = launcher.build_rom_command(cfg, cfg.systems["scummvm"], str(f))
    assert cmd[-1] == "monkey" and f"--path={tmp_path}" in cmd


def test_every_system_has_valid_templates():
    from atarilauncher import emulators
    for sd in emulators.SYSTEMS:
        for eid in sd.emus:
            assert eid in emulators.EMUS, (sd.id, eid)
        assert sd.extensions and ("retroarch" not in sd.emus or sd.core)
