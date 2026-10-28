"""Go Live: OBS install tile, the ready-made scene, the Twitch / TikTok / YouTube dashboards in the browser, honest TikTok text."""
import json
from pathlib import Path

import pytest

from atarilauncher import apps, appinstall, golive, icons, webapps
from atarilauncher.config import default_config


def which_only(*names):
    return lambda exe: f"/usr/bin/{exe}" if exe in names else None


def test_obs_is_a_one_button_install_app():
    a = apps.BY_ID["obs"]
    assert a.flatpak == "com.obsproject.Studio" and a.apt == "obs-studio" and a.group == "apps"
    assert appinstall.TARGETS["obs"] is not None
    assert "Game Capture" in a.note                                           # the Linux limit is stated on the tile
    spec = icons.spec_for("app:obs")
    assert spec is not None and spec.flatpak == "com.obsproject.Studio"      # icon comes from Flathub at runtime


def test_the_three_dashboards_open_in_the_browser_window_with_runtime_icons_and_no_bundled_logo():
    for wid, host in (("twitchlive", "dashboard.twitch.tv"), ("tiktoklive", "www.tiktok.com"), ("youtubelive", "studio.youtube.com")):
        w = webapps.BY_ID[wid]
        assert w.browse and w.url.startswith("https://" + host) and not w.drm
        s = icons.spec_for(w.gid)
        assert s and s.kind == "web" and s.site == w.url                      # favicon is fetched when the app runs
    assert "Windows-only" in webapps.BY_ID["tiktoklive"].note
    shipped = [p.name.lower() for p in (Path(golive.__file__).parent / "assets").rglob("*") if p.is_file()]
    assert not any(x in n for n in shipped for x in ("twitch", "tiktok", "youtube", "obs"))


def test_scene_collection_matches_the_session_and_is_valid_json():
    x = golive.scene_collection("x11")
    w = golive.scene_collection("wayland")
    assert x["name"] == "Code Go Live" and x["current_scene"] == "Game" and x["scene_order"] == [{"name": "Game"}]
    assert [s["id"] for s in x["sources"]] == ["scene", "xshm_input"]
    assert [s["id"] for s in w["sources"]] == ["scene", "pipewire-screen-capture-source"]
    item = x["sources"][0]["settings"]["items"][0]
    assert item["name"] == x["sources"][1]["name"] and item["source_uuid"] == x["sources"][1]["uuid"] and item["visible"]
    assert json.loads(json.dumps(x)) == x
    assert "game_capture" not in json.dumps(x)                               # Windows-only source is never used


def test_ensure_scene_writes_once_in_the_right_obs_folder_and_never_overwrites(tmp_path):
    f, new = golive.ensure_scene("native", tmp_path, "x11")
    assert new and f == tmp_path / ".config/obs-studio/basic/scenes/Code_Go_Live.json"
    assert json.loads(f.read_text())["name"] == "Code Go Live"
    f.write_text("mine")
    f2, new2 = golive.ensure_scene("native", tmp_path, "x11")
    assert f2 == f and not new2 and f.read_text() == "mine"
    fl, newf = golive.ensure_scene("flatpak", tmp_path, "wayland")
    assert newf and ".var/app/com.obsproject.Studio/config/obs-studio/basic/scenes" in str(fl)


def test_start_obs_opens_it_with_the_scene_and_never_stores_a_key(tmp_path):
    calls = []
    ok, text = golive.start_obs(default_config(), tmp_path, which_only("obs"), lambda c, **k: calls.append((c, k)), "x11")
    assert ok and calls[0][0] == ["obs", "--collection", "Code Go Live", "--scene", "Game", "--disable-shutdown-check"]
    assert calls[0][1]["start_new_session"] and "stream key" in text and "password" in text
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert "stream_key" not in f.read_text().lower() and '"key"' not in f.read_text().lower()


def test_start_obs_when_missing_or_failing_is_explained(tmp_path):
    ok, text = golive.start_obs(default_config(), tmp_path, lambda e: None, lambda *a, **k: 1 / 0, "x11")
    assert not ok and "not installed" in text

    def boom(*a, **k):
        raise OSError(2, "No such file")
    ok, text = golive.start_obs(default_config(), tmp_path, which_only("obs"), boom, "x11")
    assert not ok and "No such file" in text


def test_tiktok_text_is_honest_about_windows_only_and_who_gets_a_key():
    t = golive.TIKTOK_TEXT
    assert "Windows" in t and "Linux" in t and "OBS" in t and "qualify" in t and "stream key" in t


# ------------------------------------------------------------------ the page
@pytest.fixture
def be_(tmp_path, monkeypatch, _qt_app):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ATARI_NO_WIFI", "1")
    from atarilauncher import backend as be
    from atarilauncher.store import Store
    cfg = default_config()
    cfg.steam_enabled = False
    cfg.first_run = False
    return be.Backend(cfg=cfg, store=Store(tmp_path / "s.json"), enable_gamepad=False)


def test_go_live_page_offers_install_then_open_and_the_three_dashboards(be_, monkeypatch):
    monkeypatch.setattr(apps, "app_status", lambda cfg, app, *a, **k: (False, "x"))
    rows = be_.pageRows("golive")
    ids = [r.get("id") for r in rows]
    assert "obsinstall" in ids and {"go:web:twitchlive", "go:web:tiktoklive", "go:web:youtubelive"} <= set(ids) and "recordings" in ids
    text = " ".join(r.get("title", "") for r in rows)
    assert "Windows / Mac" in text and "stream key" in text and "F9" in text and "Game Capture" in text
    installs = []
    monkeypatch.setattr(be_, "begin_install", lambda specs, **kw: installs.append(specs))
    assert be_.pageActivate("golive", "obsinstall") == "" and installs == [["obs"]]
    monkeypatch.setattr(apps, "app_status", lambda cfg, app, *a, **k: (True, "OBS"))
    assert "obsopen" in [r.get("id") for r in be_.pageRows("golive")]
    opened = []
    monkeypatch.setattr(golive, "start_obs", lambda cfg, **k: (opened.append(1) or (True, "ok")))
    assert be_.pageActivate("golive", "obsopen") == "" and opened
    launched = []
    monkeypatch.setattr(be_, "_launch_game", lambda g: launched.append(g.gid))
    assert be_.pageActivate("golive", "go:web:tiktoklive") == "close" and launched == ["web:tiktoklive"]
    assert be_.pageActivate("golive", "recordings") == "page:recordings"
    assert be_.pageTitle("golive") == "GO LIVE"


def test_the_options_menu_leads_to_go_live():
    qml = (Path(golive.__file__).parent / "qml" / "Main.qml").read_text()
    assert 'id: "golive"' in qml and 'openPage("golive")' in qml
