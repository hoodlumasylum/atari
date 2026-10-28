"""The file viewer shows every place (Downloads, Games folders and their console folders, Videos, BIOS / emulator / CodeAque folders),
with a breadcrumb, Up and All places on every folder, links to folders that open, and look-only BIOS folders."""
import os
from pathlib import Path

import pytest

from atarilauncher import files

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf  # noqa: E402
from tests.test_ui_keys import Ui, app  # noqa: E402,F401


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    for d in ("Downloads", "Games/Atari/xbox", "Games/Atari/snes", "Games/CodeAque/nes", "Videos",
              ".var/app/app.xemu.xemu/data/xemu/xemu", ".local/share/atari", ".config/retroarch/system"):
        (h / d).mkdir(parents=True)
    (h / ".var/app/app.xemu.xemu/data/xemu/xemu/Complex_4627v1.03.bin").write_bytes(b"\0" * 1000)
    (h / "Games/Atari/xbox/Game.iso").write_bytes(b"x" * 2000)
    (h / "Downloads/bios.zip").write_bytes(b"x" * 100)
    return h


def labels(pls):
    return [p.label for p in pls]


def test_places_lists_every_root_in_order(home):
    pl = files.places(home)
    got = labels(pl)
    assert got[:3] == ["Downloads", "Games", "Videos"]
    assert "Games / Atari" in got and "Games / CodeAque" in got
    assert "Games / Atari / xbox" in got and "Games / Atari / snes" in got and "Games / CodeAque / nes" in got
    assert any(l.startswith("BIOS / emulator: xemu") for l in got) and "CodeAque data (favourites, covers, logs)" in got
    assert any(l.startswith("BIOS / emulator: RetroArch") for l in got)
    groups = [p.group for p in pl]
    assert groups == sorted(groups, key=["main", "games", "system", "look"].index)           # grouped in the order shown
    assert all(p.writable for p in pl if p.group != "look") and not any(p.writable for p in pl if p.group == "look")
    xemu = next(p for p in pl if p.label.startswith("BIOS / emulator: xemu"))
    assert xemu.path == home / ".var/app/app.xemu.xemu/data/xemu/xemu" and xemu.count == 1


def test_a_folder_that_is_only_another_name_for_one_listed_is_not_doubled(home):
    (home / "Games/Code").symlink_to(home / "Games/Atari", target_is_directory=True)
    got = labels(files.places(home))
    assert "Games / Code" not in got and got.count("Games / Atari") == 1
    (home / "Games/Code").unlink()
    (home / "Games/Code").mkdir()
    assert "Games / Code" in labels(files.places(home))                                     # a real folder of its own is listed


def test_places_that_do_not_exist_are_left_out(tmp_path):
    h = tmp_path / "empty"
    h.mkdir()
    assert files.places(h) == []


def test_breadcrumb_starts_at_the_place_and_follows_the_folders(home):
    assert files.breadcrumb(home / "Downloads", home) == "Downloads"
    sub = home / "Downloads/a/b"
    sub.mkdir(parents=True)
    assert files.breadcrumb(sub, home) == "Downloads  >  a  >  b"
    assert files.breadcrumb(home / "Games/Atari/xbox", home) == "Games / Atari / xbox"
    assert files.breadcrumb(home / ".var/app/app.xemu.xemu/data/xemu/xemu", home).startswith("BIOS / emulator: xemu")
    assert files.breadcrumb(Path("/somewhere/else"), home) == "/somewhere/else"


def test_top_and_look_only_rules(home):
    assert files.is_top(home / "Downloads", home) and files.is_top(home / "Games", home)
    assert not files.is_top(home / "Games/Atari", home) and not files.is_top(home / "Games/Atari/xbox", home)
    xd = home / ".var/app/app.xemu.xemu/data/xemu/xemu"
    assert files.is_top(xd, home) and files.is_look_only(xd, home) and files.is_look_only(xd / "Complex_4627v1.03.bin", home)
    assert not files.is_look_only(home / "Downloads", home) and not files.is_look_only(home / "Games/Atari/xbox/Game.iso", home)
    ok, text = files.delete(xd / "Complex_4627v1.03.bin", home)
    assert not ok and (xd / "Complex_4627v1.03.bin").exists()                              # nothing in a look-only folder is ever deleted
    assert not files.rename(xd / "Complex_4627v1.03.bin", "x.bin", home)[0]


def test_links_to_folders_are_listed_and_open_but_cannot_be_used_to_change_outside(home, tmp_path):
    outside = tmp_path / "drive" / "Games"
    (outside / "psx").mkdir(parents=True)
    (outside / "psx" / "game.cue").write_text("x")
    (home / "Games/Atari/ps1link").symlink_to(outside, target_is_directory=True)
    entries, _ = files.list_dir(home / "Games/Atari")
    link = next(e for e in entries if e.name == "ps1link")
    assert link.is_dir and link.link and link.count == 1                                    # shown as a folder, not hidden
    assert [e.name for e in files.list_dir(home / "Games/Atari/ps1link")[0]] == ["psx"]       # and it opens
    assert not files.inside_roots(home / "Games/Atari/ps1link/psx/game.cue", home)
    assert not files.delete(home / "Games/Atari/ps1link/psx/game.cue", home)[0] and (outside / "psx/game.cue").exists()
    (home / "Games/Atari/broken").symlink_to(tmp_path / "gone", target_is_directory=True)
    assert "broken" not in [e.name for e in files.list_dir(home / "Games/Atari")[0]]       # a dead link is not shown


# ------------------------------------------------------------------ the screen
@pytest.fixture
def ui(app, tmp_path, monkeypatch, home):
    monkeypatch.setenv("HOME", str(home))
    conf(tmp_path)
    u = Ui(app, tmp_path, monkeypatch, config_exists=True, home=home)
    yield u
    u.close()


def sel(rows):
    return [r["id"] for r in rows if r.get("id")]


def test_place_list_has_every_group_with_headings(ui, home):
    b = ui.backend
    b.filesReset()
    rows = b.pageRows("files")
    text = " ".join(r["title"] for r in rows)
    for head in ("Main places:", "Games folders:", "Console folders inside your games folders:", "look only"):
        assert head in text
    titles = [r["title"] for r in rows if r.get("id", "").startswith("fmroot:")]
    assert "Games / Atari / xbox" in titles and any(t.startswith("BIOS / emulator: xemu") for t in titles)
    assert sel(rows)[-1] == "back"


def test_walk_into_a_console_folder_and_all_the_way_back_up(ui, home):
    b = ui.backend
    b.filesReset()
    rows = b.pageRows("files")
    xbox = next(r for r in rows if r.get("title") == "Games / Atari / xbox")
    assert b.pageActivate("files", xbox["id"]) == "page:files"
    rows = b.pageRows("files")
    text = " ".join(r["title"] for r in rows)
    assert "You are here:  Games / Atari / xbox" in text and any(r.get("title") == "Game.iso" for r in rows)
    assert sel(rows)[:2] == ["fmup", "fmplaces"]                                           # the first buttons: Up and All places (controller: Down/A)
    assert "fmhere" in sel(rows)
    assert b.pageActivate("files", "fmup") == "page:files"
    assert b._fm_dir == home / "Games/Atari" and "Games / Atari" in " ".join(r["title"] for r in b.pageRows("files"))
    assert b.pageEscape("files") == "page:files" and b._fm_dir == home / "Games"            # Esc / B = up one folder too
    assert b.pageActivate("files", "fmup") == "page:files" and b._fm_dir is None             # Games is a start: Up goes to the list of places
    assert b.pageEscape("files") == "back"


def test_all_places_button_jumps_to_the_list_from_any_depth(ui, home):
    b = ui.backend
    (home / "Downloads/pack/inner").mkdir(parents=True)
    b.filesReset()
    b._fm_dir = home / "Downloads/pack/inner"
    rows = b.pageRows("files")
    assert "You are here:  Downloads  >  pack  >  inner" in " ".join(r["title"] for r in rows)
    assert b.pageActivate("files", "fmplaces") == "page:files" and b._fm_dir is None


def test_downloads_page_opens_the_viewer_with_all_places_one_press_away(ui, home):
    b = ui.backend
    assert b.pageActivate("downloads", "dlfiles") == "page:files"
    rows = b.pageRows("files")
    assert "You are here:  Downloads" in " ".join(r["title"] for r in rows) and "fmplaces" in sel(rows)
    assert b.pageActivate("files", "fmplaces") == "page:files"
    assert "Games / Atari / xbox" in [r["title"] for r in b.pageRows("files")]


def test_bios_folder_is_look_only_no_actions_and_a_file_press_says_where_it_is(ui, home):
    b = ui.backend
    b.filesReset()
    rows = b.pageRows("files")
    xemu = next(r for r in rows if r.get("title", "").startswith("BIOS / emulator: xemu"))
    b.pageActivate("files", xemu["id"])
    rows = b.pageRows("files")
    text = " ".join(r["title"] for r in rows)
    assert "look only" in text and "fmhere" not in sel(rows)
    f = next(r for r in rows if r.get("title") == "Complex_4627v1.03.bin")
    assert "look only" in f["detail"]
    assert b.pageActivate("files", f["id"]) == ""                                          # no action page for it
    assert str(home / ".var/app/app.xemu.xemu/data/xemu/xemu/Complex_4627v1.03.bin") in b.toast
    assert b.pageActivate("files", "fmup") == "page:files" and b._fm_dir is None             # a look-only start folder: Up = list of places


def test_a_linked_folder_opens_from_the_screen(ui, home, tmp_path):
    other = tmp_path / "usbdrive"
    (other / "n64").mkdir(parents=True)
    (home / "Games/Atari/usb").symlink_to(other, target_is_directory=True)
    b = ui.backend
    b.filesReset()
    b._fm_dir = home / "Games/Atari"
    rows = b.pageRows("files")
    link = next(r for r in rows if r.get("title") == "usb/  (link)")
    assert b.pageActivate("files", link["id"]) == "page:files" and b._fm_dir == home / "Games/Atari/usb"
    assert any(r.get("title") == "n64/" for r in b.pageRows("files"))
    assert b.pageActivate("files", "fmup") == "page:files" and b._fm_dir == home / "Games/Atari"
