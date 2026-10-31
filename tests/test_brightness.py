import subprocess
from pathlib import Path

from atarilauncher import brightness as br


def mk(tmp_path, cur=50, mx=100, kind="raw", name="intel_backlight"):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "max_brightness").write_text(str(mx))
    (d / "brightness").write_text(str(cur))
    (d / "type").write_text(kind)
    return d


def none(_):
    return None


class R:
    def __init__(self, rc=0, out=""):
        self.calls, self.rc, self.out = [], rc, out

    def __call__(self, cmd, **k):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.rc if callable(self.rc) is False else self.rc(cmd), self.out, "")


def test_order_brightnessctl_first(tmp_path):
    r = R()
    ok, how = br.set_level(40, runner=r, which=lambda n: "/usr/bin/" + n, root=str(tmp_path))
    assert ok and how == "brightnessctl" and r.calls[0][:2] == ["brightnessctl", "-q"] and r.calls[0][-1] == "40%"


def test_sysfs_written_directly_then_pkexec(tmp_path):
    d = mk(tmp_path, mx=1000)
    ok, how = br.set_level(30, which=none, root=str(tmp_path))
    assert ok and how == "backlight" and (d / "brightness").read_text() == "300"
    d.joinpath("brightness").chmod(0o444)
    got = []
    ok, how = br.set_level(60, which=none, root=str(tmp_path), root_run=lambda c: got.append(c) or 0)
    if got:                         # (running as root the write above succeeds anyway)
        assert got[0][:3] == ["pkexec", "sh", "-c"] and "600" not in got[0][3] and "60 / 100" in got[0][3]
    assert ok and how == "backlight"


def test_firmware_backlight_preferred_and_clamped(tmp_path):
    mk(tmp_path, name="acpi_video0", kind="firmware", cur=5, mx=10)
    mk(tmp_path, name="intel_backlight", kind="raw")
    assert br.backlights(str(tmp_path))[0].name == "acpi_video0"
    assert br.read_sysfs(str(tmp_path)) == 50
    assert br.clamp(0) == 5 and br.clamp(250) == 100


def test_xrandr_last(tmp_path, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    r = R(out="eDP-1 connected primary 1920x1080+0+0\nHDMI-1 disconnected\n")
    ok, how = br.set_level(50, runner=r, which=lambda n: n == "xrandr" and "/usr/bin/xrandr", root=str(tmp_path))
    assert ok and how == "xrandr" and r.calls[-1] == ["xrandr", "--output", "eDP-1", "--brightness", "0.50"]
    ok, how = br.set_level(50, runner=r, which=none, root=str(tmp_path))
    assert not ok and how == ""


def test_brightnessctl_read():
    r = R(out="intel_backlight,backlight,3000,63%,4800\n")
    assert br.read_brightnessctl(r, which=lambda n: "x") == 63


def test_fix_script_native_then_vendor_with_backup(tmp_path):
    g = tmp_path / "grub"
    g.write_text('GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n')
    b = tmp_path / "grub.bak"
    assert br.next_fix(g.read_text()) == "native"
    subprocess.run(["sh", "-c", br.fix_script("native", str(g), str(b), "true")], check=True)
    t = g.read_text()
    assert 'GRUB_CMDLINE_LINUX_DEFAULT="acpi_backlight=native quiet splash"' in t and b.read_text().count("acpi") == 0
    assert br.applied_fix(t) == "native" and br.next_fix(t) == "vendor"
    subprocess.run(["sh", "-c", br.fix_script("vendor", str(g), str(b), "true")], check=True)
    t = g.read_text()
    assert t.count("acpi_backlight") == 1 and "acpi_backlight=vendor" in t and br.next_fix(t) == ""
    assert "acpi" not in b.read_text()                     # backup kept from before the first fix
    subprocess.run(["sh", "-c", br.restore_script(str(g), str(b), "true")], check=True)
    assert "acpi" not in g.read_text() and not b.exists()


def test_fix_script_fails_when_update_fails(tmp_path):
    g = tmp_path / "grub"
    g.write_text('GRUB_CMDLINE_LINUX_DEFAULT=""\n')
    p = subprocess.run(["sh", "-c", br.fix_script("native", str(g), str(tmp_path / "b"), "false")])
    assert p.returncode != 0


def test_settings_page_and_slider(tmp_path, monkeypatch):
    import pytest
    from tests.test_bluetooth_pads import app as _a  # noqa: F401
    from tests.test_xemuconfig import make_ui
    from tests.test_ui_keys import pump
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    calls = []
    monkeypatch.setattr(br, "set_level", lambda pct, **k: calls.append(pct) or (True, "brightnessctl"))
    monkeypatch.setattr(br, "GRUB", str(tmp_path / "nogrub"))
    ui = make_ui(app, tmp_path, monkeypatch, tmp_path / "home")
    try:
        b = ui.backend
        assert any(r.get("kind") == "brightnesspage" for r in b.setupRows()) if hasattr(b, "setupRows") else True
        ids = [r.get("id") for r in b.pageRows("brightness")]
        assert "brup" in ids and "brfix" in ids and "brundo" not in ids
        b.pageActivate("brightness", "brset50")
        for _ in range(50):
            pump(app, 20)
            if calls:
                break
        assert calls == [50] and b.brightness == 50
    finally:
        ui.close()
