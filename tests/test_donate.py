"""The optional "Support Code" button: opens the donate page in the browser, only on a button press, one URL constant, no address in the repo."""
import os
import re
from pathlib import Path

import pytest

from atarilauncher import donate, launcher, webapps

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests.test_features_ui import conf, open_menu_item  # noqa: E402
from tests.test_ui_keys import Ui, app, pump  # noqa: E402,F401

ROOT = Path(donate.__file__).resolve().parent.parent


def test_the_url_lives_in_one_constant_and_is_the_paypal_me_link():
    assert donate.DONATE_URL == "https://paypal.me/Codeemulator"
    assert webapps.SUPPORT.url == donate.DONATE_URL and webapps.SUPPORT.browse
    assert "support" in webapps.BY_ID and webapps.SUPPORT not in webapps.WEBAPPS          # a button, never a tile


def test_the_address_is_written_in_exactly_one_place():
    hits = [str(p.relative_to(ROOT)) for p in (ROOT / "atarilauncher").rglob("*.py") if "paypal" in p.read_text().lower()]
    assert hits == ["atarilauncher/donate.py"]


def test_no_email_address_of_a_person_is_in_the_repo():
    bad = []
    for p in list((ROOT / "atarilauncher").rglob("*")) + [ROOT / "README.md", ROOT / "LICENSE", ROOT / "pyproject.toml"]:
        if p.is_file() and p.suffix in (".py", ".qml", ".md", ".toml", "", ".txt"):
            for m in re.findall(r"[\w.+-]+@(?:gmail|googlemail|hotmail|outlook|yahoo)\.[a-z.]+", p.read_text(errors="ignore")):
                bad.append((str(p), m))
    assert not bad


def test_the_browser_command_opens_the_donate_page_in_its_own_profile(tmp_path):
    cmd, name = webapps.build_command(None, webapps.SUPPORT, which=lambda n: "/usr/bin/" + n if n == "chromium" else None, root=tmp_path)
    assert cmd and donate.DONATE_URL in cmd and any(a.startswith("--user-data-dir=") for a in cmd)


@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    conf(tmp_path)
    u = Ui(app, tmp_path, monkeypatch, config_exists=False)
    yield u
    u.close()


def test_settings_and_options_have_the_button_and_it_launches_the_donate_page(app, ui, monkeypatch):
    b = ui.backend
    row = [r for r in b.setupRows() if r.get("kind") == "support"]
    assert len(row) == 1 and "optional" in row[0]["title"].lower() and "never asks" in row[0]["detail"]
    launched = []
    monkeypatch.setattr(webapps, "status", lambda cfg, app, *a, **k: (True, "Opens in X."))
    monkeypatch.setattr(b, "_launch_game", lambda g: launched.append(g))
    b.supportCode()
    assert [g.gid for g in launched] == ["web:support"] and launched[0].title == donate.TITLE
    cmd_seen = []
    monkeypatch.setattr(webapps, "build_command", lambda cfg, a, *x, **k: (cmd_seen.append(a.url) or ["true"], "X"))
    assert launcher.webapps.BY_ID["support"].url == donate.DONATE_URL
    main = (ROOT / "atarilauncher" / "qml" / "Main.qml").read_text()
    assert 'r.kind === "support"' in main and 'id === "support"' in main


def test_no_browser_gives_a_plain_message_and_launches_nothing(app, ui, monkeypatch):
    b = ui.backend
    launched = []
    monkeypatch.setattr(webapps, "status", lambda cfg, app, *a, **k: (False, "none"))
    monkeypatch.setattr(b, "_launch_game", lambda g: launched.append(g))
    b.supportCode()
    assert not launched and "no web browser" in b.toast


def test_the_menu_entry_opens_it_by_keyboard(app, ui, monkeypatch):
    launched = []
    monkeypatch.setattr(webapps, "status", lambda cfg, app, *a, **k: (True, "ok"))
    monkeypatch.setattr(ui.backend, "_launch_game", lambda g: launched.append(g.gid))
    open_menu_item(ui, "support")
    pump(app, 100)
    assert launched == ["web:support"]


def test_nothing_nags_the_donate_text_is_only_in_the_button_rows():
    for p in (ROOT / "atarilauncher").rglob("*.py"):
        if p.name in ("donate.py", "webapps.py"):
            continue
        t = p.read_text()
        assert "donate." not in t or p.name == "backend.py", p.name
