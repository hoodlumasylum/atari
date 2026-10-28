"""The rename from "Atari" to "CodeAque" must not break an existing 0.3.x install: same command, same folders, same desktop /
autostart / CodeAque-only files, and the in-app updater keeps working. (Paths and the repo address are deliberately unchanged.)"""
import os
import re
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from atarilauncher import __version__, config, kiosk, library, paths, updater
from atarilauncher.config import default_config

ROOT = Path(__file__).resolve().parent.parent


def test_the_product_is_called_code_everywhere_a_person_reads_it():
    shown = []
    for f in list((ROOT / "atarilauncher").glob("*.py")) + list((ROOT / "atarilauncher/qml").glob("*.qml")) + [ROOT / "README.md", ROOT / "install.sh", ROOT / "packaging/atari.desktop.in"]:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r"\bAtari\b", line):
                shown.append((f.name, n, line.strip()))
    allowed = ("Atari 2600", "Atari 5200", "Atari 7800", "Atari Lynx", "Atari Jaguar", "Atari ST", "Atari XL", "Atari XE", "Atari 8-bit",
               "Atari 400", "Atari 800", "Atari Flashback", "Atari VCS", "Games/Atari", "Atari Studio", "Atari Recordings", '"Atari"',
               "up to version 0.3", "not Atari", "called \"Atari\"", "Atari/", "Atari-YYYY", "formerly", "Atari OS")
    stray = [s for s in shown if not any(a in s[2] for a in allowed)]
    assert stray == []


def test_window_name_desktop_entry_and_wordmark():
    assert "Name=CodeAque" in (ROOT / "packaging/atari.desktop.in").read_text()
    main = (ROOT / "atarilauncher/__main__.py").read_text()
    assert 'setApplicationName("CodeAque")' in main and 'setDesktopFileName("atari")' in main      # file name kept: autostart still matches
    assert (ROOT / "atarilauncher/assets/codeaque-logo.png").stat().st_size > 10_000
    assert "codeaque-logo.png" in (ROOT / "atarilauncher/qml/Wordmark.qml").read_text()


def test_an_old_032_home_still_loads_unchanged(tmp_path, monkeypatch):
    """~/.config/atari, ~/.local/share/atari and ~/Games/Atari are still where CodeAque looks."""
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "ATARI_CONFIG_DIR", "ATARI_DATA_DIR"):
        monkeypatch.delenv(k, raising=False)
    assert paths.config_dir() == home / ".config" / "atari" and paths.data_dir() == home / ".local" / "share" / "atari"
    (home / ".config/atari").mkdir(parents=True)
    (home / ".config/atari/config.toml").write_text('[ui]\nsound_effects = false\nesc_exit = false\n\n[steam]\nenabled = false\n'
                                                    f'\n[systems.nes]\nroms = ["{home}/Games/Atari/nes"]\n')
    (home / ".local/share/atari").mkdir(parents=True)
    (home / ".local/share/atari/state.json").write_text('{"favorites": ["nes:mario"], "play_seconds": {"nes:mario": 120}}')
    (home / "Games/Atari/nes").mkdir(parents=True)
    (home / "Games/Atari/nes/Mario.nes").write_bytes(b"NES\x1a" + b"\0" * 64)
    cfg = config.load_config()
    assert cfg.sound_effects is False and cfg.esc_exit is False
    assert cfg.intro_enabled and cfg.intro_default and not hasattr(cfg, "wifi_removed")      # new settings default sensibly
    lib = library.build_library(cfg, home=home, metadata={})
    assert any(g.title.startswith("Mario") for g in lib.games)
    assert (home / ".local/share/atari/state.json").read_text().startswith('{"favorites"')   # nothing was touched


def test_an_existing_code_only_install_is_still_recognised_and_removable(tmp_path):
    lay = kiosk.Layout(root=tmp_path)
    for rel, body in ((lay.session_script, "#!/bin/sh\nexec atari --fullscreen\n"),
                      (lay.xsession, "[Desktop Entry]\nName=Atari-only\nExec=/usr/local/bin/atari-session\nType=XSession\n"),
                      (lay.lightdm_conf, "[Seat:*]\nautologin-user=kid\nautologin-session=atari\n")):
        f = lay.p(rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    assert kiosk.enabled(lay)                                                  # the old files are exactly what 0.4 looks for
    assert kiosk.SESSION_NAME == "atari" and lay.session_script.endswith("atari-session")
    new_xs = kiosk.render_xsession("/usr/local/bin/atari-session")
    assert "Name=CodeAque" in new_xs


def test_the_updater_still_finds_atari_named_assets_and_the_old_repo(monkeypatch):
    assert "hoodlumasylum/atari" in updater.API_URL if hasattr(updater, "API_URL") else "hoodlumasylum/atari" in Path(updater.__file__).read_text()
    rel = updater._parse_release if hasattr(updater, "_parse_release") else None
    src = Path(updater.__file__).read_text()
    assert 'f"atari-{version}.tar.gz"' in src                                  # copies of 0.3.x look for exactly this name


# --- the install.sh part that runs on upgrade: command links, desktop entry, icons, autostart ---------------------
def install_part(tmp_path, path_extra="", with_old=True):
    """Runs the 'app menu entry' section of install.sh in a fake HOME (no pip, no network)."""
    text = (ROOT / "install.sh").read_text()
    a = text.index("# ---------------------------------------------------------------- app menu entry")
    b = text.index('say "Done!"')
    section = text[a:b]
    home = tmp_path / "home"
    app = tmp_path / "app"
    (app / "packaging/icons").mkdir(parents=True)
    for f in ("atari-launcher.svg", "atari.desktop.in"):
        (app / "packaging" / f).write_text((ROOT / "packaging" / f).read_text())
    for n in (512, 256, 128, 64):
        (app / f"packaging/icons/code-{n}.png").write_bytes(b"\x89PNG" + bytes(n))
    (app / "scripts").mkdir()
    for f in ("install-everything.sh", "install-emulators.sh"):
        (app / "scripts" / f).write_text("#!/bin/sh\n")
    (app / "run.sh").write_text("#!/bin/sh\n")
    (app / "run.sh").chmod(0o755)
    data = home / ".local/share"
    bin_ = home / ".local/bin"
    if with_old:                                                               # what a 0.3.2 install left behind
        (data / "applications").mkdir(parents=True)
        (data / "applications/atari.desktop").write_text("[Desktop Entry]\nName=Atari\nExec=/old/run.sh\nIcon=atari-launcher\n")
        (home / ".config/autostart").mkdir(parents=True)
        (home / ".config/autostart/atari.desktop").write_text("[Desktop Entry]\nName=Atari\nExec=/old/run.sh\n")
        bin_.mkdir(parents=True)
        (bin_ / "atari").symlink_to("/old/run.sh")
    script = tmp_path / "part.sh"
    script.write_text("set -eu\nsay(){ echo \"== $*\"; }\nAUTOSTART=0\nDATA_HOME='%s'\nAPP_DIR='%s'\nVERSION=0.4.0\n%s\n"
                      "echo \"NOTE=${CODE_NOTE:-}\"\n" % (data, app, section))
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), PATH=f"{path_extra}{fake_bin}:/usr/bin:/bin")
    r = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return home, app, r.stdout


def test_upgrade_keeps_the_atari_command_adds_code_and_renames_the_menu_entry(tmp_path):
    home, app, out = install_part(tmp_path)
    assert (home / ".local/bin/atari").resolve() == (app / "run.sh").resolve()           # re-pointed, still works
    assert (home / ".local/bin/code").resolve() == (app / "run.sh").resolve()
    assert (home / ".local/bin/code-launcher").is_symlink()
    entry = (home / ".local/share/applications/atari.desktop").read_text()
    assert "Name=CodeAque" in entry and f"Exec={app}/run.sh" in entry and "Icon=atari-launcher" in entry
    assert "Name=CodeAque" in (home / ".config/autostart/atari.desktop").read_text()        # an existing autostart is refreshed, not removed
    assert (home / ".local/share/icons/hicolor/256x256/apps/atari-launcher.png").is_file()
    assert (home / ".local/share/icons/hicolor/scalable/apps/atari-launcher.svg").is_file()


def test_the_code_command_never_hijacks_visual_studio_code(tmp_path):
    vs = tmp_path / "vsbin"
    vs.mkdir()
    (vs / "code").write_text("#!/bin/sh\necho vscode\n")
    (vs / "code").chmod(0o755)
    home, app, out = install_part(tmp_path, path_extra=f"{vs}:")
    assert not (home / ".local/bin/code").exists()
    assert (home / ".local/bin/atari").exists() and (home / ".local/bin/code-launcher").exists()
    assert "Visual Studio Code" in out


def test_a_foreign_code_file_in_local_bin_is_left_alone(tmp_path):
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    (home / ".local/bin/code").write_text("#!/bin/sh\n")
    home2, app, out = install_part(tmp_path, with_old=False)
    assert (home / ".local/bin/code").read_text() == "#!/bin/sh\n" and not (home / ".local/bin/code").is_symlink()


def test_uninstall_removes_only_its_own_code_link(tmp_path):
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    ours = tmp_path / "app" / "run.sh"
    ours.parent.mkdir()
    ours.write_text("")
    (home / ".local/bin/code").symlink_to(ours)
    env = dict(os.environ, HOME=str(home), ATARI_INSTALL_DIR=str(tmp_path / "app"), XDG_DATA_HOME=str(home / ".local/share"), XDG_CONFIG_HOME=str(home / ".config"))
    subprocess.run(["bash", str(ROOT / "uninstall.sh")], env=env, capture_output=True, text=True, timeout=30, check=True)
    assert not (home / ".local/bin/code").exists()
    other = home / ".local/bin/code"
    other.write_text("vscode")
    subprocess.run(["bash", str(ROOT / "uninstall.sh")], env=env, capture_output=True, text=True, timeout=30, check=True)
    assert other.read_text() == "vscode"


def test_branding_files_exist():
    from PySide6.QtGui import QImage
    b = ROOT / "docs/branding"
    for n in ("codeaque-logo-source.png", "codeaque-logo.png", "codeaque-banner.png", "codeaque-cutline.png", "README.md"):
        assert (b / n).is_file(), n
    assert not (b / "code-sticker.svg").exists() and not (b / "code-logo.png").exists()          # the old logo is gone
    logo = QImage(str(b / "codeaque-logo.png"))
    assert logo.hasAlphaChannel() and logo.width() >= 1000 and logo.pixelColor(2, 2).alpha() == 0     # transparent background
    cut = QImage(str(b / "codeaque-cutline.png"))
    assert cut.width() >= 1500 and cut.pixelColor(2, 2).alpha() == 0
    text = (b / "README.md").read_text()
    assert "1254" in text and "print" in text.lower() and "AI" in text                         # honest about size and rights
    for n in ("codeaque-logo.png", "codeaque-icon.png"):
        im = QImage(str(ROOT / "atarilauncher/assets" / n))
        assert im.hasAlphaChannel() and im.pixelColor(1, 1).alpha() == 0 and im.width() >= 500
    for n in (512, 256, 128, 64):
        assert QImage(str(ROOT / f"packaging/icons/code-{n}.png")).width() == n
