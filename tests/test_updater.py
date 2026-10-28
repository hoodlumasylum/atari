import hashlib
import io
import json
import tarfile
import threading
from pathlib import Path

import pytest

from atarilauncher import updater
from tests.fakeserver import Fake


@pytest.fixture
def fake():
    f = Fake()
    yield f
    f.stop()


def make_package(version="9.9.9", install_body=None, extra=None):
    """A release tarball shaped like atari-X.Y.Z.tar.gz with a tiny install.sh that copies itself into the install dir."""
    install = install_body or (
        '#!/usr/bin/env bash\nset -e\nSRC="$(cd "$(dirname "$0")" && pwd)"\n'
        'echo "==> Copying files"\nrm -rf "$ATARI_INSTALL_DIR/atarilauncher"\n'
        'cp -a "$SRC/atarilauncher" "$ATARI_INSTALL_DIR/"\necho "==> Done"\n')
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        def add(name, data, mode=0o644):
            ti = tarfile.TarInfo(f"atari-{version}/{name}")
            ti.size, ti.mode = len(data), mode
            tf.addfile(ti, io.BytesIO(data))
        add("install.sh", install.encode(), 0o755)
        add("atarilauncher/__init__.py", f'__version__ = "{version}"\n'.encode())
        for k, v in (extra or {}).items():
            add(k, v)
    return buf.getvalue()


def publish(fake, version="9.9.9", pkg=None, sums=True, bad_hash=False, body="Fixes things.", **kw):
    pkg = pkg if pkg is not None else make_package(version)
    name = f"atari-{version}.tar.gz"
    fake.files[f"/dl/{name}"] = pkg
    digest = hashlib.sha256(pkg).hexdigest()
    if bad_hash:
        digest = "0" * 64
    fake.files["/dl/SHA256SUMS.txt"] = f"{digest}  {name}\n".encode()
    assets = [{"name": name, "browser_download_url": fake.url + f"/dl/{name}"}]
    if sums:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": fake.url + "/dl/SHA256SUMS.txt"})
    fake.files["/repos/x/releases/latest"] = json.dumps(
        dict(tag_name="v" + version, body=body, html_url="http://example/rel", assets=assets, **kw)).encode()
    return fake.url + "/repos/x/releases/latest"


@pytest.fixture
def installed(tmp_path):
    root = tmp_path / "atari-launcher"
    (root / ".venv").mkdir(parents=True)
    (root / "atarilauncher").mkdir()
    (root / "atarilauncher" / "__init__.py").write_text('__version__ = "0.3.0"\n')
    (root / "install.sh").write_text("#!/bin/sh\n")
    return root


def test_version_compare():
    assert updater.is_newer("0.3.1", "0.3.0") and updater.is_newer("v1.0", "0.9.9")
    assert not updater.is_newer("0.3.0", "0.3.0") and not updater.is_newer("0.2.9", "0.3.0")
    assert not updater.is_newer("garbage", "0.3.0")
    assert updater.is_newer("0.10.0", "0.9.0")


def test_due_once_a_day():
    assert updater.due(0, 100000) and not updater.due(99000, 100000) and updater.due(1000, 1000 + 86400)


def test_check_finds_newer_and_ignores_same_or_unusable(fake):
    url = publish(fake, "9.9.9", body="Notes here")
    rel = updater.check("0.3.0", url)
    assert rel and rel.version == "9.9.9" and rel.notes == "Notes here" and rel.tar_name == "atari-9.9.9.tar.gz"
    assert updater.check("9.9.9", url) is None
    assert updater.fetch_latest(publish(fake, "9.9.9", sums=False)) is None          # no checksums: not offered
    assert updater.fetch_latest(publish(fake, "9.9.9", prerelease=True)) is None


def test_offline_and_http_errors_are_friendly(fake):
    with pytest.raises(updater.Offline) as e:
        updater.fetch_latest("http://127.0.0.1:9/x", timeout=1)
    assert "internet" in str(e.value)
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest(fake.url + "/nothing-here")


def test_full_update_keeps_user_files_and_installs(fake, installed, tmp_path):
    cfg = tmp_path / "conf"
    data = tmp_path / "data"
    cfg.mkdir(), data.mkdir()
    (cfg / "config.toml").write_text("mine = true\n")
    (data / "state.json").write_text('{"favorites": ["a"]}')
    rel = updater.check("0.3.0", publish(fake))
    events = []
    ver = updater.perform(rel, installed, lambda *a: events.append(a))
    assert ver == "9.9.9"
    assert updater.version_in(installed) == "9.9.9"
    assert (cfg / "config.toml").read_text() == "mine = true\n"
    assert (data / "state.json").read_text() == '{"favorites": ["a"]}'
    states = [e[0] for e in events]
    assert "downloading" in states and "verifying" in states and "installing" in states
    assert any("Copying files" in e[1] for e in events)


def test_bad_checksum_installs_nothing(fake, installed):
    rel = updater.check("0.3.0", publish(fake, bad_hash=True))
    with pytest.raises(updater.UpdateError) as e:
        updater.perform(rel, installed)
    assert "checksum" in str(e.value) and updater.version_in(installed) == "0.3.0"


def test_failed_install_restores_old_files(fake, installed):
    bad = make_package(install_body='#!/usr/bin/env bash\nrm -rf "$ATARI_INSTALL_DIR/atarilauncher"\n'
                                    'echo "==> Breaking things"\necho boom >&2\nexit 3\n')
    rel = updater.check("0.3.0", publish(fake, pkg=bad))
    with pytest.raises(updater.UpdateError) as e:
        updater.perform(rel, installed)
    assert "put back" in str(e.value)
    assert updater.version_in(installed) == "0.3.0"        # the old copy is still there and intact


def test_wrong_version_inside_package_is_refused(fake, installed):
    rel = updater.check("0.3.0", publish(fake, "9.9.9", pkg=make_package("8.8.8")))
    with pytest.raises(updater.UpdateError):
        updater.perform(rel, installed)
    assert updater.version_in(installed) == "0.3.0"


def test_unsafe_tar_paths_are_refused(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        ti = tarfile.TarInfo("../evil.txt")
        ti.size = 1
        tf.addfile(ti, io.BytesIO(b"x"))
    p = tmp_path / "bad.tar.gz"
    p.write_bytes(buf.getvalue())
    with pytest.raises(updater.UpdateError):
        updater.safe_extract(p, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_cancel_while_downloading(fake, installed):
    rel = updater.check("0.3.0", publish(fake))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(updater.Cancelled):
        updater.perform(rel, installed, cancel=cancel)
    assert updater.version_in(installed) == "0.3.0"


def test_source_checkout_cannot_self_update(tmp_path):
    ok, why = updater.can_self_update(tmp_path)
    assert not ok and "releases/latest" in why


def test_restart_command_runs_run_sh_detached(tmp_path):
    cmd = updater.restart_command(tmp_path, ["--windowed", "--selftest"])
    assert cmd[0] == "bash" and cmd[-2:] == [str(tmp_path / "run.sh"), "--windowed"]
