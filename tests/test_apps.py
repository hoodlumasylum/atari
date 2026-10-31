import json
import sqlite3
from pathlib import Path

import pytest

from atarilauncher import apps, launcher, library
from atarilauncher.config import default_config

VERIFIED_FLATHUB_IDS = {   # checked against flathub.org on 2026-10-28
    "roblox": "org.vinegarhq.Sober", "heroic": "com.heroicgameslauncher.hgl", "lutris": "net.lutris.Lutris",
    "bottles": "com.usebottles.bottles", "itch": "io.itch.itch", "prism": "org.prismlauncher.PrismLauncher",
    "minecraft": "com.mojang.Minecraft", "moonlight": "com.moonlight_stream.Moonlight",
    "protonup": "net.davidotek.pupgui2", "kodi": "tv.kodi.Kodi", "steam": "com.valvesoftware.Steam",
    "transmission": "com.transmissionbt.Transmission", "obs": "com.obsproject.Studio", "spotify": "com.spotify.Client",
}


def nowhere(_n):
    return None


def test_app_table_uses_the_verified_flathub_ids():
    assert {a.id: a.flatpak for a in apps.APP_DEFS if not a.lutris} == VERIFIED_FLATHUB_IDS
    assert "unofficial" in apps.BY_ID["roblox"].note.lower() and "sign in" in apps.BY_ID["roblox"].note.lower()


def test_detection_hint_and_override(tmp_path):
    cfg = default_config()
    rb = apps.BY_ID["roblox"]
    ready, text = apps.app_status(cfg, rb, tmp_path, nowhere)
    assert not ready and "flatpak install flathub org.vinegarhq.Sober" in text and "Install emulators" in text
    (tmp_path / ".local/share/flatpak/app/org.vinegarhq.Sober/current").mkdir(parents=True)
    assert apps.app_command(cfg, rb, tmp_path, nowhere) == (["flatpak", "run", "org.vinegarhq.Sober"], "flatpak")
    cfg.emulator_commands["roblox"] = "/opt/sober/run --fast"
    assert apps.app_command(cfg, rb, tmp_path, nowhere) == (["/opt/sober/run", "--fast"], "custom")
    cfg2 = default_config()
    assert apps.app_command(cfg2, apps.BY_ID["lutris"], tmp_path, lambda n: "/usr/bin/lutris" if n == "lutris" else None) \
        == (["lutris"], "native")


def test_library_always_lists_the_apps_but_all_games_stays_games_only(tmp_path):
    cfg = default_config()
    cfg.steam_enabled = False
    res = library.build_library(cfg, home=tmp_path, metadata={})
    titles = [g.title for g in res.games if g.platform == apps.APPS]
    assert "Roblox" in titles and "Heroic Games Launcher" in titles and len(titles) == len([a for a in apps.APP_DEFS if a.group == "apps"])
    from atarilauncher.model import filter_games
    from atarilauncher.store import Store
    st = Store(tmp_path / "s.json")
    assert filter_games(res.games, st, "all", "") == []
    assert len(filter_games(res.games, st, apps.APPS, "")) == len([a for a in apps.APP_DEFS if a.group == "apps"])
    assert [g.title for g in filter_games(res.games, st, "all", "roblox")] == ["Roblox"]    # search still finds it


def test_launch_roblox_not_installed_gives_friendly_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(apps.shutil, "which", lambda n: None)
    cfg = default_config()
    g = next(g for g in library.build_library(cfg, home=tmp_path, metadata={}).games if g.title == "Roblox")
    with pytest.raises(launcher.LaunchError) as e:
        launcher.run_game(cfg, g, lambda: None)
    assert "not installed" in str(e.value) and "org.vinegarhq.Sober" in str(e.value)


def test_launch_app_runs_custom_command(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    cfg = default_config()
    flag = tmp_path / "ran"
    script = tmp_path / "sober.sh"
    script.write_text(f"#!/bin/sh\nsleep 0.2\ntouch {flag}\n")
    script.chmod(0o755)
    cfg.emulator_commands["roblox"] = str(script)
    g = next(g for g in library.build_library(cfg, home=tmp_path, metadata={}).games if g.title == "Roblox")
    started = []
    secs, err = launcher.run_game(cfg, g, lambda: started.append(1))
    assert started and flag.exists() and err == ""


# ------------------------------------------------------------------ Heroic / Lutris import
def test_heroic_games_imported_from_its_json(tmp_path):
    base = tmp_path / ".config/heroic"
    (base / "legendaryConfig/legendary").mkdir(parents=True)
    (base / "gog_store").mkdir(parents=True)
    (base / "store_cache").mkdir(parents=True)
    (base / "legendaryConfig/legendary/installed.json").write_text(json.dumps(
        {"Quail": {"app_name": "Quail", "title": "Epic Game", "install_path": "/g/epic"}}))
    (base / "gog_store/installed.json").write_text(json.dumps(
        {"installed": [{"appName": "1207658930", "install_path": "/g/gog/Some GOG"}]}))
    (base / "store_cache/gog_library.json").write_text(json.dumps({"games": [{"app_name": "1207658930", "title": "Nice GOG Game"}]}))
    (base / "store_cache/nile_library.json").write_text("not json")                 # junk is ignored
    games = {g.title: g for g in apps.heroic_games(tmp_path)}
    assert set(games) == {"Epic Game", "Nice GOG Game"}
    assert games["Epic Game"].uri == "heroic://launch/legendary/Quail"
    assert games["Nice GOG Game"].uri == "heroic://launch/gog/1207658930"


def make_lutris_db(path, rows):
    path.parent.mkdir(parents=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, runner TEXT, installed INTEGER, "
                "hidden INTEGER, lastplayed INTEGER)")
    con.executemany("INSERT INTO games (id,name,slug,runner,installed,hidden,lastplayed) VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def test_lutris_games_imported_from_pga_db(tmp_path):
    make_lutris_db(tmp_path / ".local/share/lutris/pga.db", [
        (1, "Wine Thing", "wine-thing", "wine", 1, 0, 100), (2, "Not Installed", "x", "linux", 0, 0, 0),
        (3, "Hidden", "h", "linux", 1, 1, 0), (4, "Steam dup", "s", "steam", 1, 0, 0), (5, "Native", "n", "linux", 1, None, 0)])
    games = apps.lutris_games(tmp_path)
    assert sorted(g.title for g in games) == ["Native", "Wine Thing"]
    assert {g.title: g.uri for g in games}["Wine Thing"] == "lutris:rungameid/1"


def test_imported_games_appear_in_library_and_launch_through_their_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    make_lutris_db(tmp_path / ".var/app/net.lutris.Lutris/data/lutris/pga.db", [(7, "Wine Thing", "w", "wine", 1, 0, 0)])
    cfg = default_config()
    cfg.steam_enabled = False
    res = library.build_library(cfg, home=tmp_path, metadata={})
    g = next(g for g in res.games if g.platform == "lutris")
    assert g.title == "Wine Thing" and g.launch == "lutris:rungameid/7" and g.platform_name == "Lutris"
    # launched with the app's command + the link
    flag = tmp_path / "args"
    script = tmp_path / "lutris.sh"
    script.write_text(f'#!/bin/sh\necho "$@" > {flag}\n')
    script.chmod(0o755)
    cfg.emulator_commands["lutris"] = str(script)
    launcher.run_game(cfg, g, lambda: None)
    assert flag.read_text().strip() == "lutris:rungameid/7"
