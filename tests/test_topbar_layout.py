"""The home top bar must never overlap itself (0.5.1: the search button sat on top of ADD GAMES at 1366x768)."""
import pytest
from PySide6.QtCore import QPointF, QRectF

from atarilauncher import media
from tests.test_spotify import make, pump  # noqa: F401
from tests.test_spotify import app  # noqa: F401  (fixture)

NAMES = ("addGamesButton", "searchButton", "wifiButton", "brightnessPill", "noPadPill", "padBattery", "clock", "mediaControl")


def walk(root):
    todo = [root]
    while todo:
        it = todo.pop()
        yield it
        todo += it.childItems()


def visible(it):
    while it is not None:
        if not it.isVisible() or it.opacity() == 0:
            return False
        it = it.parentItem()
    return True


def boxes(win):
    root = win.contentItem()
    bar = next(i for i in walk(root) if i.objectName() == "tabRow").parentItem()
    out = []
    for it in walk(bar):
        n = it.objectName()
        if (n in NAMES or (it.parentItem() is not None and it.parentItem().objectName() == "tabRow")) and visible(it) and it.width() > 0:
            p = it.mapToItem(root, QPointF(0, 0))
            out.append((n or "tab", QRectF(p.x(), p.y(), it.width(), it.height())))
    return out


@pytest.mark.parametrize("size", [(1366, 768), (1920, 1080), (1280, 720), (1024, 600)])
def test_top_bar_items_never_overlap(app, tmp_path, monkeypatch, size):  # noqa: F811
    monkeypatch.setenv("ATARI_NO_BATTERY", "1")
    ui, _ = make(app, tmp_path, monkeypatch, media.Track("Playing", "spotify", "A Very Long Artist Name", "An Even Longer Song Title"), [])
    try:
        b = ui.backend
        b.wifi._summary = "Policevan69-HomeNetwork"
        b.wifi.summaryChanged.emit()
        b.set_pad_batteries([{"name": "Pad A", "text": "Charging 40%", "low": False, "charging": True, "percent": 40, "known": True},
                             {"name": "Pad B", "text": "12%", "low": True, "charging": False, "percent": 12, "known": True}])
        ui.win.resize(*size)
        for _ in range(30):
            pump(app, 30)
        bx = boxes(ui.win)
        names = [n for n, _ in bx]
        assert "searchButton" in names and "addGamesButton" in names and names.count("tab") == 5
        for i, (n1, r1) in enumerate(bx):
            assert r1.right() <= size[0] + 0.5 and r1.left() >= -0.5, (n1, r1, size)
            for n2, r2 in bx[i + 1:]:
                if n1 == "padBattery" and n2 == "padBattery" or {n1, n2} == {"tab"}:
                    inter = r1.intersected(r2)
                    assert inter.width() <= 0.5, (n1, n2, size)
                    continue
                inter = r1.intersected(r2)
                assert inter.width() <= 0.5 or inter.height() <= 0.5, (n1, r1, n2, r2, size)
        sb = dict(bx)["searchButton"]
        ab = dict(bx)["addGamesButton"]
        assert sb.left() - ab.right() >= 10, "search needs its own space next to ADD GAMES"
        ui.win.grabWindow().save(str(tmp_path / f"bar{size[0]}.png"))
        import shutil
        shutil.copy(tmp_path / f"bar{size[0]}.png", f"/tmp/bar{size[0]}.png")
    finally:
        ui.close()
