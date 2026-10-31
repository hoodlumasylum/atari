"""Windows games: finding the .exe, archives, runners (umu / Proton / Wine), the add flow through the real QML window."""
import io
import json
import os
import stat
import tarfile
import hashlib
import zipfile
from pathlib import Path

import pytest

from atarilauncher import config, diagnose, installer, launcher, library, windows
from tests.fakeserver import Fake


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path / "conf"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path


def make_game_tree(root: Path):
    (root / "Game_Data").mkdir(parents=True)
    (root / "Game.exe").write_bytes(b"MZ" + b"\0" * 5000)
    (root / "UnityCrashHandler64.exe").write_bytes(b"MZ" + b"\0" * 90000)
    (root / "unins000.exe").write_bytes(b"MZ" + b"\0" * 90000)
    (root / "extras").mkdir()
    (root / "extras" / "setup.exe").write_bytes(b"MZ" + b"\0" * 900000)
    return root


def stub(path: Path, body: str):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_find_exes_prefers_the_unity_game_and_skips_junk(tmp_path):
    root = make_game_tree(tmp_path / "g")
    found = [c.rel for c in windows.find_exes(root)]
    assert found[0] == "Game.exe"
    assert "UnityCrashHandler64.exe" not in found and "unins000.exe" not in found
    assert found[-1] == os.path.join("extras", "setup.exe")      # an installer is listed, but last


def test_clean_name_and_slug():
    assert windows.clean_name("Dreams_of_Saturn_v1.2.zip") == "Dreams of Saturn v1.2"
    assert windows.clean_name("Some Game.7z") == "Some Game"
    assert windows.slugify("Dreams of Saturn!") == "dreams-of-saturn"


def test_zip_extracts_and_refuses_unsafe_paths(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Game/Game.exe", b"MZ")
        zf.writestr("Game/Game_Data/x.dat", b"1")
    seen = []
    windows.extract_archive(z, tmp_path / "out", lambda d, t: seen.append((d, t)))
    assert (tmp_path / "out/Game/Game.exe").is_file() and seen[-1] == (2, 2)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.exe", b"MZ")
    with pytest.raises(windows.WinError, match="unsafe"):
        windows.extract_archive(bad, tmp_path / "out2")
    assert not (tmp_path / "evil.exe").exists()
    broken = tmp_path / "b.zip"
    broken.write_bytes(b"not a zip")
    with pytest.raises(windows.WinError, match="could not be opened"):
        windows.extract_archive(broken, tmp_path / "out3")


def test_7z_needs_the_7z_program_and_uses_it_when_there(tmp_path):
    a = tmp_path / "g.7z"
    a.write_bytes(b"7z")
    with pytest.raises(windows.WinError, match="7-Zip"):
        windows.extract_archive(a, tmp_path / "o", which=lambda n: None)
    fake7z = stub(tmp_path / "7z", 'for a in "$@"; do case "$a" in -o*) d="${a#-o}";; esac; done\n'
                                   'mkdir -p "$d" && echo MZ > "$d/Game.exe"\n')
    windows.extract_archive(a, tmp_path / "o", which=lambda n: str(fake7z) if n == "7z" else None)
    assert (tmp_path / "o/Game.exe").is_file()


def test_store_add_remove_unique_ids_and_cover_copy(env, tmp_path):
    exe = tmp_path / "Game.exe"
    exe.write_bytes(b"MZ")
    cover = tmp_path / "c.png"
    cover.write_bytes(b"png")
    a = windows.add_game("Dreams of Saturn", str(exe), str(cover))
    b = windows.add_game("Dreams of Saturn", str(exe))
    assert a.id == "dreams-of-saturn" and b.id == "dreams-of-saturn-2"
    assert Path(a.cover).is_file() and Path(a.cover).read_bytes() == b"png"
    assert [g.name for g in windows.load_games()] == ["Dreams of Saturn"] * 2
    assert windows.remove_game(a.gid) and len(windows.load_games()) == 1
    assert exe.exists()                                              # only CodeAque's entry goes
    windows.games_file().write_text("{broken")
    assert windows.load_games() == []                                # a damaged file never crashes CodeAque


def test_games_show_up_in_the_library(env, tmp_path):
    exe = tmp_path / "Game.exe"
    exe.write_bytes(b"MZ")
    windows.add_game("My Fan Game", str(exe))
    res = library.build_library(config.default_config())
    g = [x for x in res.games if x.platform == "windows"]
    assert len(g) == 1 and g[0].title == "My Fan Game" and g[0].platform_name == "PC Games"


def fake_steam_home(home: Path, proton: str):
    d = home / ".steam/steam/steamapps/common" / proton
    d.mkdir(parents=True)
    stub(d / "proton", "echo proton\n")
    return home / ".steam/steam"


def test_runner_order_custom_umu_proton_wine(env, tmp_path):
    home = tmp_path / "home"
    cfg = config.default_config()
    nothing = lambda n: None
    assert windows.find_runner(cfg, home, nothing).kind == ""
    assert "PC game support" in windows.runner_status(cfg, home, nothing)[1]
    assert windows.find_runner(cfg, home, lambda n: "/usr/bin/wine" if n == "wine" else None).kind == "wine"
    root = fake_steam_home(home, "Proton 8.0")
    fake_steam_home(home, "Proton 9.0")
    r = windows.find_runner(cfg, home, lambda n: "/usr/bin/wine" if n == "wine" else None)
    assert r.kind == "proton" and "Proton 9.0" in r.cmd[0] and r.steam_root == str(root)
    r = windows.find_runner(cfg, home, lambda n: "/usr/bin/" + n if n in ("wine", "umu-run") else None)
    assert r.kind == "umu"
    cfg.emulator_commands["windows"] = "mycmd --flag"
    assert windows.find_runner(cfg, home, lambda n: "/x").kind == "custom"


def test_ge_proton_is_preferred_over_steams_own(env, tmp_path):
    home = tmp_path / "home"
    root = fake_steam_home(home, "Proton 9.0")
    ge = root / "compatibilitytools.d/GE-Proton9-20"
    ge.mkdir(parents=True)
    stub(ge / "proton", "echo ge\n")
    script, _ = windows.find_proton(home)
    assert "GE-Proton9-20" in script


def test_build_launch_per_runner_uses_a_private_prefix(env, tmp_path):
    home = tmp_path / "home"
    exe = tmp_path / "Game.exe"
    exe.write_bytes(b"MZ")
    g = windows.WinGame("my-game", "My Game", str(exe))
    cfg = config.default_config()
    cmd, e, cwd, label = windows.build_launch(cfg, g, home, lambda n: "/bin/umu-run" if n == "umu-run" else None)
    assert cmd == ["/bin/umu-run", str(exe)] and e["WINEPREFIX"].endswith("prefixes/my-game") and cwd == tmp_path
    assert Path(e["WINEPREFIX"]).is_dir() and e["GAMEID"] == "umu-0"
    root = fake_steam_home(home, "Proton 9.0")
    cmd, e, _, label = windows.build_launch(cfg, g, home, lambda n: None)
    assert cmd[1] == "run" and cmd[-1] == str(exe)
    assert e["STEAM_COMPAT_DATA_PATH"].endswith("prefixes/my-game") and e["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == str(root)
    cmd, e, *_ = windows.build_launch(cfg, g, tmp_path / "nohome", lambda n: "/usr/bin/wine" if n == "wine" else None)
    assert cmd == ["/usr/bin/wine", str(exe)] and "WINEPREFIX" in e


def test_build_launch_errors_are_plain_english(env, tmp_path):
    cfg = config.default_config()
    g = windows.WinGame("x", "X", str(tmp_path / "missing.exe"))
    with pytest.raises(windows.WinError, match="missing"):
        windows.build_launch(cfg, g, tmp_path, lambda n: "/x")
    (tmp_path / "ok.exe").write_bytes(b"MZ")
    with pytest.raises(windows.WinError, match="PC game support"):
        windows.build_launch(cfg, windows.WinGame("x", "X", str(tmp_path / "ok.exe")), tmp_path / "nohome", lambda n: None)


def test_launching_through_a_stub_runner(env, tmp_path, monkeypatch):
    """The whole launch path with a fake umu-run that records what it was given."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "record.txt"
    stub(bindir / "umu-run", f'echo "$@" > {record}\necho "WINEPREFIX=$WINEPREFIX GAMEID=$GAMEID PWD=$PWD" >> {record}\n')
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    exe = tmp_path / "Dreams Of Saturn" / "Game.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    windows.add_game("Dreams of Saturn", str(exe))
    game = [g for g in library.build_library(config.default_config()).games if g.platform == "windows"][0]
    started = []
    secs, err = launcher.run_game(config.default_config(), game, on_started=lambda: started.append(1))
    text = record.read_text()
    assert started and str(exe) in text and "prefixes/dreams-of-saturn" in text and "GAMEID=umu-0" in text
    assert f"PWD={exe.parent}" in text
    assert err == ""                                                  # a clean exit, even though it was quick


def test_a_runner_that_fails_at_once_gives_advice(env, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub(bindir / "umu-run", "exit 3\n")
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    exe = tmp_path / "G.exe"
    exe.write_bytes(b"MZ")
    windows.add_game("G", str(exe))
    game = [g for g in library.build_library(config.default_config()).games if g.platform == "windows"][0]
    secs, err = launcher.run_game(config.default_config(), game, on_started=lambda: None)
    assert "closed right away" in err and "Fix my game" in err


def test_install_umu_checks_the_checksum_and_never_installs_a_bad_download(env, tmp_path, monkeypatch):
    from atarilauncher import covers
    home = tmp_path / "home"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        data = b"#!/usr/bin/env python3\nprint('umu')\n"
        ti = tarfile.TarInfo("umu/umu-run")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
    pkg = buf.getvalue()
    f = Fake()
    try:
        def release(digest):
            f.files["/rel"] = json.dumps({"assets": [{"name": "umu-launcher-1.4.4-zipapp.tar", "digest": digest,
                                                      "browser_download_url": f.url + "/dl.tar"}]}).encode()
        f.files["/dl.tar"] = pkg
        monkeypatch.setenv("ATARI_UMU_API", f.url + "/rel")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        http = covers.Http(timeout=3, pause=0, backoff=0.01)
        out = []
        release("sha256:" + "0" * 64)
        res = installer.install_umu(out.append, home, http)
        assert res.status == "failed" and "checksum" in res.detail and not (home / ".local/bin/umu-run").exists()
        release("")
        assert installer.install_umu(out.append, home, http).status == "failed"
        release("sha256:" + hashlib.sha256(pkg).hexdigest())
        res = installer.install_umu(out.append, home, http)
        assert res.status == "installed"
        assert (home / ".local/bin/umu-run").is_symlink() and os.access(home / ".local/bin/umu-run", os.X_OK)
        assert installer.install_umu(out.append, home, http).status == "already"
    finally:
        f.stop()


def test_the_install_everything_list_has_the_windows_helpers():
    ids = {e.id for e in installer.default_selection()}
    assert {"protonup", "wine", "umu"} <= ids
    from atarilauncher import apps
    assert apps.BY_ID["protonup"].flatpak == "net.davidotek.pupgui2"


def test_diagnose_controller_and_game_checks(env, tmp_path):
    js = tmp_path / "sys/js0/device"
    js.mkdir(parents=True)
    (js / "name").write_text("Xbox Wireless Controller\n")
    assert diagnose.controllers(str(tmp_path / "sys")) == ["Xbox Wireless Controller"]
    assert "Xbox Wireless Controller" in diagnose.controller_text(str(tmp_path / "sys"))
    assert "No game controller" in diagnose.controller_text(str(tmp_path / "none"))
    cfg = config.default_config()
    g = library.Game(gid="rom:x", title="Sonic", platform="genesis", platform_name="Genesis", rom_path=str(tmp_path / "gone.md"))
    rows = diagnose.check_game(cfg, g, str(tmp_path / "none"))
    bad = [r for r in rows if r["state"] == "bad"]
    assert any("missing" in r["advice"] for r in bad)                 # the ROM file is gone
    assert "problem" in diagnose.summary(rows)


def test_list_shows_the_windows_helpers(capsys):
    installer.list_status()
    text = capsys.readouterr().out
    assert "PC Games support (umu-launcher)" in text and "PC Games support (fallback runtime)" in text and "7-Zip" in text and "net.davidotek.pupgui2" in text
