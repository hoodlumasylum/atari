import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
