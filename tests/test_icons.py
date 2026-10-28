"""Runtime icons for app tiles: installed icon first, then the download cache, then the coloured-initial fallback. Fake HTTP only."""
import os
import struct
import time
from pathlib import Path

import pytest

from atarilauncher import apps, config, covers, icons, library
from tests.fakeserver import JPG, PNG, Fake


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.stop()


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))


def fetcher(fake, tmp_path, **kw):
    return icons.IconFetcher(covers.Http(timeout=3, pause=0, backoff=0.01), tmp_path / "icons", fake.url + "/flathub", fake.url + "/steam", **kw)


BIG = PNG + b"\0" * 300          # the fake pictures are tiny: pad them over the 200-byte sanity floor


def page(fake, links, path="/"):
    fake.files[path] = ("<html><head>" + links + "</head><body>x</body></html>").encode()


def test_page_icons_prefers_big_touch_icons_then_png_then_svg():
    html = ('<link rel="icon" href="/f16.png" sizes="16x16"><link rel="shortcut icon" href="/favicon.ico">'
            "<link rel='apple-touch-icon' sizes='180x180' href='/t180.png'><link rel=\"icon\" href=\"/a.svg\" sizes=\"any\">"
            '<link rel="mask-icon" href="/mask.svg"><link rel="stylesheet" href="/x.css">')
    got = icons.page_icons(html, "https://example.com/start")
    assert got[0] == "https://example.com/t180.png" and "https://example.com/mask.svg" not in got and "https://example.com/x.css" not in got
    assert got.index("https://example.com/a.svg") < got.index("https://example.com/favicon.ico")


def test_web_app_icon_is_downloaded_once_and_cached(fake, tmp_path):
    page(fake, '<link rel="apple-touch-icon" sizes="180x180" href="/img/touch.png"><link rel="icon" href="/fav.ico">')
    fake.files["/img/touch.png"] = BIG
    spec = icons.Spec("web:youtube", "YouTube", site=fake.url + "/", kind="web")
    got = []
    rep = fetcher(fake, tmp_path).run([spec], on_icon=lambda s, p: got.append(p), home=tmp_path)
    assert rep["got"] == 1 and got == [str(tmp_path / "icons" / "web_youtube.png")]
    assert Path(got[0]).read_bytes() == BIG
    assert icons.cached("web:youtube", tmp_path / "icons") == got[0]
    n = len(fake.hits)
    rep = fetcher(fake, tmp_path).run([spec], home=tmp_path)                       # cached: not a single request
    assert rep["skipped"] == 1 and len(fake.hits) == n
    assert fake.ua_seen and all("Code-Launcher" in u for u in fake.ua_seen)                 # an honest User-Agent


def test_favicon_fallbacks_when_the_page_names_no_icon(fake, tmp_path):
    page(fake, "")
    fake.files["/apple-touch-icon.png"] = BIG
    spec = icons.Spec("web:netflix", "Netflix", site=fake.url + "/", kind="web")
    assert fetcher(fake, tmp_path).run([spec], home=tmp_path)["got"] == 1


def test_ico_is_converted_to_png_when_qt_can_else_kept(fake, tmp_path):
    ico = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 2, 3, 0, 0, 1, 32, len(PNG), 22) + PNG
    assert icons.sniff_ext(ico) == "ico"
    page(fake, "")
    fake.files["/favicon.ico"] = ico + b"\0" * 300
    spec = icons.Spec("web:tiktok", "TikTok", site=fake.url + "/", kind="web")
    assert fetcher(fake, tmp_path).run([spec], home=tmp_path)["got"] == 1
    assert icons.cached("web:tiktok", tmp_path / "icons").rsplit(".", 1)[1] in ("png", "ico")


def test_flatpak_icon_comes_from_flathub_and_steam_art_from_the_steam_cdn(fake, tmp_path):
    fake.files["/flathub/tv.kodi.Kodi.png"] = BIG
    fake.files["/steam/730/header.jpg"] = JPG + b"\0" * 300           # (no tall capsule for this one: the next name is used)
    specs = [icons.Spec("app:kodi", "Kodi", flatpak="tv.kodi.Kodi"), icons.Spec("free:cs2", "Counter-Strike 2", steam_appid="730", kind="free")]
    rep = fetcher(fake, tmp_path).run(specs, home=tmp_path)
    assert rep["got"] == 2
    assert icons.cached("app:kodi", tmp_path / "icons").endswith("app_kodi.png")
    assert icons.cached("free:cs2", tmp_path / "icons").endswith("free_cs2.jpg")
    assert "/steam/730/library_600x900.jpg" in fake.hits and "/steam/730/header.jpg" in fake.hits


def test_nothing_found_is_remembered_then_retried_later(fake, tmp_path):
    page(fake, "")
    spec = icons.Spec("web:twitch", "Twitch", site=fake.url + "/", kind="web")
    assert fetcher(fake, tmp_path).run([spec], home=tmp_path)["missing"] == 1
    n = len(fake.hits)
    assert fetcher(fake, tmp_path).run([spec], home=tmp_path)["missing"] == 1 and len(fake.hits) == n
    fake.files["/apple-touch-icon.png"] = BIG
    later = fetcher(fake, tmp_path, now=lambda: time.time() + 5 * 86400)
    assert later.run([spec], home=tmp_path)["got"] == 1


def test_offline_stops_quickly_and_leaves_the_fallback(tmp_path):
    dead = icons.IconFetcher(covers.Http(timeout=1, retries=1, pause=0, backoff=0.01), tmp_path / "icons",
                             "http://127.0.0.1:9/f", "http://127.0.0.1:9/s")
    specs = [icons.Spec(f"app:x{i}", "X", flatpak=f"a.b.C{i}") for i in range(6)]
    rep = dead.run(specs, home=tmp_path)
    assert rep["offline"] and rep["got"] == 0
    assert not any(Path(tmp_path / "icons").glob("*.png"))


# ------------------------------------------------------------------ icons that are already installed
def test_installed_flatpak_icon_beats_the_cache(fake, tmp_path):
    home = tmp_path / "home"
    d = home / ".local/share/flatpak/exports/share/icons/hicolor/128x128/apps"
    d.mkdir(parents=True)
    (d / "tv.kodi.Kodi.png").write_bytes(BIG)
    spec = icons.Spec("app:kodi", "Kodi", flatpak="tv.kodi.Kodi")
    assert icons.local_icon(spec, home) == str(d / "tv.kodi.Kodi.png")
    assert icons.resolve(spec, home, tmp_path / "icons") == (str(d / "tv.kodi.Kodi.png"), True)
    assert fetcher(fake, tmp_path).run([spec], home=home)["skipped"] == 1 and fake.hits == []


def test_native_app_icon_found_through_its_desktop_file(tmp_path):
    home = tmp_path / "home"
    (home / ".local/share/applications").mkdir(parents=True)
    (home / ".local/share/applications/kodi.desktop").write_text("[Desktop Entry]\nName=Kodi\nExec=kodi %U\nIcon=kodi\n")
    ic = home / ".local/share/icons/hicolor/256x256/apps"
    ic.mkdir(parents=True)
    (ic / "kodi.png").write_bytes(BIG)
    assert icons.local_icon(icons.Spec("app:kodi", "Kodi", exes=("kodi",)), home) == str(ic / "kodi.png")
    (home / ".local/share/applications/other.desktop").write_text("[Desktop Entry]\nExec=/opt/foo/bar --x\nIcon=/abs/pic.png\n")
    assert icons.local_icon(icons.Spec("app:zzz", "Z", exes=("nothing",)), home) == ""


# ------------------------------------------------------------------ the library and the screen
def test_every_streaming_app_and_free_game_tile_has_an_icon_recipe():
    from atarilauncher import freegames, webapps
    for w in webapps.WEBAPPS:
        s = icons.spec_for(w.gid)
        assert s and s.site.startswith("https://") and s.kind == "web"
    for a in apps.APP_DEFS:
        if a.flatpak or a.id in icons.APP_SITES:
            assert icons.spec_for(a.gid), a.id
    for g in freegames.GAMES:
        assert (icons.spec_for(g.gid) is not None) == (g.kind in ("steam", "flatpak")), g.id
    assert icons.spec_for("studio:open") is None and icons.spec_for("tool:record") is None


def test_library_uses_cached_icons_and_marks_them_to_fit(tmp_path, monkeypatch):
    root = tmp_path / "data" / "icons"
    root.mkdir(parents=True)
    (root / "web_youtube.png").write_bytes(BIG)
    (root / "free_cs2.jpg").write_bytes(JPG + b"\0" * 300)
    cfg = config.default_config()
    cfg.steam_enabled = False
    res = library.build_library(cfg, home=tmp_path, metadata={})
    by = {g.gid: g for g in res.games}
    assert by["web:youtube"].cover == str(root / "web_youtube.png") and by["web:youtube"].fit
    assert by["free:cs2"].cover == str(root / "free_cs2.jpg") and not by["free:cs2"].fit      # real Steam art fills the tile
    assert by["web:netflix"].cover == "" and not by["web:netflix"].fit                         # offline / not fetched: coloured initials
    assert by["studio:open"].cover == ""


def test_cover_qml_draws_initials_when_there_is_no_icon():
    qml = (Path(__file__).resolve().parent.parent / "atarilauncher" / "qml" / "Cover.qml").read_text()
    assert "monogram" in qml and "Image.Ready" in qml and "cv.fit" in qml


def test_backend_downloads_icons_in_the_background_and_updates_the_tile(fake, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication
    from atarilauncher import backend as be
    from atarilauncher.store import Store
    app = QCoreApplication.instance() or QCoreApplication([])
    fake.files["/flathub/com.heroicgameslauncher.hgl.png"] = BIG
    monkeypatch.setenv("ATARI_ICONS_FLATHUB_URL", fake.url + "/flathub")
    monkeypatch.setenv("ATARI_ICONS_DIR", str(tmp_path / "ic"))
    monkeypatch.setenv("ATARI_COVERS_FAST", "1")
    monkeypatch.delenv("ATARI_NO_COVERS", raising=False)
    real = icons.spec_for
    monkeypatch.setattr(icons, "spec_for", lambda gid: real(gid) if gid == "app:heroic" else None)   # (never touch real websites)
    cfg = config.default_config()
    cfg.steam_enabled = False
    cfg.first_run = False
    b = be.Backend(cfg=cfg, store=Store(tmp_path / "s.json"), enable_gamepad=False)
    b.setFilter("all")
    b.startIcons()
    game = next(g for g in b._all if g.gid == "app:heroic")
    end = time.time() + 15
    while time.time() < end and not game.cover:
        app.processEvents()
        time.sleep(0.05)
    assert game.cover == str(tmp_path / "ic" / "app_heroic.png") and game.fit
