import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# tests never touch the internet, minimise the window or open terminals unless a test opts in
os.environ.setdefault("ATARI_NO_COVERS", "1")
os.environ.setdefault("ATARI_NO_MINIMIZE", "1")
os.environ.setdefault("ATARI_NO_UPDATE_CHECK", "1")
os.environ.setdefault("ATARI_NO_SOUND", "1")   # no helper process / audio in tests unless a test asks for it
os.environ.setdefault("ATARI_HINT_DELAY", "0")     # no pause for the "press Esc twice" screen
os.environ.setdefault("ATARI_NO_NOTIFY", "1")
os.environ.setdefault("ATARI_NO_SESSIONLOG", "1")  # tests never write the real ~/.local/share/atari/session.log
os.environ.setdefault("ATARI_NO_STEAMFIX", "1")    # tests never edit a real Steam config or start watchers
os.environ.setdefault("ATARI_NO_ROOTAUTH", "1")    # no in-app password provider unless a test asks for it
os.environ.setdefault("ATARI_NO_MEDIA", "1")       # no playerctl calls in tests unless a test fakes them
os.environ.setdefault("ATARI_NO_BADGES", "1")       # no ProtonDB lookups in tests
os.environ.setdefault("ATARI_NO_BRIGHTNESS", "1")
os.environ.setdefault("ATARI_NO_WIFI", "1")        # no nmcli calls in tests unless a test mocks it
os.environ.setdefault("ATARI_NO_INTRO", "1")      # no start-up intro in tests unless a test turns it on
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def fake_system(tmp_path):
    """A pretend Linux home with Steam in ~/.local/share/Steam, a 'Windows' NTFS library and an
    unplugged library, plus a mounts file saying which drive is NTFS."""
    home = tmp_path / "home"
    mnt = tmp_path / "mnt"
    steam = home / ".local/share/Steam"
    (steam / "steamapps").mkdir(parents=True)
    (home / ".steam").mkdir()
    (home / ".steam/steam").symlink_to(steam)
    ntfs_lib = mnt / "WindowsSteam/SteamLibrary"
    (ntfs_lib / "steamapps").mkdir(parents=True)

    def fill(text):
        return text.replace("@HOME@", str(home)).replace("@MNT@", str(mnt))

    (steam / "steamapps/libraryfolders.vdf").write_text(fill((FIX / "libraryfolders_new.vdf").read_text()))
    for name in ("appmanifest_620.acf", "appmanifest_228980.acf", "appmanifest_1887720.acf",
                 "appmanifest_730.acf", "appmanifest_broken.acf"):
        shutil.copy(FIX / name, steam / "steamapps" / name)
    shutil.copy(FIX / "appmanifest_400.acf", ntfs_lib / "steamapps/appmanifest_400.acf")
    (steam / "steamapps/compatdata/620").mkdir(parents=True)
    mounts = tmp_path / "mounts"
    mounts.write_text(fill((FIX / "mounts.txt").read_text()))
    return {"home": home, "mnt": mnt, "steam": steam, "ntfs_lib": ntfs_lib, "mounts": str(mounts)}


@pytest.fixture(scope="session", autouse=True)
def _qt_app():
    """One QGuiApplication (offscreen) for the whole run - the QML key/mouse tests need a GUI app, and Qt allows only one."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        yield None
        return
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    yield app
