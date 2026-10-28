"""The file viewer: list with sizes and free space, one-button extract (zip, tar, 7z, rar), add to my games, rename, delete with confirm."""
import dataclasses
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
    assert [e.name for e in entries] == ["Zfolder", "A.txt", "alink", "b.zip"] and not more          # a link to a file is shown (marked), not hidden
    assert entries[0].is_dir and entries[0].count == 1 and entries[3].size == 2048 and entries[3].kind == "zip"
    assert entries[2].link and not entries[1].link
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
    res = files.extract(z, progress=lambda pr: seen.append(dataclasses.replace(pr)), home=home)
    assert res.ok and res.dest == home / "Downloads" / "My Game" and (res.dest / "game" / "data.bin").read_bytes() == b"x" * 1000
    assert "3 items" in res.text and z.exists()                                         # the archive is kept
    assert seen[-1].fraction == 1.0 and seen[-1].percent_text == "100%"
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
    assert files.extract(part, home=home).text == "That is not an archive CodeAque can unpack (zip, tar, 7z, rar)."
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


SEVENZ = r'''#!/bin/sh
echo "$@" >> "$FAKE_LOG"
if [ "$1" = "l" ]; then
  printf 'Path = a.7z\nPhysical Size = 123\n\n----------\nPath = f1\nSize = 300\nFolder = -\n\nPath = f2\nSize = 100\nFolder = -\n'
  exit 0
fi
for a in "$@"; do case "$a" in -o*) D="${a#-o}";; -p*) P="${a#-p}";; esac; done
if [ -n "$FAKE_NEEDPW" ] && [ "$P" != "$FAKE_NEEDPW" ]; then echo "ERROR: Wrong password"; exit 2; fi
mkdir -p "$D"
printf '  0%%'; sleep 0.2
echo one > "$D/f1"; printf '\r 40%% 1 - f1'; sleep 0.2
echo two > "$D/f2"; printf '\r 80%% 2 - f2'; sleep 0.2
printf '\r100%%'; exit 0
'''
UNRAR = r'''#!/bin/sh
echo "$@" >> "$FAKE_LOG"
if [ "$1" = "l" ]; then printf 'Archive: a.rar\n\n  Name   Size\n   f1   300\n   f2   100\n -----------\n          2     400  \n'; exit 0; fi
D="$(for a in "$@"; do last="$a"; done; echo "$last")"
for a in "$@"; do case "$a" in -p*) P="${a#-p}";; esac; done
if [ -n "$FAKE_NEEDPW" ] && [ "$P" != "$FAKE_NEEDPW" ]; then echo "Enter password (will not be echoed) for f1:"; exit 11; fi
if [ -n "$FAKE_CRC" ]; then echo "f1  CRC failed"; exit 3; fi
mkdir -p "$D"
printf 'Extracting  f1                  0%%\b\b\b\b 50%%\b\b\b\b OK\n'; head -c 300 /dev/zero > "$D/f1"; sleep 0.9
printf 'Extracting  f2                  0%%\b\b\b\b 99%%\b\b\b\b OK\n'; head -c 100 /dev/zero > "$D/f2"; sleep 0.9
exit 0
'''


@pytest.fixture
def tools(tmp_path, monkeypatch):
    """Stand-in 7z / unrar programs (real shell scripts that print what the real ones print and write files), found through `which`."""
    d = tmp_path / "tools"
    d.mkdir()
    for name, body in (("7z", SEVENZ), ("unrar", UNRAR)):
        (d / name).write_text(body)
        (d / name).chmod(0o755)
    log = tmp_path / "tool.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.delenv("FAKE_NEEDPW", raising=False)
    monkeypatch.delenv("FAKE_CRC", raising=False)

    def which(n, have=("7z", "unrar")):
        return str(d / n) if n in have and (d / n).exists() else None
    which.log = log
    return which


def test_7z_shows_the_tools_percentage_and_file_names_and_never_waits_on_the_keyboard(home, tools):
    a = home / "Downloads" / "g.7z"
    a.write_bytes(b"x")
    seen = []
    res = files.extract(a, which=lambda n: tools(n, ("7z",)), progress=lambda pr: seen.append(dataclasses.replace(pr)), home=home)
    assert res.ok and (home / "Downloads" / "g" / "f2").read_text() == "two\n" and "2 items" in res.text
    pcts = [round(p.fraction * 100) for p in seen if p.percent is not None]
    assert pcts and pcts == sorted(pcts) and 40 in pcts and 80 in pcts and pcts[-1] == 100
    assert {"f1", "f2"} <= {p.name for p in seen}
    assert seen[0].total == 400 and seen[0].files_total == 2                  # sizes come from the tool's listing
    call = [l for l in tools.log.read_text().splitlines() if l.startswith("x ")][0]
    assert call.startswith("x -y -bso1 -bsp1 -bb1 -o") and f"-o{home / 'Downloads' / 'g'}" in call and call.endswith(str(a)) and " -p " in call


def test_7z_password_is_used_and_a_wrong_or_missing_one_asks(home, tools, monkeypatch):
    a = home / "Downloads" / "s.7z"
    a.write_bytes(b"x")
    monkeypatch.setenv("FAKE_NEEDPW", "pw 1")
    which = lambda n: tools(n, ("7z",))  # noqa: E731
    res = files.extract(a, which=which, home=home)
    assert res.needs_password and not res.ok and not (home / "Downloads" / "s").exists()
    res = files.extract(a, "bad", which=which, home=home)
    assert res.needs_password and "did not work" in res.text and not (home / "Downloads" / "s").exists()
    res = files.extract(a, "pw 1", which=which, home=home)
    assert res.ok and "-ppw 1" in tools.log.read_text()


def test_rar_prefers_unrar_counts_bytes_written_against_the_listed_size_and_reports_errors(home, tools, monkeypatch):
    a = home / "Downloads" / "g.rar"
    a.write_bytes(b"x")
    seen = []
    res = files.extract(a, which=tools, progress=lambda pr: seen.append(dataclasses.replace(pr)), home=home)
    assert res.ok
    first = [l for l in tools.log.read_text().splitlines() if l.startswith("x ")][0]
    assert first.startswith("x -y -p- ") and first.endswith(str(home / "Downloads" / "g") + "/")
    assert seen[0].total == 400 and seen[0].files_total == 2
    byte_fracs = [p.fraction for p in seen if p.percent is None and p.fraction is not None]
    assert byte_fracs and max(byte_fracs) >= 0.7 and byte_fracs == sorted(byte_fracs)        # from the bytes on disk
    assert {"f1", "f2"} <= {p.name for p in seen}
    monkeypatch.setenv("FAKE_NEEDPW", "pw")
    res = files.extract(a, which=tools, home=home)
    assert res.needs_password and not res.ok
    res = files.extract(a, "bad", which=tools, home=home)
    assert res.needs_password and "did not work" in res.text
    monkeypatch.delenv("FAKE_NEEDPW")
    monkeypatch.setenv("FAKE_CRC", "1")
    res = files.extract(a, which=tools, home=home)
    assert not res.ok and not res.needs_password and "damaged" in res.text


def test_cancel_stops_the_tool_and_removes_the_half_made_folder(home, tools):
    a = home / "Downloads" / "g.7z"
    a.write_bytes(b"x")
    ev = threading.Event()

    def progress(pr):
        if pr.percent is not None and pr.percent >= 40:
            ev.set()
    t0 = time.time()
    res = files.extract(a, which=lambda n: tools(n, ("7z",)), progress=progress, cancel=ev, home=home)
    assert not res.ok and res.text == "Cancelled." and time.time() - t0 < 5
    assert not (home / "Downloads" / "g").exists()


def test_a_tool_that_will_not_start_is_explained(home):
    a = home / "Downloads" / "g.7z"
    a.write_bytes(b"x")
    res = files.extract(a, which=lambda n: "/nonexistent/7z" if n == "7z" else None, home=home)
    assert not res.ok and "Could not start" in res.text and not (home / "Downloads" / "g").exists()


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


# ------------------------------------------------------------------ in CodeAque
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
    assert [r["title"] for r in rows if r.get("id", "").startswith("fmroot:")][:4] == ["Downloads", "Games", "Videos", "Games / Atari"]
    assert "Free space here" in next(r for r in rows if r.get("title") == "Downloads")["detail"]
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


def test_password_protected_archive_uses_the_in_app_dialog(app, ui, monkeypatch, tools):
    b = ui.backend
    h = Path(os.environ["HOME"])
    (h / "Downloads" / "s.7z").write_bytes(b"x")
    monkeypatch.setattr(files.shutil, "which", lambda n: tools(n, ("7z",)))
    monkeypatch.setenv("FAKE_NEEDPW", "open sesame")
    b._fm_pick = h / "Downloads" / "s.7z"
    b.pageActivate("fileact", "fmextract")
    for _ in range(100):
        pump(app, 50)
        if b.inputActive:
            break
    assert b.inputActive and b.inputSecret and b.inputTitle == "ARCHIVE PASSWORD"
    b.submitInput("wrong one")                                      # a wrong password asks again, with the reason
    for _ in range(100):
        pump(app, 50)
        if b.inputActive and b.inputError:
            break
    assert b.inputActive and "did not work" in b.inputError
    b.submitInput("open sesame")
    for _ in range(100):
        pump(app, 50)
        if not b._fm_busy:
            break
    assert b._fm_ok and "-popen sesame" in tools.log.read_text()
    assert "open sesame" not in b._fm_msg and (h / "Downloads" / "s" / "f1").exists()


def bar(rows):
    return next((r for r in rows if r.get("kind") == "progress"), None)


def test_extract_runs_in_the_background_with_a_percentage_bar_file_name_and_cancel_button(app, ui, monkeypatch, tools):
    b = ui.backend
    h = Path(os.environ["HOME"])
    (h / "Downloads" / "big.7z").write_bytes(b"x")
    monkeypatch.setattr(files.shutil, "which", lambda n: tools(n, ("7z",)))
    b._fm_pick = h / "Downloads" / "big.7z"
    t0 = time.time()
    assert b.pageActivate("fileact", "fmextract") == "refresh"
    assert time.time() - t0 < 1.0                                    # the click returns at once: the unpack is in a worker thread
    rows = b.pageRows("fileact")
    assert [r["kind"] for r in rows if r["kind"] != "info"][:2] == ["progress", "item"] and rows[-1]["id"] == "fmcancel" and "Cancel" in rows[-1]["title"]
    pcts = []
    for _ in range(200):
        pump(app, 40)
        r = bar(b.pageRows("fileact"))
        if r is None:
            break
        if r["value"]:
            pcts.append(int(r["value"].rstrip("%")))
            assert 0.0 <= r["fraction"] <= 1.0 and r["title"]
            if r["fraction"] >= 0.4:
                assert "f" in r["title"] and "of" in r["detail"]
    assert not b._fm_busy and b._fm_ok and pcts and pcts == sorted(pcts) and max(pcts) >= 40
    assert "Unpacked into the folder" in b._fm_msg and bar(b.pageRows("fileact")) is None
    assert any(r.get("title", "").startswith("DONE:") for r in b.pageRows("fileact"))


def test_the_bar_is_indeterminate_until_a_size_is_known(app, ui):
    b = ui.backend
    b._fm_busy, b._fm_prog = "Unpacking x.rar ...", None
    r = bar(b.pageRows("files" if False else "fileact")) if b._fm_pick else None
    rows = b._fm_busy_rows()
    assert bar(rows)["fraction"] == -1.0 and bar(rows)["title"] == "Getting ready ..." and bar(rows)["value"] == ""
    b._fm_prog = files.Progress(done=5 * 1024 * 1024, name="a/b.bin")
    r = bar(b._fm_busy_rows())
    assert r["fraction"] == -1.0 and "written so far" in r["detail"] and r["title"] == "a/b.bin"
    b._fm_prog = files.Progress(done=512, total=1024, name="c", files_done=1, files_total=4)
    r = bar(b._fm_busy_rows())
    assert r["fraction"] == 0.5 and r["value"] == "50%" and "of" in r["detail"] and "file 2 of 4" in r["detail"]
    b._fm_prog = files.Progress(files_done=3, files_total=4)
    assert bar(b._fm_busy_rows())["value"] == "75%"
    b._fm_busy = ""


def test_cancel_button_and_esc_stop_the_background_unpack_and_say_so(app, ui, monkeypatch, tools):
    b = ui.backend
    h = Path(os.environ["HOME"])
    (h / "Downloads" / "c.7z").write_bytes(b"x")
    monkeypatch.setattr(files.shutil, "which", lambda n: tools(n, ("7z",)))
    b._fm_pick = h / "Downloads" / "c.7z"
    b.pageActivate("fileact", "fmextract")
    for _ in range(50):
        pump(app, 40)
        r = bar(b.pageRows("fileact"))
        if r and r["value"]:
            break
    assert b.pageActivate("fileact", "fmcancel") == ""
    for _ in range(100):
        pump(app, 40)
        if not b._fm_busy:
            break
    assert not b._fm_busy and not b._fm_ok and b._fm_msg == "Cancelled." and not (h / "Downloads" / "c").exists()
    # Esc (and B) does the same
    b.pageActivate("fileact", "fmextract")
    pump(app, 100)
    assert b.pageEscape("fileact") == "" and b._fm_cancel.is_set()
    for _ in range(100):
        pump(app, 40)
        if not b._fm_busy:
            break
    assert b._fm_msg == "Cancelled."


def test_a_failed_unpack_ends_with_an_error_message_not_a_stuck_bar(app, ui, monkeypatch, tools):
    b = ui.backend
    h = Path(os.environ["HOME"])
    (h / "Downloads" / "d.rar").write_bytes(b"x")
    monkeypatch.setattr(files.shutil, "which", lambda n: tools(n, ("unrar",)))
    monkeypatch.setenv("FAKE_CRC", "1")
    b._fm_pick = h / "Downloads" / "d.rar"
    b.pageActivate("fileact", "fmextract")
    for _ in range(100):
        pump(app, 40)
        if not b._fm_busy:
            break
    assert not b._fm_busy and not b._fm_ok and "damaged" in b._fm_msg and bar(b.pageRows("fileact")) is None
    assert any(r.get("title", "").startswith("NOTE:") and "damaged" in r["title"] for r in b.pageRows("fileact"))


def test_qml_draws_the_bar_and_the_cursor_skips_it(app, ui):
    q = (Path(files.__file__).parent / "qml" / "MenuList.qml").read_text()
    m = (Path(files.__file__).parent / "qml" / "Main.qml").read_text()
    assert 'modelData.kind === "progress"' in q and "barFill" in q and "barPercent" in q and "barName" in q and "barDetail" in q
    assert q.count('"progress"') >= 3 and 'r.kind === "progress"' in m
    from PySide6.QtCore import QObject
    from PySide6.QtQuick import QQuickItem
    from tests.test_features_ui import open_menu_item
    b = ui.backend
    b._fm_busy, b._fm_prog = "Unpacking x.zip ...", files.Progress(done=1, total=4, name="dir/file.bin")
    try:
        open_menu_item(ui, "files")
        pump(app, 200)
        assert ui.mode == "page" and ui.win.property("pageName") == "files"

        def find(name, item=None):
            """The VISIBLE item with this objectName (every MenuList has hidden bar parts in each row)."""
            item = item or ui.win.contentItem()
            if item.objectName() == name and item.isVisible():
                return item
            for c in item.childItems():
                r = find(name, c)
                if r is not None:
                    return r
            return None
        fill, track, pct, nm = find("barFill"), find("barTrack"), find("barPercent"), find("barName")
        assert fill is not None and track is not None
        assert pct.property("text") == "25%" and nm.property("text") == "dir/file.bin"
        pump(app, 300)                                                       # the width animates to the fraction
        assert abs(fill.property("width") / track.property("width") - 0.25) < 0.02
        b._fm_prog = files.Progress(done=3, total=4, name="dir/other.bin")
        b.pageChanged.emit()
        pump(app, 500)
        assert find("barPercent").property("text") == "75%" and find("barName").property("text") == "dir/other.bin"
        assert abs(find("barFill").property("width") / find("barTrack").property("width") - 0.75) < 0.02
    finally:
        b._fm_busy, b._fm_prog = "", None


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
