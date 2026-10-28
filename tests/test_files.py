"""The file viewer: list with sizes and free space, one-button extract (zip, tar, 7z, rar), add to my games, rename, delete with confirm."""
import io
import os
import subprocess
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import pytest

from atarilauncher import config, files

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from tests.test_features_ui import conf  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    for d in ("Downloads", "Games/Atari", "Videos"):
        (h / d).mkdir(parents=True)
    return h


def make_zip(path, entries=None, password=None):
    with zipfile.ZipFile(path, "w") as z:
        for n, data in (entries or {"readme.txt": b"hello", "game/data.bin": b"x" * 1000}).items():
            z.writestr(n, data)


def none_which(_n):
    return None


def only(*names):
    return lambda n: f"/usr/bin/{n}" if n in names else None


# ------------------------------------------------------------------ places and listing
def test_places_are_only_downloads_games_videos_and_what_exists(home, tmp_path):
    assert [l for l, _ in files.roots(home)] == ["Downloads", "Games", "Videos"]
    (home / "Videos").rmdir()
    assert [l for l, _ in files.roots(home)] == ["Downloads", "Games"]
    assert files.inside_roots(home / "Downloads" / "x.zip", home)
    assert not files.inside_roots(tmp_path / "other", home) and not files.inside_roots(home / "Documents", home)
    assert not files.inside_roots(home / "Downloads" / ".." / "Documents", home)


def test_symlink_escaping_a_place_is_outside(home, tmp_path):
    (tmp_path / "secret").mkdir()
    (home / "Downloads" / "link").symlink_to(tmp_path / "secret", target_is_directory=True)
    assert not files.inside_roots(home / "Downloads" / "link", home)
    assert files.delete(home / "Downloads" / "link" / "x", home)[0] is False


def test_listing_has_folders_first_sizes_counts_hides_dotfiles_and_links(home, tmp_path):
    d = home / "Downloads"
    (d / "b.zip").write_bytes(b"x" * 2048)
    (d / "A.txt").write_bytes(b"x")
    (d / ".hidden").write_text("x")
    (d / "Zfolder").mkdir()
    (d / "Zfolder" / "one").write_text("1")
    (d / "alink").symlink_to(d / "A.txt")
    entries, more = files.list_dir(d)
    assert [e.name for e in entries] == ["Zfolder", "A.txt", "b.zip"] and not more
    assert entries[0].is_dir and entries[0].count == 1 and entries[2].size == 2048 and entries[2].kind == "zip"
    assert files.list_dir(d, cap=2)[1] is True and files.list_dir(tmp_path / "nope") == ([], False)


def test_free_space_text():
    t = files.free_text(Path("/tmp"))
    assert t.startswith("Free space here: ") and " of " in t
    assert files.free_text(Path("/definitely/not/here")) == "Free space: unknown"


# ------------------------------------------------------------------ rename / delete
def test_rename_rules(home):
    f = home / "Downloads" / "old.zip"
    f.write_text("x")
    (home / "Downloads" / "taken.zip").write_text("x")
    assert files.rename(f, "a/b", home)[1] == "A name cannot contain a slash (/)."
    assert files.rename(f, "  ", home)[0] is False and files.rename(f, "..", home)[0] is False
    assert "already exists" in files.rename(f, "taken.zip", home)[1] and "same name" in files.rename(f, "old.zip", home)[1]
    ok, text = files.rename(f, "new name.zip", home)
    assert ok and (home / "Downloads" / "new name.zip").exists() and not f.exists() and "new name.zip" in text
    assert not files.rename(home / "Downloads", "x", home)[0]                          # a place itself
    assert not files.rename(home / "elsewhere.txt", "x", home)[0]


def test_delete_file_folder_and_link_and_refusals(home, tmp_path):
    d = home / "Downloads"
    (d / "f.bin").write_text("x")
    assert files.delete(d / "f.bin", home) == (True, "Deleted f.bin.") and not (d / "f.bin").exists()
    (d / "dir" / "sub").mkdir(parents=True)
    (d / "dir" / "sub" / "x").write_text("x")
    assert files.delete(d / "dir", home)[0] and not (d / "dir").exists()
    outside = tmp_path / "keepme"
    outside.mkdir()
    (outside / "x").write_text("x")
    (d / "lnk").symlink_to(outside, target_is_directory=True)
    ok, text = files.delete(d / "lnk", home)
    assert not ok                                                  # resolves outside the places: refused, and what it points to is untouched
    assert (outside / "x").exists()
    assert not files.delete(d, home)[0] and d.exists()              # never a place itself
    assert not files.delete(tmp_path / "keepme" / "x", home)[0] and (outside / "x").exists()
    assert "gone" in files.delete(d / "never", home)[1]


# ------------------------------------------------------------------ open
def test_open_uses_mpv_for_videos_and_xdg_open_otherwise(home):
    v, t = home / "Videos" / "a.mp4", home / "Downloads" / "a.txt"
    assert files.opener(v, only("mpv", "xdg-open")) == ["mpv", "--fs", "--", str(v)]
    assert files.opener(v, only("vlc", "xdg-open"))[0] == "vlc"
    assert files.opener(v, only("xdg-open")) == ["xdg-open", str(v)] and files.opener(t, only("mpv", "xdg-open"))[0] == "xdg-open"
    assert files.opener(t, none_which) == []
    calls = []
    v.write_text("x")
    ok, text = files.open_file(v, only("mpv"), lambda cmd, **kw: calls.append((cmd, kw)), home)
    assert ok and calls[0][1]["start_new_session"] is True
    assert not files.open_file(t, none_which, None, home)[0]
    assert not files.open_file(home.parent / "x.txt", only("xdg-open"), None, home)[0]


# ------------------------------------------------------------------ extract
def test_zip_extracts_with_one_call_into_a_new_folder_beside_it(home):
    z = home / "Downloads" / "My Game.zip"
    make_zip(z)
    seen = []
    res = files.extract(z, progress=lambda i, n: seen.append((i, n)), home=home)
    assert res.ok and res.dest == home / "Downloads" / "My Game" and (res.dest / "game" / "data.bin").read_bytes() == b"x" * 1000
    assert "3 items" in res.text and seen[-1] == (1, 1) and z.exists()                  # the archive is kept
    res2 = files.extract(z, home=home)                                                  # again: a NEW folder, nothing overwritten
    assert res2.ok and res2.dest.name == "My Game (2)" and res.dest.exists()


def test_tar_variants_extract_and_skip_links(home):
    t = home / "Downloads" / "pack.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        info = tarfile.TarInfo("a/b.txt")
        info.size = 3
        tf.addfile(info, io.BytesIO(b"abc"))
        ln = tarfile.TarInfo("a/evil")
        ln.type = tarfile.SYMTYPE
        ln.linkname = "/etc/passwd"
        tf.addfile(ln)
    res = files.extract(t, home=home)
    assert res.ok and (res.dest / "a" / "b.txt").read_text() == "abc" and not (res.dest / "a" / "evil").exists() and res.dest.name == "pack"
    assert files.archive_stem(Path("x.tgz")) == "x" and files.archive_kind("a.TAR.XZ") == "tar" and files.archive_kind("a.txt") == ""


def test_unsafe_paths_stop_everything_and_leave_nothing_behind(home):
    z = home / "Downloads" / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("fine.txt", "x")
        zf.writestr("../../escaped.txt", "x")
    res = files.extract(z, home=home)
    assert not res.ok and "unsafe path" in res.text and not (home / "Downloads" / "evil").exists()
    assert not (home / "escaped.txt").exists() and not (home.parent / "escaped.txt").exists()


def test_a_broken_or_unfinished_archive_is_explained(home):
    bad = home / "Downloads" / "bad.zip"
    bad.write_bytes(b"not a zip")
    res = files.extract(bad, home=home)
    assert not res.ok and "could not be opened" in res.text and not (home / "Downloads" / "bad").exists()
    part = home / "Downloads" / "x.zip.part"
    part.write_text("x")
    assert files.extract(part, home=home).text == "That is not an archive Code can unpack (zip, tar, 7z, rar)."
    assert "gone" in files.extract(home / "Downloads" / "no.zip", home=home).text
    assert "inside Downloads" in files.extract(home.parent / "o.zip", home=home).text


def test_7z_and_rar_need_a_tool_and_the_install_button_names_it(home):
    for name, tool in (("a.7z", "7zip"), ("a.rar", "unrar")):
        a = home / "Downloads" / name
        a.write_bytes(b"x")
        res = files.extract(a, which=none_which, home=home)
        assert not res.ok and res.needs_tool == tool and "Install button" in res.text and not (home / "Downloads" / "a").exists()
    assert files.missing_tool("zip", none_which) == "" and files.missing_tool("tar", none_which) == ""
    assert files.missing_tool("rar", only("7z")) == "" and files.tool_for("rar", only("unrar", "7z"))[1] == "unrar"


def fake_runner(calls, rc=0, out="", on_run=None):
    def run(cmd, **kw):
        calls.append(cmd)
        if on_run:
            on_run(cmd)
        return subprocess.CompletedProcess(cmd, rc, out, "")
    return run


def test_7z_runs_the_tool_into_the_new_folder_and_a_password_is_used(home):
    a = home / "Downloads" / "g.7z"
    a.write_bytes(b"x")
    calls = []
    res = files.extract(a, which=only("7z"), run=fake_runner(calls, on_run=lambda c: (home / "Downloads" / "g" / "f").write_text("1")), home=home)
    assert res.ok and calls[0][:4] == ["/usr/bin/7z", "x", "-y", "-bd"] and calls[0][4] == f"-o{home / 'Downloads' / 'g'}" and calls[0][-1] == str(a)
    assert "-p" in calls[0]                                                    # no password: the tool must not wait on the keyboard
    calls.clear()
    files.extract(a, "pw 1", which=only("7z"), run=fake_runner(calls), home=home)
    assert "-ppw 1" in calls[0]


def test_rar_prefers_unrar_and_a_password_error_asks_for_it(home):
    a = home / "Downloads" / "g.rar"
    a.write_bytes(b"x")
    calls = []
    files.extract(a, which=only("unrar", "7z"), run=fake_runner(calls), home=home)
    assert calls[0][:3] == ["/usr/bin/unrar", "x", "-y"] and "-p-" in calls[0]
    (home / "Downloads" / "g").rmdir()
    res = files.extract(a, which=only("unrar"), run=fake_runner([], rc=3, out="Enter password (will not be echoed)"), home=home)
    assert res.needs_password and not res.ok and not (home / "Downloads" / "g").exists()
    res = files.extract(a, "bad", which=only("unrar"), run=fake_runner([], rc=3, out="Wrong password"), home=home)
    assert res.needs_password and "did not work" in res.text
    res = files.extract(a, which=only("unrar"), run=fake_runner([], rc=2, out="CRC failed"), home=home)
    assert not res.ok and not res.needs_password and "damaged" in res.text


def test_encrypted_zip_asks_for_a_password(home):
    z = home / "Downloads" / "secret.zip"
    make_zip(z)
    data = bytearray(z.read_bytes())
    # set the "encrypted" flag bit in every local + central header (enough for the check; real decryption is not attempted here)
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = 0
        while (i := data.find(sig, i)) != -1:
            data[i + off] |= 1
            i += 4
    z.write_bytes(bytes(data))
    res = files.extract(z, home=home)
    assert res.needs_password and not (home / "Downloads" / "secret").exists()


def test_cancel_stops_a_zip_and_cleans_up(home):
    z = home / "Downloads" / "big.zip"
    make_zip(z, {f"f{i}.txt": b"x" for i in range(20)})
    ev = threading.Event()
    ev.set()
    res = files.extract(z, cancel=ev, home=home)
    assert not res.ok and res.text == "Cancelled." and not (home / "Downloads" / "big").exists()


# ------------------------------------------------------------------ in Code
@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    conf(tmp_path)
    u = Ui(app, tmp_path, monkeypatch, config_exists=False)
    h = tmp_path / "home"
    for d in ("Downloads", "Games/Atari", "Videos"):
        (h / d).mkdir(parents=True, exist_ok=True)
    yield u
    u.close()


def row(rows, rid):
    return next((r for r in rows if r.get("id") == rid), None)


def titles(rows):
    return " | ".join(r.get("title", "") for r in rows)


def test_downloads_page_has_the_big_file_viewer_button_and_options_has_the_entry(ui):
    rows = ui.backend.pageRows("downloads")
    r = row(rows, "dlfiles")
    assert r and r["kind"] == "done" and "FILE VIEWER" in r["title"] and rows.index(r) <= 2
    from pathlib import Path as P
    main = (P(files.__file__).parent / "qml" / "Main.qml").read_text()
    assert 'id: "files"' in main and "My files" in main


def test_browse_list_folders_and_back_up(ui):
    b = ui.backend
    h = Path(os.environ["HOME"])
    (h / "Downloads" / "Sub").mkdir()
    (h / "Downloads" / "Sub" / "x.txt").write_text("x" * 5000)
    (h / "Downloads" / "pack.zip").write_bytes(b"x" * 3000)
    b.filesReset()
    rows = b.pageRows("files")
    assert [r["title"] for r in rows if r.get("id", "").startswith("fmroot:")] == ["Downloads", "Games", "Videos"]
    assert "Free space here" in rows[1]["detail"]
    assert b.pageActivate("files", "fmroot:0") == "page:files"
    rows = b.pageRows("files")
    assert any("Free space here" in r.get("title", "") for r in rows)
    sub = next(r for r in rows if r.get("title") == "Sub/")
    assert sub["value"] == "1 item"
    pack = next(r for r in rows if r.get("title") == "pack.zip")
    assert pack["value"] == "2.9 KB" and "Extract here" in pack["detail"]
    assert b.pageActivate("files", sub["id"]) == "page:files"
    rows = b.pageRows("files")
    assert any(r.get("title") == "x.txt" and r["value"] == "4.9 KB" for r in rows)
    assert b.pageEscape("files") == "page:files"                       # Esc / B goes up one folder
    assert any(r.get("title") == "Sub/" for r in b.pageRows("files"))
    assert b.pageEscape("files") == "page:files" and b._fm_dir is None
    assert b.pageEscape("files") == "back"


def test_one_button_extract_in_code_with_progress_and_result(app, ui):
    b = ui.backend
    h = Path(os.environ["HOME"])
    make_zip(h / "Downloads" / "game.zip")
    b.filesReset()
    b._fm_dir = h / "Downloads"
    rows = b.pageRows("files")
    zid = next(r["id"] for r in rows if r.get("title") == "game.zip")
    assert b.pageActivate("files", zid) == "page:fileact"
    rows = b.pageRows("fileact")
    assert row(rows, "fmextract")["kind"] == "done" and "Extract here" in row(rows, "fmextract")["title"]
    assert row(rows, "fminstall:7zip") is None
    assert b.pageActivate("fileact", "fmextract") == "refresh"
    assert b._fm_busy
    for _ in range(100):
        pump(app, 50)
        if not b._fm_busy:
            break
    assert not b._fm_busy and b._fm_ok and (h / "Downloads" / "game" / "readme.txt").exists()
    assert "Unpacked into the folder" in b._fm_msg


def test_missing_tool_shows_an_install_button(ui, monkeypatch):
    b = ui.backend
    h = Path(os.environ["HOME"])
    (h / "Downloads" / "x.rar").write_bytes(b"x")
    monkeypatch.setattr(files.shutil, "which", none_which)
    b._fm_pick = h / "Downloads" / "x.rar"
    rows = b.pageRows("fileact")
    assert row(rows, "fminstall:unrar")["title"] == "Install unrar"
    asked = []
    monkeypatch.setattr(b, "begin_install", lambda specs, for_gid="", what="", titles=None: asked.append((specs, what)))
    b.pageActivate("fileact", "fminstall:unrar")
    assert asked == [(["unrar"], "unrar (opens .rar archives)")]


def test_password_protected_archive_uses_the_in_app_dialog(app, ui, monkeypatch):
    b = ui.backend
    h = Path(os.environ["HOME"])
    (h / "Downloads" / "s.7z").write_bytes(b"x")
    monkeypatch.setattr(files.shutil, "which", only("7z"))
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        if not any(a.startswith("-p") and len(a) > 2 for a in cmd):
            return subprocess.CompletedProcess(cmd, 2, "Enter password:", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(files.subprocess, "run", fake_run)
    b._fm_pick = h / "Downloads" / "s.7z"
    b.pageActivate("fileact", "fmextract")
    for _ in range(100):
        pump(app, 50)
        if b.inputActive:
            break
    assert b.inputActive and b.inputSecret and b.inputTitle == "ARCHIVE PASSWORD"
    b.submitInput("open sesame")
    for _ in range(100):
        pump(app, 50)
        if not b._fm_busy:
            break
    assert b._fm_ok and any("-popen sesame" in c for c in seen[-1])
    assert "open sesame" not in b._fm_msg


def test_rename_in_code_uses_the_typing_box(app, ui):
    b = ui.backend
    h = Path(os.environ["HOME"])
    f = h / "Downloads" / "old.txt"
    f.write_text("x")
    b._fm_pick = f
    b.pageActivate("fileact", "fmrename")
    pump(app, 100)
    assert b.inputActive and b.inputInitial == "old.txt" and not b.inputSecret
    b.submitInput("new.txt")
    pump(app, 100)
    assert (h / "Downloads" / "new.txt").exists() and not f.exists() and b._fm_pick.name == "new.txt" and "Renamed" in b._fm_msg
    b.pageActivate("fileact", "fmrename")
    pump(app, 100)
    b.cancelInput()
    assert (h / "Downloads" / "new.txt").exists()


def test_delete_asks_first_and_starts_on_no(app, ui):
    b = ui.backend
    h = Path(os.environ["HOME"])
    f = h / "Downloads" / "junk.bin"
    f.write_text("x")
    b._fm_pick = f
    assert b.pageActivate("fileact", "fmdelete") == "page:fileact"
    rows = b.pageRows("fileact")
    selectable = [r for r in rows if r.get("kind") != "info"]
    assert selectable[0]["id"] == "fmno" and selectable[1]["id"] == "fmyes" and "for good" in titles(rows) + " ".join(r.get("title", "") for r in rows)
    assert b.pageActivate("fileact", "fmno") == "page:fileact" and f.exists()
    assert b.pageEscape("fileact") == "page:files" and f.exists()
    b.pageActivate("fileact", "fmdelete")
    assert b.pageActivate("fileact", "fmyes") == "page:files" and not f.exists() and "Deleted junk.bin" in b._fm_msg


def test_add_to_my_games_goes_through_the_system_picker_and_back_to_the_viewer(ui):
    b = ui.backend
    h = Path(os.environ["HOME"])
    f = h / "Downloads" / "sonic.md"
    f.write_bytes(b"x")
    b._fm_pick = f
    assert b.pageActivate("fileact", "fmadd") == "page:dlsystem"
    rows = b.pageRows("dlsystem")
    sid = next(r["id"] for r in rows if r.get("id", "").startswith("dlsys:"))
    assert b.pageActivate("dlsystem", sid) == "page:files"
    assert not f.exists() and "in your games now" in b._fm_msg


def test_keys_walk_the_viewer_and_escape_goes_up(app, ui):
    from tests.test_features_ui import open_menu_item
    h = Path(os.environ["HOME"])
    (h / "Downloads" / "Sub").mkdir()
    open_menu_item(ui, "files")
    pump(app, 100)
    assert ui.mode == "page" and ui.win.property("pageName") == "files"
    ui.key(Qt.Key_Return)                                   # Downloads
    pump(app, 100)
    assert ui.backend._fm_dir == h / "Downloads"
    ui.key(Qt.Key_Escape)                                   # up to the places
    pump(app, 100)
    assert ui.mode == "page" and ui.backend._fm_dir is None
    ui.key(Qt.Key_Escape)                                   # and out
    pump(app, 100)
    assert ui.mode == "library"
