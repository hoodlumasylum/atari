import os
import shutil
import subprocess
from pathlib import Path

import pytest

from atarilauncher import xbox, roms

TOOL = "/tmp/exi/extract-xiso"


def test_kinds(tmp_path):
    dc = tmp_path / "Shenmue Disc 1.iso"
    dc.write_bytes(b"SEGA SEGAKATANA SEGA ENTERPRISES" + b"\0" * 70000)
    junk = tmp_path / "junk.iso"
    junk.write_bytes(b"\0" * 70000)
    assert xbox.game_kind(str(dc)) == "dreamcast" and "Dreamcast" in xbox.problem_text("dreamcast")
    assert xbox.game_kind(str(junk)) == "unknown"
    assert xbox.game_kind(str(tmp_path / "x.gdi")) == "dreamcast"


@pytest.mark.skipif(not os.access(TOOL, os.X_OK), reason="needs the real extract-xiso in /tmp/exi")
def test_real_redump_becomes_xiso_copy_original_untouched(tmp_path, monkeypatch):
    src = tmp_path / "g"
    src.mkdir()
    (src / "default.xbe").write_bytes(os.urandom(200000))
    x = tmp_path / "small.xiso"
    subprocess.run([TOOL, "-c", str(src), str(x)], capture_output=True, check=True)
    games = tmp_path / "xbox"
    games.mkdir()
    red = games / "Shenmue II.iso"
    with open(red, "wb") as f:
        f.truncate(0x18300000)
    with open(red, "ab") as f:
        f.write(x.read_bytes())
    before = os.stat(red).st_mtime_ns, red.stat().st_size
    assert xbox.game_kind(str(red)) == "redump"
    said = []
    ok, msg, new = xbox.fix_game_file(str(red), say=said.append, tool=TOOL)
    assert ok and "Done" in msg and new == str(games / "Shenmue II.xiso") and xbox.iso_kind(new) == "xiso"
    assert (os.stat(red).st_mtime_ns, red.stat().st_size) == before                 # original untouched
    assert not [p for p in games.iterdir() if p.name.startswith(".codeaque-xiso-")]
    found = roms.scan_system([games], ("iso", "xiso"), "xbox")
    assert [r.path.name for r in found] == ["Shenmue II.xiso"]                     # shown once, as the fixed copy
    assert xbox.disc_image_for(str(red)) == new


def test_install_tool_checks_checksums(tmp_path, monkeypatch):
    monkeypatch.setattr(xbox, "tool_path", lambda: tmp_path / "tools" / "extract-xiso")
    with pytest.raises(RuntimeError, match="checksum"):
        xbox.install_tool(fetch=lambda url, dest: Path(dest).write_bytes(b"evil"))
    z = Path("/tmp/exi/x.zip")
    if z.is_file():
        p = xbox.install_tool(fetch=lambda url, dest: shutil.copy(z, dest))
        assert os.access(p, os.X_OK)
