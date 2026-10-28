"""BandLab (web music studio): a Studio-area tile that opens in its own browser window, keeps its login, allows the microphone."""
from pathlib import Path

from atarilauncher import icons, launcher, library, webapps
from atarilauncher.config import default_config

only = lambda *names: (lambda exe: f"/usr/bin/{exe}" if exe in names else None)  # noqa: E731


def games():
    cfg = default_config()
    cfg.steam_enabled = False
    return {g.gid: g for g in library.build_library(cfg, metadata={}).games}


def test_bandlab_tile_sits_in_the_studio_area_next_to_the_built_in_studio():
    g = games()
    b = g["web:bandlab"]
    assert (b.platform, b.platform_name) == ("studio", "Studio") == (g["studio:open"].platform, g["studio:open"].platform_name)
    assert "bandlab.com" in webapps.BY_ID["bandlab"].url and "Esc twice" in b.note
    assert not any(x.gid == "web:bandlab" and x.platform == webapps.STREAMING for x in g.values())
    assert sum(1 for x in library.build_library(default_config(), metadata={}).games if x.gid == "web:bandlab") == 1


def test_bandlab_is_not_counted_as_a_game():
    from atarilauncher import apps
    assert "studio" in apps.NON_GAME


def test_chromium_window_has_its_own_profile_and_the_microphone_allowed(tmp_path):
    cmd, name = webapps.build_command(None, webapps.BY_ID["bandlab"], which=only("google-chrome-stable"), root=tmp_path)
    assert name == "Google Chrome"
    assert "--app=https://www.bandlab.com/studio" in cmd and "--start-fullscreen" in cmd
    assert f"--user-data-dir={tmp_path / 'bandlab'}" in cmd             # login is remembered in this private profile
    assert webapps.MIC_FLAG in cmd


def test_other_web_apps_do_not_get_the_microphone_flag(tmp_path):
    for wid in ("youtube", "netflix", "spotify", "browser"):
        cmd, _ = webapps.build_command(None, webapps.BY_ID[wid], which=only("google-chrome-stable"), root=tmp_path)
        assert webapps.MIC_FLAG not in cmd, wid


def test_firefox_gets_a_user_js_with_the_microphone_pref_once(tmp_path):
    app = webapps.BY_ID["bandlab"]
    cmd, name = webapps.build_command(None, app, which=only("firefox"), root=tmp_path)
    assert name == "Firefox" and "--kiosk" in cmd and cmd[-1] == app.url
    prof = tmp_path / "bandlab"
    webapps.prepare_profile(app, prof)
    webapps.prepare_profile(app, prof)
    text = (prof / "user.js").read_text()
    assert text.count("media.navigator.permission.disabled") == 1
    webapps.prepare_profile(webapps.BY_ID["youtube"], tmp_path / "youtube")
    assert not (tmp_path / "youtube").exists()


def test_flatpak_browser_is_given_the_profile_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(webapps.emulators, "flatpak_installed", lambda fid, home=None: fid == "com.google.Chrome")
    cmd, _ = webapps.build_command(None, webapps.BY_ID["bandlab"], which=only(), root=tmp_path)
    assert cmd[:3] == ["flatpak", "run", f"--filesystem={tmp_path}"] and webapps.MIC_FLAG in cmd


def test_no_browser_gives_the_install_help_and_a_chrome_install_offer():
    ok, text = webapps.status(None, webapps.BY_ID["bandlab"], which=only(), home=Path("/nonexistent"))
    assert not ok and text == webapps.HELP_TEXT


def test_launching_the_tile_starts_the_browser_in_its_own_session_with_the_exit_hint(monkeypatch, tmp_path):
    seen = {}

    class P:
        def wait(self):
            return 0

    def popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return P()
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(launcher, "_check_executable", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "_start_watch", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "_hint_delay", lambda: 0)
    monkeypatch.setattr(launcher, "clean_env", lambda: {})
    monkeypatch.setattr(webapps, "find_browser", lambda *a, **k: (webapps.BROWSERS[0], "native"))
    monkeypatch.setattr(webapps.shutil, "which", only("google-chrome-stable"))
    g = games()["web:bandlab"]
    started = []
    launcher.run_game(default_config(), g, lambda: started.append(1))
    assert started and seen["kw"]["start_new_session"] is True
    assert "--app=https://www.bandlab.com/studio" in seen["cmd"] and webapps.MIC_FLAG in seen["cmd"]
    assert (tmp_path / "webapps" / "bandlab").is_dir()
    assert "Esc" in launcher.controls_hint(default_config(), g)       # the "how to come back" hint shows for Studio-area web apps too


def test_icon_is_fetched_at_runtime_with_a_coloured_initial_fallback_and_nothing_is_bundled():
    spec = icons.spec_for("web:bandlab")
    assert spec is not None and spec.site == "https://www.bandlab.com/studio" and spec.kind == "web"
    assert games()["web:bandlab"].cover == ""                        # offline / not fetched yet: the tile draws its initial
    root = Path(__file__).resolve().parents[1] / "atarilauncher"
    assert not [p for p in root.rglob("*") if "bandlab" in p.name.lower()]
