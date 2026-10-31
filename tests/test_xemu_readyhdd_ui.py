import threading

from atarilauncher import xemuconfig
from tests.test_xemuconfig import make_ui, app  # noqa: F401
from tests.test_ui_keys import pump


def wait(app, cond, n=200):  # noqa: F811
    for _ in range(n):
        pump(app, 20)
        if cond():
            return True
    return False


def test_button_shows_progress_then_done_or_try_again(app, tmp_path, monkeypatch):  # noqa: F811
    gate = threading.Event()

    def fake(say=None, **k):
        say("Downloading", 0.5)
        gate.wait(5)
        say("Checking", 1.0)
        return True, "Ready: disk at /x/xbox_hdd_formatted.qcow2", None
    monkeypatch.setattr(xemuconfig, "get_ready_hdd", fake)
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        b.pageRows("xemusetup")
        assert b.pageActivate("xemusetup", "xmhddready") == "refresh"
        assert wait(app, lambda: any(r.get("kind") == "progress" and "Downloading" in r["title"] for r in b.pageRows("xemusetup")))
        changed = []
        b.pageChanged.connect(lambda: changed.append(1))
        gate.set()
        assert wait(app, lambda: "Done, set up." in " ".join(r["title"] for r in b.pageRows("xemusetup")))
        assert changed, "the page must refresh by itself when the download finishes"
        monkeypatch.setattr(xemuconfig, "get_ready_hdd", lambda say=None, **k: (False, "no internet", None))
        b.pageActivate("xemusetup", "xmhddready")
        assert wait(app, lambda: any(r.get("title") == "Try again" for r in b.pageRows("xemusetup")))
        t = " ".join(r["title"] for r in b.pageRows("xemusetup"))
        assert "Could not get the formatted hard disk: no internet" in t and "Open xemu's disk page in the browser" in t
    finally:
        ui.close()
