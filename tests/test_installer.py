import io
import os
import stat
import zipfile
from pathlib import Path

import pytest

from atarilauncher import apps, installer
from atarilauncher.emulators import EMUS
from tests.fakeserver import Fake

FAKE_FLATPAK = r'''#!/usr/bin/env bash
# a pretend flatpak: remembers installs in $FAKE_FP_DIR, fails for ids listed in $FAKE_FP_FAIL
echo "$@" >> "$FAKE_FP_DIR/log"
case "$1" in
  info) [ -e "$FAKE_FP_DIR/installed/$2" ]; exit $? ;;
  remote-add) touch "$FAKE_FP_DIR/flathub"; exit 0 ;;
  install)
    id="${@: -1}"
    case " $FAKE_FP_FAIL " in *" $id "*) echo "error: nothing matches $id" >&2; exit 1 ;; esac
    mkdir -p "$FAKE_FP_DIR/installed"; touch "$FAKE_FP_DIR/installed/$id"; exit 0 ;;
esac
exit 0
'''


@pytest.fixture
def fp(tmp_path, monkeypatch):
    d = tmp_path / "fp"
    bin_ = tmp_path / "bin"
    d.mkdir(), bin_.mkdir()
    exe = bin_ / "flatpak"
    exe.write_text(FAKE_FLATPAK)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_FP_DIR", str(d))
    monkeypatch.setenv("FAKE_FP_FAIL", "")
    monkeypatch.setattr(installer.time, "sleep", lambda s: None)
    return d


def log_lines(fp):
    p = fp / "log"
    return p.read_text().splitlines() if p.exists() else []


def test_installs_adds_flathub_continues_after_failure_and_summarises(fp, monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_FP_FAIL", "net.pcsx2.PCSX2")
    out = []
    sel = [EMUS["mgba"], EMUS["pcsx2"], apps.BY_ID["roblox"], apps.BY_ID["heroic"]]
    rc = installer.run_install(sel, out=out.append, assume_yes=True, use_apt=False, with_cores=False, home=tmp_path)
    text = "\n".join(out)
    assert rc == 1                                                    # one failed
    log = log_lines(fp)
    assert any(l.startswith("remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo")
               for l in log)
    for fid in ("io.mgba.mGBA", "org.vinegarhq.Sober", "com.heroicgameslauncher.hgl"):
        assert (fp / "installed" / fid).exists()
    assert not (fp / "installed" / "net.pcsx2.PCSX2").exists()
    assert "DID NOT INSTALL (1)" in text and "PCSX2" in text and "Installed now (3)" in text
    assert "UNOFFICIAL" in text and "sign in to your own" in text       # the Roblox note
    assert "Add BIOS files" in text                                     # BIOS reminder, never downloads them


def test_second_run_is_idempotent(fp, tmp_path):
    sel = [EMUS["mgba"], apps.BY_ID["lutris"]]
    installer.run_install(sel, out=lambda s: None, assume_yes=True, use_apt=False, with_cores=False, home=tmp_path)
    n_installs = sum(1 for l in log_lines(fp) if l.startswith("install "))
    out = []
    rc = installer.run_install(sel, out=out.append, assume_yes=True, use_apt=False, with_cores=False, home=tmp_path)
    assert rc == 0 and sum(1 for l in log_lines(fp) if l.startswith("install ")) == n_installs
    assert "Already installed (2)" in "\n".join(out)


def test_default_selection_is_everything():
    ids = {e.id for e in installer.default_selection()}
    assert {"retroarch", "duckstation", "pcsx2", "flycast", "roblox", "heroic", "lutris", "bottles", "itch",
            "prism", "minecraft", "moonlight"} <= ids
    assert "desmume" not in ids


def test_cores_downloaded_from_fake_server(tmp_path):
    f = Fake()
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("nestopia_libretro.so", b"\x7fELF-fake")
        f.files["/nestopia_libretro.so.zip"] = buf.getvalue()
        os.environ["ATARI_CORES_URL"] = f.url + "/{core}.so.zip"
        from atarilauncher import covers
        out = []
        res = installer.install_cores(out.append, tmp_path, covers.Http(timeout=3, pause=0, backoff=0.01),
                                      names=["nestopia_libretro", "missing_libretro"])
    finally:
        os.environ.pop("ATARI_CORES_URL", None)
        f.stop()
    st = {r.name: r.status for r in res}
    assert st["core nestopia"] == "installed" and st["core missing"] == "failed"
    assert (installer.cores_dir(tmp_path) / "nestopia_libretro.so").read_bytes() == b"\x7fELF-fake"


def test_terminal_chain_prefers_the_first_available():
    only = {"gnome-terminal", "kitty"}
    cmd = installer.terminal_command(["bash", "x.sh"], lambda n: "/usr/bin/" + n if n in only else None)
    assert cmd[:2] == ["gnome-terminal", "--"] and cmd[-2:] == ["bash", "x.sh"]
    cmd = installer.terminal_command(["a"], lambda n: "/k" if n == "kitty" else None)
    assert cmd == ["kitty", "a"]
    assert installer.terminal_command(["a"], lambda n: None) is None
    ok, msg = installer.open_in_terminal(["a"], lambda n: None)
    assert not ok and "atari-install-everything" in msg
    started = []
    ok, msg = installer.open_in_terminal(["a"], lambda n: "/x" if n == "xfce4-terminal" else None,
                                         popen=lambda *a, **k: started.append(a[0]))
    assert ok and started == [["xfce4-terminal", "-x", "a"]]


def test_script_wrappers_exist_and_are_executable():
    root = Path(installer.__file__).resolve().parent.parent / "scripts"
    for name in ("install-everything.sh", "install-emulators.sh"):
        assert os.access(root / name, os.X_OK)
