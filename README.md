# Atari — a game launcher for your living-room PC

![Atari home screen](docs/screenshot.png)

**Atari** is a full-screen, controller-friendly "console style" menu for a Linux gaming PC.
You pick a game from a wall of big tiles, press **A** (or **Enter**), and it starts.
It shows:

* your **Steam** games (it finds them automatically, even on several drives),
* your **retro games** (NES, SNES, Mega Drive/Genesis, Atari 2600/7800, Game Boy, GBA, N64, PlayStation 1 and more) from folders you choose,
* **Favorites** and **Recent** lists, **search**, and how long you have played each game.

> **About the name.** "Atari" is just the name of this personal hobby project. It is **not** affiliated with,
> endorsed by, or connected to Atari or any other company. There are no company logos in it: the look
> (black, wood grain, orange-to-red stripes) is original artwork drawn in code, and the covers are generated
> placeholder tiles. **No games or ROMs are included** — you need to own the games you play.

| Search with a controller | Setup screen |
|---|---|
| ![search](docs/screenshot-search.png) | ![setup](docs/screenshot-setup.png) |

(The screenshots use made-up demo games.)

---

## 1. Install (Linux Mint, Ubuntu, Fedora…)

You need a Linux computer with an internet connection (for the first install only).

1. Download **`atari-0.1.0.tar.gz`** from the [Releases page](https://github.com/hoodlumasylum/atari/releases/latest) and unpack it
   (right-click → *Extract Here*). Or, if you know Git: `git clone https://github.com/hoodlumasylum/atari.git`.
2. Open a **Terminal** *inside* the unpacked folder (right-click in the folder → *Open in Terminal*) and type:

   ```bash
   ./install.sh
   ```

   It may ask for your password to install a few standard system libraries (it asks first).
   It then creates a private Python environment inside the folder and adds **Atari** to your application menu (under *Games*).

   * Want it to open by itself when you log in (like a console)? Use `./install.sh --autostart` instead.
   * **Keep the folder** where it is after installing (the menu entry points to it). If you move it, run `./install.sh` again.

Exact commands on a fresh Linux Mint / Ubuntu machine:

```bash
cd ~/Downloads
tar xzf atari-0.1.0.tar.gz
cd atari-0.1.0
./install.sh
```

To remove it later: `./uninstall.sh` (your settings and play history are kept; delete the folder to remove the rest).

## 2. Start it

* Open your application menu and click **Atari**, or
* in a terminal: `./run.sh` (add `--windowed` for a normal window instead of full screen).

**Keys** (a controller works the same way — Xbox/PlayStation/Switch/8BitDo pads are all recognised by SDL):

| Do this | Keyboard | Controller |
|---|---|---|
| Move around | Arrow keys | D-pad / left stick |
| Play the selected game | Enter | A (✕ on PlayStation) |
| Back / close | Esc | B (○) |
| Add/remove favorite | F | Y (△) |
| Search | `/` | X (□) |
| Switch list (Recent, Favorites, Steam, consoles…) | Q / E, or press Up to reach the list bar | LB / RB |
| Menu (rescan, setup, quit) | F10 or M | Start |
| Full screen on/off | F11 | — |

Search has an on-screen keyboard for controllers; with a real keyboard just type.

## 3. Point it at Steam and your ROMs

On the **first start** Atari shows a setup screen automatically. Later: **Menu → Set up folders**.

### Steam
Nothing to do if Steam is installed normally. Atari looks in `~/.steam`, `~/.local/share/Steam`,
the Flatpak location and the Snap location, and reads **all** your Steam library folders (the ones you added
with Steam → *Settings → Storage*), including drives mounted under `/media`, `/mnt` or `/run/media`.
It lists everything that is fully installed (not tools such as Proton), shows the artwork Steam has already
downloaded to your computer (otherwise a coloured tile), and starts games with Steam itself
(`steam steam://rungameid/<id>`). Steam has to be installed and signed in; the first launch may bring up Steam's own window.

If a library lives on a drive that is **not mounted** or is a **Windows (NTFS) drive**, the setup screen and the
game's info line say so. See "Caveats" below.

### Retro games (ROMs)
1. On the setup screen, pick a console (for example *Super Nintendo*) and press **Enter**.
2. Browse to the folder that holds those games (the browser also lists your USB drives) and choose **Use this folder**.
3. Choose **Save and start playing**.

Atari searches the folder and all its sub-folders for the right file types and cleans up the names
(`Super_Game (USA) [!].sfc` → "Super Game"). If you keep ROMs in `~/ROMs/snes`, `~/Roms/nes` etc., Atari
pre-fills them for you on first run.

**Emulators:** Atari does not contain emulators. By default it starts games through **RetroArch**
(easiest: the Flatpak `org.libretro.RetroArch` from the Software Manager, which can download cores for you via
*Load Core → Download a Core*; the Ubuntu/Mint package works too but its cores come as separate packages such as
`libretro-snes9x`), choosing a standard core for each console (e.g. `snes9x`, `fceumm`, `stella`, `mgba`).
Other emulators work too — see below.

**Box art:** Atari doesn't download anything from the internet. Retro games get a generated tile. To use your own picture,
put a PNG/JPG named exactly like the game file (without the extension) here:
`~/.config/atari/covers/<console>/Super_Game (USA).png`, for example `~/.config/atari/covers/snes/...`.

### The settings file (optional, for tinkering)
Everything is stored in plain text in **`~/.config/atari/config.toml`** (created after the first setup). Example:

```toml
[systems.snes]
name = "Super Nintendo"
roms = ["/home/me/ROMs/snes", "/media/me/USB/more-snes"]   # several folders are fine
extensions = ["sfc", "smc", "zip"]
core = "snes9x_libretro"
command = "{retroarch} -f -L {core_path} {rom}"           # default

[systems.gba]
roms = ["/home/me/ROMs/gba"]
command = "mgba-qt -f {rom}"                               # any emulator works

[systems.dreamcast]                                        # brand-new console of your own
name = "Dreamcast"
roms = ["/home/me/ROMs/dc"]
extensions = ["cdi", "gdi", "chd"]
command = "flycast {rom}"

[retroarch]
command = "flatpak run org.libretro.RetroArch"            # only if auto-detection is wrong
```

Placeholders in `command`: `{rom}` (the game file), `{retroarch}`, `{core_path}`, `{core}`, `{cores_dir}`, `{rom_dir}`, `{rom_name}`.
Spaces in file names are handled for you. Also available: `[steam] extra_libraries = [...]` and `[general] fullscreen = false`.
Restart Atari (or use *Menu → Rescan library*) after editing.

Play time and recents are saved in `~/.local/share/atari/state.json`. A log of launches (useful if an emulator won't start)
is in `~/.local/share/atari/launch.log`.

---

## 4. Dual boot: Linux next to Windows

Goal: keep Windows exactly as it is and add Linux for a console-style gaming experience. Choose at power-on which one to use.
This is safe if you go slowly, but **partitioning can destroy data if something goes wrong**, so:

1. **Back up first.** Copy photos, documents and save games to an external drive or cloud storage. Not optional.
2. **Pick a Linux.** The easiest for newcomers is **Linux Mint** (Cinnamon edition) — friendly installer, works with
   Windows already on the disk. Gaming-focused options are **Bazzite** and **Nobara** (Steam and graphics drivers ready out of the box),
   but their installers are less forgiving for *sharing a disk* with Windows: they are happiest on their **own separate drive**.
   (Atari's installer is written for Mint/Ubuntu/Fedora-style systems; Bazzite/Nobara are *not tested* with it.)
3. **Check for BitLocker/Device Encryption** (Windows 11 often turns it on automatically). Find your **recovery key**
   at <https://account.microsoft.com/devices/recoverykey> *before* touching partitions; Windows may ask for it afterwards.
4. **Make room.** In Windows press `Win + X` → **Disk Management** → right-click your **C:** drive → **Shrink Volume**.
   Free **at least 100–200 GB** (more if you want many games). Leave the new space **unallocated** — don't format it.
5. **Turn off Fast Startup** (it leaves Windows' drives half-asleep so Linux can only open them read-only):
   Control Panel → Power Options → *Choose what the power buttons do* → *Change settings that are currently unavailable* →
   untick **Turn on fast startup** → Save. Then do a full **Restart** (not Shut down).
6. **Secure Boot.** Mint, Ubuntu and Fedora boot with Secure Boot **on**. Bazzite/Nobara may ask you to enrol a key the first time
   (follow their install guide). If a proprietary graphics driver (NVIDIA) asks you to set a one-time password and enrol a key on
   the next reboot, follow the blue screen's steps. Only if you still can't boot should you switch Secure Boot off in the BIOS —
   and note that some Windows games' anti-cheat wants it on.
7. **Create the installer USB.** Download the ISO from the distro's website, write it to a USB stick with
   [Balena Etcher](https://etcher.balena.io/) or Rufus, restart and pick the USB in the boot menu (usually F12, F11, F10 or Esc at power-on).
8. **Install alongside Windows.** In the installer choose **"Install Linux Mint alongside Windows Boot Manager"**
   (Ubuntu says "Install Ubuntu alongside Windows Boot Manager"). Drag the slider/choose the free space you made. Finish and restart.
   You will get a menu at every boot to choose Linux or Windows.
9. **After installing**, run Software Update, install the graphics driver (Mint: *Driver Manager*), install **Steam**
   (Software Manager) and sign in, then install Atari (section 1).

### Using your Windows Steam drive from Linux — read this
You will be tempted to point Linux at the Steam library you already have on Windows' drive so you don't re-download games.
**Honest warning:** it mostly doesn't work well.

* Windows drives use **NTFS**. Linux can read and write it (just click the drive in the file manager to mount it — it appears under
  `/media/<you>/` and Atari's folder browser lists it), and Atari **will list** Steam games found there.
* But Windows games run on Linux through **Proton**, which needs a real Linux file system. On NTFS, Proton games often **fail to start,
  crash, or lose saves**. Steam's own support pages say Steam libraries on NTFS are unsupported. Native Linux games can have the same trouble.
* If Windows is hibernating or "fast startup" is on, Linux can only open the drive **read-only** (or refuse), and updating games from
  both systems into the same folder can corrupt the library.

**What I recommend:** keep a **separate Steam library for Linux** on a Linux file system (**ext4**, or **btrfs**):
* best: a **dedicated second drive/SSD** formatted ext4 in Linux (the *Disks* app → format; *formatting erases the drive* — double check which one!), or
* a separate partition you create during the install, or just the default Linux home folder.

Then tell Steam about it: in **Steam → Settings → Storage**, open the drive drop-down → **Add Drive** (older Steam: *Settings → Downloads →
Steam Library Folders → Add Library Folder*), pick the drive's folder, and choose it as the default for new installs. In *Disks*
→ the drive → ⚙ → **Edit Mount Options** → untick *User Session Defaults* and tick *Mount at system startup* so it's
always there. Atari then finds every library Steam knows about automatically. Your Windows games stay on Windows; re-download
what you want on Linux (save games sync through Steam Cloud for many titles).

Other honest caveats: some games with kernel-level anti-cheat (many competitive multiplayer titles) don't run on Linux;
check [protondb.com](https://www.protondb.com) for each game; and big Windows updates occasionally reset the boot menu — Linux's installer docs
(or `boot-repair`) can restore it.

---

## Caveats and limits (honest list)

* Atari was **tested without a real Steam install, real controller, or real emulator** (see *Testing* below). The Steam,
  controller and emulator parts are built to the documented formats and covered by simulated tests, but expect to report small bugs on real hardware.
* Steam play-time is measured by watching for the game's process after Steam starts it; if it can't detect the start,
  the game still launches but no time is recorded. Steam's own time stays in Steam.
* Atari does not manage Steam sign-in, downloads, Proton versions, or shader caches — Steam does.
* Retro defaults assume RetroArch cores exist. A missing core shows RetroArch's own error; details go to `launch.log`.
* No automatic box-art download (by design, to keep it offline and copyright-clean).
* Controller input only works while Atari is the focused window (so it never steals input from a game).
* Wayland/X11 are both supported by Qt, but only headless (offscreen) testing was done. Full screen on some Wayland setups may need `F11`.
* There is **no AppImage** in this version (needs extra work to be reliable); the folder + `install.sh` is the supported way.

## Testing

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Covers the Steam VDF/ACF parser (fixtures with multiple libraries, NTFS mount detection, broken files), ROM scanner, config
round-trips, launch-command building (RetroArch, Flatpak, custom emulators), play-time tracking with a fake emulator and fake Steam
process, search/favorites/recent logic, controller dead-zone/repeat logic, and starting the real UI headlessly (empty setup,
first run, populated). The screenshots are made with:
`QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software ./run.sh --demo --windowed --size 1920x1080 --screenshot docs/screenshot.png`

## How it is built

Python 3 + **PySide6 / Qt Quick (QML)** for the interface; plain Python modules for Steam (`steam.py`, `vdf.py`), ROMs (`roms.py`),
settings (`config.py`), play-time storage (`store.py`) and launching (`launcher.py`). Controllers are read by a small helper
process using SDL2 (from the `pygame` package) and turned into key presses, so the keyboard and controller share one code path.
MIT licensed — see `LICENSE`.
