import subprocess
from pathlib import Path
from atarilauncher import xemuconfig


def _setup(tmp_path):
    folder = xemuconfig.data_folders(tmp_path, lambda n: None)[0]
    toml = xemuconfig.config_files(tmp_path, lambda n: None)[0]
    toml.parent.mkdir(parents=True, exist_ok=True)
    return folder, toml


def test_portal_paths_are_copied_into_xemus_folder_and_rewritten(tmp_path, monkeypatch):
    folder, toml = _setup(tmp_path)
    portal = tmp_path / "run/user/1000/doc/ab12"
    portal.mkdir(parents=True)
    flash = portal / "Complex_4627.bin"
    flash.write_bytes(b"\0" * 262144)
    assert xemuconfig.is_portal_path("/run/user/1000/doc/ab12/Complex_4627.bin")
    assert not xemuconfig.is_portal_path(str(flash.parent.parent))
    monkeypatch.setattr(xemuconfig, "is_portal_path", lambda v: "/doc/" in str(v))
    toml.write_text(f'[sys.files]\nflashrom_path = "{flash}"\n')
    xemuconfig.repair(tmp_path, lambda n: None)
    text = toml.read_text()
    kept = folder / xemuconfig.CANONICAL["flashrom_path"]
    assert kept.is_file() and str(kept) in text and str(flash) not in text


def test_create_hdd_then_repair_writes_hdd_path(tmp_path):
    folder, toml = _setup(tmp_path)
    toml.write_text("[sys.files]\n")
    which = lambda n: "/usr/bin/qemu-img" if n == "qemu-img" else None

    def runner(cmd, **kw):
        Path(cmd[4]).write_bytes(b"QFI\xfb")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    ok, msg = xemuconfig.create_empty_hdd(tmp_path, which, runner)
    assert ok and (folder / "xbox_hdd.qcow2").is_file()
    assert "formats it itself" not in msg
    assert "XboxHDM" in xemuconfig.FORMAT_HELP and "never downloads" in xemuconfig.FORMAT_HELP
