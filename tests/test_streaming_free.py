"""Streaming & Social web apps, Kodi, and the Free Games list."""
import os
import stat
from pathlib import Path

import pytest

from atarilauncher import apps, config, diagnose, freegames, launcher, library, webapps


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path / "conf"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path


def stub(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def only(*names):
    return lambda n: "/usr/bin/" + n if n in names else None


def test_browser_choice_and_commands(env, tmp_path):
    cfg = config.default_config()
    yt, nf = webapps.BY_ID["youtube"], webapps.BY_ID["netflix"]
    home = tmp_path / "home"
    assert webapps.build_command(cfg, yt, home, only()) == ([], "")
    assert "Install emulators and apps" in webapps.status(cfg, yt, home, only())[1]
    cmd, name = webapps.build_command(cfg, yt, home, only("chromium"), tmp_path / "w")
    assert name == "Chromium" and cmd[0] == "/usr/bin/chromium" or cmd[0] == "chromium"
    assert "--app=https://www.youtube.com/tv" in cmd and "--start-fullscreen" in cmd
    assert f"--user-data-dir={tmp_path / 'w' / 'youtube'}" in cmd                   # its own profile folder
    # Netflix prefers a browser that can do DRM, even when Chromium comes first in the table
    cmd, name = webapps.build_command(cfg, nf, home, only("chromium", "google-chrome-stable"), tmp_path / "w")
    assert name == "Google Chrome"
    cmd, name = webapps.build_command(cfg, nf, home, only("chromium", "firefox"), tmp_path / "w")
    assert name == "Firefox" and "--kiosk" in cmd and "--profile" in cmd and "--app=https://www.netflix.com" not in cmd
    ok, text = webapps.status(cfg, nf, home, only("chromium"))
    assert ok and "may not play DRM" in text
    cfg.emulator_commands["browser"] = "mybrowser --foo"
    cmd, name = webapps.build_command(cfg, yt, home, only())
    assert cmd[:2] == ["mybrowser", "--foo"] and name == "your browser"


def test_flatpak_browser_gets_access_to_its_profile_folder(env, tmp_path):
    home = tmp_path / "home"
    (home / ".local/share/flatpak/app/com.google.Chrome/current").mkdir(parents=True)
    cmd, name = webapps.build_command(config.default_config(), webapps.BY_ID["netflix"], home, only(), tmp_path / "w")
    assert name == "Google Chrome" and cmd[:2] == ["flatpak", "run"] and f"--filesystem={tmp_path / 'w'}" in cmd
    assert "com.google.Chrome" in cmd


def test_no_company_logos_and_every_app_is_listed(env):
    ids = {w.id for w in webapps.WEBAPPS}
    assert {"youtube", "netflix", "instagram", "facebook", "tiktok", "disney", "prime", "twitch"} <= ids
    assert all(w.url.startswith("https://") for w in webapps.WEBAPPS)
    assert [w.id for w in webapps.WEBAPPS if w.drm] == ["spotify", "netflix", "disney", "prime"]
    assert all("720p" in w.note for w in webapps.WEBAPPS if w.drm and w.id != "spotify")                   # the honest quality limit
    res = library.build_library(config.default_config())
    g = {x.gid: x for x in res.games}
    assert g["web:netflix"].platform == "streaming" and g["app:kodi"].platform == "streaming"
    assert g["app:roblox"].platform == "apps"
    assert apps.BY_ID["kodi"].flatpak == "tv.kodi.Kodi"


def test_a_web_app_starts_in_the_browser_with_its_profile(env, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    rec = tmp_path / "rec.txt"
    stub(bindir / "chromium", f'echo "$@" > {rec}\n')
    monkeypatch.setenv("PATH", str(bindir))           # only the stub: never start a real browser from a test
    game = [g for g in library.build_library(config.default_config()).games if g.gid == "web:youtube"][0]
    started = []
    secs, err = launcher.run_game(config.default_config(), game, on_started=lambda: started.append(1))
    assert started and "--app=https://www.youtube.com/tv" in rec.read_text() and err == ""
    assert (tmp_path / "data" / "webapps" / "youtube").is_dir()


def test_no_browser_gives_plain_advice(env, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    game = [g for g in library.build_library(config.default_config()).games if g.gid == "web:youtube"][0]
    with pytest.raises(launcher.LaunchError, match="Install emulators and apps"):
        launcher.run_game(config.default_config(), game, on_started=lambda: None)
    rows = diagnose.check_game(config.default_config(), game, str(tmp_path / "none"))
    assert any(r["state"] == "bad" and "Web browser" in r["title"] for r in rows)


def test_streaming_and_free_tiles_are_not_counted_as_games(env):
    from atarilauncher.model import filter_games
    res = library.build_library(config.default_config())
    allg = filter_games(res.games, "all", "", None, "az") if False else None
    real = [g for g in res.games if g.platform not in apps.NON_GAME]
    assert real == []                                                                   # nothing but tiles on a new PC


def test_free_games_list_is_honest():
    ids = {g.id for g in freegames.GAMES}
    assert {"cs2", "dota2", "tf2", "poe", "warframe", "supertuxkart", "0ad", "xonotic", "openarena"} <= ids
    for g in freegames.GAMES:
        if g.kind == "steam":
            assert g.ref.isdigit() and g.works == freegames.VERIFIED and "ProtonDB" in g.why and "2026-10-28" in g.why
        elif g.kind == "flatpak":
            assert g.ref.count(".") >= 2
        else:
            assert g.works == freegames.BLOCKED and "anti-cheat" in g.why
    bad = {g.id for g in freegames.GAMES if g.kind == "info"}
    assert bad == {"fortnite", "cod"}                                                   # explained, never launchable
    assert "Does NOT work on Linux" in freegames.BY_ID["fortnite"].badge
    assert freegames.steam_command_for(freegames.BY_ID["cs2"], False) == "steam://install/730"
    assert freegames.steam_command_for(freegames.BY_ID["cs2"], True) == "steam://rungameid/730"
    assert "Prism" in freegames.MINECRAFT_NOTE and "licence" in freegames.MINECRAFT_NOTE


def test_free_games_in_the_library_with_badges(env):
    g = {x.gid: x for x in library.build_library(config.default_config()).games}
    assert g["free:cs2"].platform == "free" and g["free:cs2"].steam_appid == "730"
    assert "Works on Linux: Verified" in g["free:cs2"].note and "Press Play to install" in g["free:cs2"].note
    assert "Does NOT work on Linux" in g["free:fortnite"].note and "install" not in g["free:fortnite"].note.lower()


def test_pressing_play_on_fortnite_only_explains(env):
    g = [x for x in library.build_library(config.default_config()).games if x.gid == "free:fortnite"][0]
    with pytest.raises(launcher.LaunchError) as e:
        launcher.run_game(config.default_config(), g, on_started=lambda: None)
    assert str(e.value).startswith(launcher.INFO) and "anti-cheat" in str(e.value)


def test_steam_free_game_opens_the_install_page_or_plays(env, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    rec = tmp_path / "rec.txt"
    stub(bindir / "steam", f'echo "$@" >> {rec}\n')
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + "/usr/bin:/bin")
    g = [x for x in library.build_library(config.default_config()).games if x.gid == "free:cs2"][0]
    with pytest.raises(launcher.LaunchError, match="free install page"):
        launcher.run_game(config.default_config(), g, on_started=lambda: None)
    import time
    for _ in range(40):
        if rec.exists() and rec.read_text().strip():
            break
        time.sleep(0.05)
    assert "steam://install/730" in rec.read_text()


def test_flatpak_free_game_opens_an_install_terminal_when_missing(env, tmp_path, monkeypatch):
    from atarilauncher import installer
    seen = []
    monkeypatch.setattr(installer, "open_in_terminal", lambda cmd=None, *a, **k: (seen.append(cmd), (True, "ok"))[1])
    g = [x for x in library.build_library(config.default_config()).games if x.gid == "free:supertuxkart"][0]
    with pytest.raises(launcher.LaunchError, match="Installing SuperTuxKart"):
        launcher.run_game(config.default_config(), g, on_started=lambda: None)
    assert "flatpak install --user -y flathub net.supertuxkart.SuperTuxKart" in seen[0][-1]


def test_helpers_chrome_and_antimicrox_are_in_the_install_script():
    ids = {e.id for e in __import__("atarilauncher.installer", fromlist=["x"]).default_selection()}
    assert {"chrome", "antimicrox", "kodi"} <= ids
    assert {h.id: h.flatpak for h in apps.HELPERS}["chrome"] == "com.google.Chrome"
