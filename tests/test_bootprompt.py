from atarilauncher import bootscreen
from tests.test_xemuconfig import make_ui, app  # noqa: F401


def test_prompt_once_after_update_when_menu_is_old(app, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bootscreen, "menu_state", lambda *a, **k: "old")
    monkeypatch.setattr(bootscreen, "menu_entries", lambda *a, **k: ["Linux Mint 22 Cinnamon", "Windows Boot Manager"])
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        asked = []
        b.pageRequested.connect(asked.append)
        ran = []
        b._boot_reapply_prompt()
        assert asked == ["boot"]
        rows = b.pageRows("boot")
        assert any("NOT up to date" in r["title"] for r in rows)
        b._boot_activate("bootinstall", run=lambda script, what: ran.append(what))
        assert ran == ["Installing the boot screen"]          # one tap after the prompt
        b._boot_reapply_prompt()
        assert asked == ["boot"]                                # only once per version
    finally:
        ui.close()
