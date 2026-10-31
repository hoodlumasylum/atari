import sqlite3
from pathlib import Path

from atarilauncher import apps, webapps
from atarilauncher.config import default_config


def test_cloud_services_are_listed_and_utomik_is_not():
    ids = {w.id for w in webapps.WEBAPPS if w.cloud}
    assert ids == {"xcloud", "geforcenow", "luna", "boosteroid", "antstream", "blacknut"}
    assert all(w.url.startswith("https://") for w in webapps.WEBAPPS if w.cloud)
    assert "cloud" in apps.NON_GAME


def _lutris(home: Path, slugs):
    db = home / ".local/share/lutris/pga.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE games (id INTEGER, name TEXT, slug TEXT, runner TEXT, installed INTEGER, hidden INTEGER, lastplayed INTEGER)")
    for i, s in enumerate(slugs):
        con.execute("INSERT INTO games VALUES (?,?,?,?,?,?,?)", (i, s, s, "wine", 1, 0, 0))
    con.commit(); con.close()


def test_ea_app_installs_with_lutris_then_runs(tmp_path):
    cfg = default_config()
    ea = apps.BY_ID["eaapp"]
    which = lambda exe: "/usr/bin/lutris" if exe == "lutris" else None
    cmd, how = apps.app_command(cfg, ea, tmp_path, which)
    assert how == "lutris-install" and cmd == ["lutris", "lutris:install/ea-app-standard"]
    _lutris(tmp_path, ["ea-app"])
    cmd, how = apps.app_command(cfg, ea, tmp_path, which)
    assert how == "lutris" and cmd == ["lutris", "lutris:rungame/ea-app"]


def test_rockstar_without_lutris_is_not_ready(tmp_path):
    ok, text = apps.app_status(default_config(), apps.BY_ID["rockstar"], tmp_path, lambda e: None)
    assert not ok and "Lutris" in text
