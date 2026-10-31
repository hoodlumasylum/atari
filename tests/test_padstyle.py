from atarilauncher import padstyle
from tests.test_bluetooth_pads import items, make_ui, pump  # noqa: F401
from tests.test_bluetooth_pads import app  # noqa: F401


def test_style_from_pad_names():
    assert padstyle.style_of("Wireless Controller") == "ps" and padstyle.style_of("DualSense Wireless Controller") == "ps"
    assert padstyle.style_of("Sony Interactive Entertainment Wireless Controller") == "ps"
    assert padstyle.style_of("Xbox Wireless Controller") == "xbox" and padstyle.style_of("Microsoft X-Box 360 pad") == "xbox"
    assert padstyle.style_of("8BitDo Pro 2") == "xbox" and padstyle.resolve("auto", "") == "xbox"
    assert padstyle.resolve("ps", "Xbox Wireless Controller") == "ps" and padstyle.resolve("auto", "Wireless Controller") == "ps"


def test_prompt_words():
    t = "Up/Down to choose, Enter / A to press.  Esc / B = back.  Delete / X clears.  LB / RB = system."
    assert padstyle.pad_text(t, "ps") == ("Up/Down to choose, Enter / Cross to press.  Esc / Circle = back.  Delete / Square clears."
                                          "  L1 / R1 = system.")
    assert padstyle.pad_text(t, "xbox") == t
    assert padstyle.pad_text("A big game. Press Y to sort", "ps") == "A big game. Press Triangle to sort"


def test_hint_bar_switches_live_to_the_last_pad_and_override(app, tmp_path, monkeypatch):  # noqa: F811
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        pump(app, 100)
        a = items(ui.win, "padButton_A")[0]
        assert b.padStyle == "xbox" and a.property("label") == "A"
        b._pad_info_line("#use Wireless Controller")
        pump(app, 100)
        a = items(ui.win, "padButton_A")[0]
        assert b.padStyle == "ps" and a.property("psShape") == "cross" and a.property("label") == ""
        assert items(ui.win, "padButton_menu")[0].property("label") == "OPTIONS"
        assert "Circle = back" in b.pageSub("about")
        b._pad_info_line("#use Xbox Wireless Controller")
        pump(app, 50)
        assert b.padStyle == "xbox" and "B = back" in b.pageSub("about")
        b.cyclePadStyle()                       # auto -> ps
        assert b.padStyle == "ps"
        b.cyclePadStyle()                       # ps -> xbox
        b._pad_info_line("#use Wireless Controller")
        assert b.padStyle == "xbox"             # override wins
        b.cyclePadStyle()                       # back to auto
        assert b.padStyle == "ps"
        ui.win.grabWindow().save("/tmp/hints_ps.png")
    finally:
        ui.close()
