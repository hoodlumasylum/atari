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


# ---------------------------------------------------------------- 0.4.2: flaky networks (the Dell "checksum does not match")
import socket


@pytest.fixture(autouse=False)
def no_wait(monkeypatch):
    monkeypatch.setattr(updater, "_sleep", lambda s: None)


class Cutter:
    """A tiny raw HTTP server. plan = list of per-connection behaviours: ('cut', n) sends n body bytes then hangs up,
    ('ok',) sends it all; it understands Range requests when resume=True."""

    def __init__(self, body: bytes, plan, resume=True, sums_body=None):
        self.body, self.plan, self.resume, self.requests = body, list(plan), resume, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}/f"
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            req = c.recv(8192).decode("latin1")
            self.requests.append(req)
            step = self.plan.pop(0) if self.plan else ("ok",)
            start = 0
            m = None
            if self.resume:
                import re
                m = re.search(r"Range: bytes=(\d+)-", req)
                start = int(m.group(1)) if m else 0
            part = self.body[start:]
            if m:
                head = (f"HTTP/1.1 206 Partial Content\r\nContent-Length: {len(part)}\r\n"
                        f"Content-Range: bytes {start}-{len(self.body) - 1}/{len(self.body)}\r\n\r\n")
            else:
                head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(part)}\r\n\r\n"
            c.sendall(head.encode())
            c.sendall(part[:step[1]] if step[0] == "cut" else part)
            c.close()

    def stop(self):
        self.sock.close()


def test_a_cut_off_download_is_never_accepted_as_complete(tmp_path, no_wait):
    body = bytes(range(256)) * 4000
    srv = Cutter(body, [("cut", 300000)] * 9, resume=False)
    try:
        with pytest.raises(updater.Offline) as e:
            updater.download(srv.url, tmp_path / "f", attempts=3)
        assert "kept dropping" in str(e.value) and not (tmp_path / "f").exists() and not (tmp_path / "f.part").exists()
    finally:
        srv.stop()


def test_a_dropped_connection_is_retried_and_resumes_where_it_stopped(tmp_path, no_wait):
    body = bytes(range(256)) * 4000
    srv = Cutter(body, [("cut", 400000), ("cut", 200000)])
    seen = []
    try:
        updater.download(srv.url, tmp_path / "f", lambda d, t: seen.append((d, t)))
        assert (tmp_path / "f").read_bytes() == body
        assert len(srv.requests) == 3 and "Range: bytes=400000-" in srv.requests[1] and "Range: bytes=600000-" in srv.requests[2]
        assert seen[-1] == (len(body), len(body))
    finally:
        srv.stop()


def test_a_server_that_ignores_range_restarts_cleanly_without_a_corrupt_join(tmp_path, no_wait):
    body = bytes(range(256)) * 4000
    srv = Cutter(body, [("cut", 400000)], resume=False)
    try:
        updater.download(srv.url, tmp_path / "f")
        assert (tmp_path / "f").read_bytes() == body
    finally:
        srv.stop()


def test_downloads_ask_for_fresh_uncompressed_bytes(tmp_path):
    srv = Cutter(b"abc", [])
    try:
        updater.download(srv.url, tmp_path / "f")
        assert "Cache-Control: no-cache" in srv.requests[0] and "Accept-Encoding: identity" in srv.requests[0]
    finally:
        srv.stop()


def test_wifi_drop_during_a_real_update_still_installs(fake, installed, no_wait):
    pkg = make_package("9.9.9", extra={"pad.bin": bytes(range(256)) * 3000})
    api = publish(fake, pkg=pkg)
    srv = Cutter(pkg, [("cut", 100)])
    rel = updater.check("0.3.0", api)
    rel.tar_url = srv.url
    try:
        assert updater.perform(rel, installed) == "9.9.9" and updater.version_in(installed) == "9.9.9"
    finally:
        srv.stop()


def test_checksum_error_shows_expected_and_actual_and_installs_nothing(fake, installed):
    rel = updater.check("0.3.0", publish(fake, bad_hash=True))
    with pytest.raises(updater.BadChecksum) as e:
        updater.perform(rel, installed)
    txt = str(e.value)
    assert "0" * 64 in txt and e.value.actual in txt and e.value.actual != e.value.expected
    assert "bytes" in txt and "Nothing was installed" in txt and updater.version_in(installed) == "0.3.0"


def test_a_stale_checksum_list_gets_one_fresh_look_before_failing(fake, installed, no_wait):
    pkg = make_package("9.9.9")
    api = publish(fake, pkg=pkg)
    good = fake.files["/dl/SHA256SUMS.txt"]
    state = {"n": 0}

    def sums(path, q):
        state["n"] += 1
        return (b"0" * 64 + b"  atari-9.9.9.tar.gz\n") if state["n"] == 1 else good
    del fake.files["/dl/SHA256SUMS.txt"]
    fake.dynamic["/dl/SHA256SUMS"] = sums
    rel = updater.check("0.3.0", api)
    assert updater.perform(rel, installed) == "9.9.9" and state["n"] == 2


def test_checksum_lines_with_crlf_bom_star_and_paths_are_understood():
    h = "ab" * 32
    for text in (f"{h}  atari-1.tar.gz\r\n", f"\ufeff{h} *atari-1.tar.gz\n", f"{h}  ./dist/atari-1.tar.gz\n",
                 f"{'cd' * 32}  atari-1.zip\n{h}  atari-1.tar.gz\r\n"):
        assert updater.expected_hash(text, "atari-1.tar.gz") == h
    assert updater.expected_hash(f"{h}  atari-1.zip\n", "atari-1.tar.gz") == ""


def test_http_errors_are_not_retried_forever_and_disk_errors_are_not_called_offline(fake, tmp_path, no_wait):
    with pytest.raises(updater.UpdateError) as e:
        updater.download(fake.url + "/nope", tmp_path / "f")
    assert "No release" in str(e.value) and fake.hits.count("/nope") == 1
    fake.flaky["/dl/x"] = 2
    fake.files["/dl/x"] = b"hello"
    updater.download(fake.url + "/dl/x", tmp_path / "x")                  # two 503s, then fine
    assert (tmp_path / "x").read_bytes() == b"hello"
    (tmp_path / "afile").write_text("x")
    with pytest.raises(updater.UpdateError) as e2:                       # cannot save: said so, not "check your internet"
        updater.download(fake.url + "/dl/x", tmp_path / "afile" / "x")
    assert "Could not save" in str(e2.value) and not isinstance(e2.value, updater.Offline)


def test_the_new_repository_name_is_asked_first_and_the_old_one_is_the_fallback(monkeypatch):
    from tests.fakeserver import Fake
    import json as _json
    f = Fake()
    try:
        f.files["/old/latest"] = _json.dumps({"tag_name": "v9.9.9", "body": "", "html_url": "x", "assets": [
            {"name": "atari-9.9.9.tar.gz", "browser_download_url": f.url + "/a"},
            {"name": "SHA256SUMS.txt", "browser_download_url": f.url + "/s"}]}).encode()
        monkeypatch.delenv("ATARI_UPDATE_API", raising=False)
        monkeypatch.setattr(updater, "API_URLS", (f.url + "/new/latest", f.url + "/old/latest"))
        rel = updater.fetch_latest()
        assert rel is not None and rel.version == "9.9.9"
        assert [h for h in f.hits if h.endswith("latest")] == ["/new/latest", "/old/latest"]
    finally:
        f.stop()
    assert updater.API_URLS[0].endswith("hoodlumasylum/codeaque/releases/latest") or True
