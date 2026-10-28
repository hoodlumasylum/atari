"""The CodeAque rename: new name and command, ~/Games/CodeAque, the About page, the in-app refresh - and nothing internal moved."""
import os
import subprocess
from pathlib import Path

import pytest

from atarilauncher import branding, config, gamesroot
from atarilauncher.library import build_library

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("ATARI_CONFIG_DIR", str(tmp_path / "conf"))
    monkeypatch.setenv("ATARI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return h


def cfg():
    c = config.default_config()
    c.steam_enabled = False
    return c


def test_all_three_games_folders_are_scanned(home):
    assert gamesroot.ROOTS == ("Games/Atari", "Games/Code", "Games/CodeAque")
    for root, name in (("Atari", "A"), ("Code", "B"), ("CodeAque", "C")):
        (home / "Games" / root / "snes").mkdir(parents=True)
        (home / "Games" / root / "snes" / f"Game {name}.sfc").write_bytes(b"x" * 600)
    res = build_library(cfg(), home=home, metadata={})
    assert sorted(g.title for g in res.games if g.platform == "snes") == ["Game A", "Game B", "Game C"]


def test_installer_adds_the_codeaque_command_and_keeps_the_old_ones(tmp_path):
    text = (ROOT / "install.sh").read_text()
    assert '"$BIN_DIR/codeaque"' in text and '"$BIN_DIR/atari"' in text and '"$BIN_DIR/code-launcher"' in text and 'CODE_LINK="$BIN_DIR/code"' in text
    assert "codeaque" in (ROOT / "uninstall.sh").read_text()
    assert "atari-launcher" in text                                                    # the icon name is internal and unchanged


def test_user_facing_names_say_codeaque_and_internal_names_are_unchanged():
    desktop = (ROOT / "packaging/atari.desktop.in").read_text()
    assert "Name=CodeAque" in desktop and "Icon=atari-launcher" in desktop
    backend = (ROOT / "atarilauncher/backend.py").read_text()
    assert '"Restart CodeAque' in backend and "~/.config/atari" in backend
    assert (ROOT / "atarilauncher/qml/Wordmark.qml").read_text().count("codeaque-logo.png") == 1 and "codeaque-icon.png" in (ROOT / "atarilauncher/qml/Wordmark.qml").read_text()


def make_install(home):
    root = home / "app"
    (root / "packaging/icons").mkdir(parents=True)
    (root / "run.sh").write_text("#!/bin/sh\n")
    (root / "packaging/atari-launcher.svg").write_text("<svg new/>")
    (root / "packaging/icons/code-64.png").write_bytes(b"new64")
    b = home / ".local/bin"
    b.mkdir(parents=True)
    (b / "atari").symlink_to(root / "run.sh")
    ap = home / ".local/share/applications"
    ap.mkdir(parents=True)
    (ap / "atari.desktop").write_text(f"[Desktop Entry]\nName=Code\nExec={root}/run.sh\nIcon=atari-launcher\n")
    ic = home / ".local/share/icons/hicolor/64x64/apps"
    ic.mkdir(parents=True)
    (ic / "atari-launcher.png").write_bytes(b"old64")
    return root


def test_refresh_renames_our_own_entries_and_adds_the_command(home):
    root = make_install(home)
    done = branding.refresh(home, root)
    assert (home / ".local/bin/codeaque").is_symlink() and os.path.realpath(home / ".local/bin/codeaque") == os.path.realpath(root / "run.sh")
    text = (home / ".local/share/applications/atari.desktop").read_text()
    assert "Name=CodeAque\n" in text and "Icon=atari-launcher" in text and f"Exec={root}/run.sh" in text
    assert (home / ".local/share/icons/hicolor/64x64/apps/atari-launcher.png").read_bytes() == b"new64"
    assert done and branding.refresh(home, root) == []                                  # second run changes nothing


def test_refresh_leaves_other_peoples_files_alone(home):
    root = make_install(home)
    (home / ".local/share/applications/atari.desktop").write_text("[Desktop Entry]\nName=Code\nExec=/opt/other/run.sh\n")
    (home / ".local/bin/atari").unlink()
    (home / ".local/bin/atari").write_text("someone else's script")
    (home / ".local/bin/codeaque").write_text("mine")
    branding.refresh(home, root)
    assert "Name=Code\n" in (home / ".local/share/applications/atari.desktop").read_text()
    assert (home / ".local/bin/codeaque").read_text() == "mine" and (home / ".local/bin/atari").read_text() == "someone else's script"
    assert branding.refresh(home / "nowhere", root / "missing") == []                   # nothing there: no error


def test_about_page_is_reachable_from_help_and_says_the_right_things(app, tmp_path, monkeypatch, home):
    monkeypatch.setenv("ATARI_NO_BRANDFIX", "1")
    conf(tmp_path)
    ui = Ui(app, tmp_path, monkeypatch, config_exists=True, home=home)
    b = ui.backend
    help_rows = b.pageRows("help")
    about = [r for r in help_rows if r.get("id") == "about"]
    assert about and "About CodeAque" in about[0]["title"]
    assert b.pageActivate("help", "about") == "page:about"
    assert b.pageTitle("about") == "ABOUT CODEAQUE"
    rows = b.pageRows("about")
    assert rows[0]["title"].startswith("CodeAque ") and rows[0]["image"].endswith("codeaque-logo.png")
    text = " ".join(r["title"] for r in rows)
    assert "~/Games/CodeAque" in text and "codeaque, code, atari and code-launcher" in text and "AI tools" in text and "1254" in text
    assert [r["id"] for r in rows if r["kind"] != "info"][-1] == "back"
    assert b.pageActivate("about", "back") == "back"


def test_a_real_install_gets_all_four_commands(tmp_path):
    from tests.test_rename import install_part
    home, app, out = install_part(tmp_path, with_old=False)
    for name in ("codeaque", "atari", "code-launcher"):
        assert (home / ".local/bin" / name).is_symlink(), name
    assert (home / ".local/bin/code").is_symlink()
