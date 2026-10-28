"""Built-in web browser tile, the Downloads page (finished files -> my games) and the Transmission torrent client."""
import os
import time
from pathlib import Path

import pytest

from atarilauncher import apps, appinstall, downloads, importer, webapps
from atarilauncher.config import default_config


def put(path: Path, data=b"x" * 10, age=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    t = time.time() - age
    os.utime(path, (t, t))
    return path


# ------------------------------------------------------------------ the browser tile
def which_only(*names):
    return lambda exe: f"/usr/bin/{exe}" if exe in names else None


def test_browser_tile_is_a_normal_window_with_an_address_bar_and_a_neutral_start_page(tmp_path):
    w = webapps.BY_ID["browser"]
    assert w.browse and w.url == "https://duckduckgo.com/" and w.gid == "web:browser"
    cmd, name = webapps.build_command(default_config(), w, tmp_path, which_only("chromium"), root=tmp_path / "p")
    assert name == "Chromium" and cmd[0] == "chromium"
    assert "--new-window" in cmd and "--start-maximized" in cmd and w.url in cmd
    assert not any(a.startswith("--app=") or a == "--start-fullscreen" for a in cmd)        # app mode would hide the address bar
    assert f"--user-data-dir={tmp_path / 'p' / 'browser'}" in cmd
    cmd, name = webapps.build_command(default_config(), w, tmp_path, which_only("firefox"), root=tmp_path / "p")
    assert cmd[0] == "firefox" and "--kiosk" not in cmd and cmd[-1] == w.url
    # the streaming apps are unchanged
    cmd, _ = webapps.build_command(default_config(), webapps.BY_ID["youtube"], tmp_path, which_only("chromium"), root=tmp_path / "p")
    assert any(a.startswith("--app=") for a in cmd) and "--start-fullscreen" in cmd


def test_no_download_site_is_curated_anywhere():
    text = " ".join(open(f).read().lower() for f in
                    (downloads.__file__, webapps.__file__, apps.__file__))
    for bad in ("rom site", "romsmania", "emuparadise", "coolrom", "romsgames", "vimm", "the pirate bay", "piratebay", "1337x",
                "nyaa", "rarbg", "magnet:?"):
        assert bad not in text, bad
    assert all(not (w.browse and "rom" in w.url) for w in webapps.WEBAPPS)


# ------------------------------------------------------------------ the downloads list
def test_scan_lists_newest_first_partials_on_top_and_guesses_the_system(tmp_path):
    cfg = default_config()
    d = tmp_path / "Downloads"
    put(d / "old.zip", age=5000)
    put(d / "Mario.nes", age=100)
    put(d / "Movie.mp4.crdownload", b"y" * 99, age=10)
    put(d / "game.iso.part", age=1)
    put(d / ".hidden", age=1)
    put(d / "x.torrent", age=50)
    (d / "Folder").mkdir()
    put(d / "Folder" / "disc.bin")
    items = downloads.scan(cfg, tmp_path)
    names = [i.name for i in items]
    assert names[:2] == ["game.iso.part", "Movie.mp4.crdownload"] or names[:2] == ["Movie.mp4.crdownload", "game.iso.part"]
    assert ".hidden" not in names and "Mario.nes" in names
    mario = next(i for i in items if i.name == "Mario.nes")
    assert "nes" in mario.guess and not mario.partial
    movie = next(i for i in items if i.name.startswith("Movie"))
    assert movie.partial and movie.shown_name == "Movie.mp4" and movie.size == 99
    assert next(i for i in items if i.name == "x.torrent").is_torrent
    folder = next(i for i in items if i.name == "Folder")
    assert folder.is_dir and not folder.partial
    assert downloads.scan(cfg, tmp_path / "nowhere") == []


def test_a_torrent_folder_with_unfinished_part_files_is_still_arriving(tmp_path):
    d = tmp_path / "Downloads" / "Big"
    put(d / "a.bin", b"1" * 5)
    put(d / "b.bin.part", b"2" * 7)
    size, partial = downloads.folder_info(d)
    assert partial and size == 12


def test_add_to_games_moves_the_file_into_the_system_folder_and_never_overwrites(tmp_path):
    cfg = default_config()
    f = put(tmp_path / "Downloads" / "Mario.nes")
    ok, text, target = downloads.add_to_games(cfg, f, "nes", tmp_path)
    assert ok and target == tmp_path / "Games" / "Atari" / "nes" / "Mario.nes" and target.exists() and not f.exists()
    assert (tmp_path / "Games" / "Code").is_symlink() and (tmp_path / "Games" / "Code" / "nes" / "Mario.nes").exists()   # ~/Games/Code works too
    again = put(tmp_path / "Downloads" / "Mario.nes", b"other")
    ok, _t, t2 = downloads.add_to_games(cfg, again, "nes", tmp_path)
    assert ok and t2.name == "Mario (2).nes" and target.read_bytes() == b"x" * 10


def test_add_to_games_refuses_unfinished_missing_unknown_system_and_moves_folders(tmp_path):
    cfg = default_config()
    p = put(tmp_path / "Downloads" / "a.nes.crdownload")
    assert downloads.add_to_games(cfg, p, "nes", tmp_path)[0] is False and p.exists()
    assert downloads.add_to_games(cfg, tmp_path / "gone.nes", "nes", tmp_path)[0] is False
    q = put(tmp_path / "Downloads" / "b.nes")
    ok, text, _ = downloads.add_to_games(cfg, q, "no-such-system", tmp_path)
    assert not ok and "system" in text and q.exists()
    d = tmp_path / "Downloads" / "Disc"
    put(d / "g.cue")
    ok, _t, t = downloads.add_to_games(cfg, d, "ps1", tmp_path)
    assert ok and (t / "g.cue").exists() and not d.exists()
    d2 = tmp_path / "Downloads" / "Disc"
    put(d2 / "h.cue")
    ok, _t, t2 = downloads.add_to_games(cfg, d2, "ps1", tmp_path)
    assert ok and t2.name == "Disc (2)"


def test_a_configured_rom_folder_wins_over_the_default(tmp_path):
    cfg = default_config()
    cfg.systems["nes"].roms = [str(tmp_path / "MyNes")]
    f = put(tmp_path / "Downloads" / "z.nes")
    ok, _t, t = downloads.add_to_games(cfg, f, "nes", tmp_path)
    assert ok and t == tmp_path / "MyNes" / "z.nes"


def test_candidates_put_the_likely_systems_first_and_list_all(tmp_path):
    cfg = default_config()
    it = downloads.Item(Path("a.nes"), 1, 0, guess=["nes"])
    c = downloads.candidates(cfg, it)
    assert c[0][0] == "nes" and len(c) == len(cfg.systems) and len({s for s, _n in c}) == len(c)


# ------------------------------------------------------------------ torrent client
def test_transmission_is_a_normal_one_button_install_app_with_a_tile():
    a = apps.BY_ID["transmission"]
    assert a.flatpak == "com.transmissionbt.Transmission" and a.apt == "transmission-gtk" and a.group == "apps"
    t = appinstall.TARGETS["transmission"]
    assert t is not None
    assert "does not preload" in a.note.lower() or "does not preload" in a.note
    cmd, how = apps.app_command(default_config(), a, which=which_only("transmission-gtk"))
    assert cmd == ["transmission-gtk"] and how == "native"


def test_open_torrent_starts_the_client_with_the_file_and_explains_when_missing(tmp_path):
    calls = []
    cfg = default_config()
    ok, text = downloads.open_torrent(cfg, tmp_path / "x.torrent", tmp_path, which_only("transmission-gtk"),
                                      lambda cmd, **kw: calls.append((cmd, kw)))
    assert ok and calls[0][0] == ["transmission-gtk", str(tmp_path / "x.torrent")] and calls[0][1]["start_new_session"]
    ok, text = downloads.open_torrent(cfg, None, tmp_path, which_only("transmission-qt"), lambda cmd, **kw: calls.append((cmd, kw)))
    assert ok and calls[1][0] == ["transmission-qt"]
    ok, text = downloads.open_torrent(cfg, None, tmp_path, lambda e: None, lambda *a, **k: calls.append(1))
    assert not ok and "not installed" in text and len(calls) == 2

    def boom(*a, **k):
        raise OSError(2, "No such file")
    ok, text = downloads.open_torrent(cfg, None, tmp_path, which_only("transmission-gtk"), boom)
    assert not ok and "No such file" in text


# ------------------------------------------------------------------ the pages
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


def titles(rows):
    return [r.get("title", "") for r in rows]


def test_downloads_page_shows_files_and_choosing_one_then_a_system_moves_it(be_, tmp_path):
    put(tmp_path / "Downloads" / "Mario.nes")
    put(tmp_path / "Downloads" / "video.mp4.crdownload", b"z" * 2048)
    rows = be_.pageRows("downloads")
    t = titles(rows)
    assert "Open the web browser" in t and "Torrent client (Transmission)" in t and "Refresh the list" in t
    assert "Mario.nes" in t and "video.mp4" in t
    mario = next(r for r in rows if r.get("title") == "Mario.nes")
    assert "Looks like" in mario["detail"] and "add it to my games" in mario["detail"]
    part = next(r for r in rows if r.get("title") == "video.mp4")
    assert part["value"].startswith("Downloading")
    assert be_.pageActivate("downloads", part["id"]) == "refresh"                          # not movable yet
    assert (tmp_path / "Downloads" / "video.mp4.crdownload").exists()
    assert be_.pageActivate("downloads", mario["id"]) == "page:dlsystem"
    srows = be_.pageRows("dlsystem")
    likely = [r for r in srows if r.get("value") == "Likely"]
    assert likely and likely[0]["id"] == "dlsys:nes" and srows[1]["id"] == "dlsys:nes"     # likely system first
    assert be_.pageActivate("dlsystem", "dlsys:nes") == "page:downloads"
    assert (tmp_path / "Games" / "Atari" / "nes" / "Mario.nes").exists()
    assert not (tmp_path / "Downloads" / "Mario.nes").exists()
    assert any("It is in your games now" in r.get("title", "") for r in be_.pageRows("downloads"))
    assert be_.pageTitle("downloads") == "DOWNLOADS" and be_.pageSub("dlsystem")


def test_empty_downloads_says_so_and_add_games_and_the_menu_lead_to_it(be_, tmp_path):
    assert any("Nothing in your Downloads" in t for t in titles(be_.pageRows("downloads")))
    assert be_.pageActivate("addgames", "downloads") == "page:downloads"
    assert any(r.get("id") == "downloads" for r in be_.pageRows("addgames"))
    qml = (Path(importer.__file__).parent / "qml" / "Main.qml").read_text()
    assert 'id: "downloads"' in qml and 'openPage("downloads")' in qml


def test_a_torrent_file_opens_in_the_client_and_the_install_button_works_when_missing(be_, tmp_path, monkeypatch):
    put(tmp_path / "Downloads" / "thing.torrent")
    opened, installs = [], []
    monkeypatch.setattr(downloads, "open_torrent", lambda cfg, path=None, **k: (opened.append(path) or (True, "ok")))
    row = next(r for r in be_.pageRows("downloads") if r.get("title") == "thing.torrent")
    assert row["value"] == "Torrent"
    assert be_.pageActivate("downloads", row["id"]) == "" and opened == [tmp_path / "Downloads" / "thing.torrent"]
    tile = next(g for g in be_._all if g.gid == "app:transmission")
    tile.missing = True
    monkeypatch.setattr(be_, "begin_install", lambda specs, **kw: installs.append((specs, kw)))
    assert be_.pageActivate("downloads", "dltorrent") == "" and installs[0][0] == ["transmission"]
    tile.missing = False
    assert be_.pageActivate("downloads", "dltorrent") == "" and opened[-1] is None
    monkeypatch.setattr(downloads, "open_torrent", lambda cfg, path=None, **k: (False, "Transmission (torrent client) is not installed yet."))
    assert be_.pageActivate("downloads", row["id"]) == "" and len(installs) == 2          # a missing client offers the install
