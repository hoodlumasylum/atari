# Atari — a game launcher for your living-room PC

![Atari home screen](docs/screenshot.png)

**Atari** is a full-screen, controller-friendly "console style" menu for a Linux gaming PC.
Pick a game from a wall of big covers, press **A** (or **Enter**), and it starts.

* **Steam** games (found automatically, even on several drives) with the artwork Steam already has on disk,
* **retro and modern console games** — Atari 2600/5200/7800/Lynx/Jaguar, NES, SNES, N64, Game Boy/GBA, Genesis, Master System,
  Saturn, Dreamcast, PlayStation 1/2/**3**/PSP, GameCube/Wii/Wii U, Switch, 3DS/DS, **Xbox Classic**, Arcade/MAME, DOS, ScummVM, Amiga,
  C64, MSX, ZX Spectrum and more — through the emulators you install,
* an **Add Games** button that copies games from a **USB stick** into your library,
* **Favourites** and **Recent** lists, **search**, sorting, and play time.

> **About the name.** "Atari" is just the name of this personal hobby project. It is **not** affiliated with,
> endorsed by, or connected to Atari or any other company. There are **no company logos, character art or
> trademarked artwork** in it: the wordmark is plain styled text, the console tiles are original vector glyphs,
> the banner is a generated neon gradient, and covers are generated placeholders unless you provide your own.
> **No games, ROMs, emulators, BIOS files, firmware or keys are included** — you need to own the games you play
> and supply your own BIOS/firmware where an emulator needs it.

| Search with a controller | Add Games from a USB stick |
|---|---|
| ![search](docs/screenshot-search.png) | ![add games](docs/screenshot-add-games.png) |
| **Emulators page** | **Setup screen** |
| ![emulators](docs/screenshot-emulators.png) | ![setup](docs/screenshot-setup.png) |

(The screenshots use made-up demo games. With no games yet you get a friendly empty screen: `docs/screenshot-empty.png`.)

## What's new in 0.2.1

* **Fixed: could not leave the first-start setup screen.** Esc / B (and Enter on the new **DONE / CONTINUE** rows or the button in the top corner)
  now take you to the main screen, even with no games yet (you get the friendly empty screen with the **Add Games** button).
  The welcome screen only appears once; you can always reopen it from **Options → Settings**.
* Keyboard focus is now grabbed reliably when the window opens, after Alt-Tab, and if anything steals it. Mouse / touch work on every row and button.

## What's new in 0.2.0

* **New look**: banner with a red ATARI wordmark, tab row (All Games / Favourites / Recent / Systems / Settings), live clock, a scrollable
  row of big console tiles, sidebar, cover grid, a detail panel with a big **PLAY** button, and a controller-hint bar.
* **Add Games** (top bar, Settings, empty screen): detects USB sticks, finds games on them, lets you tick what to copy (with total size),
  copies with a progress bar, skips duplicates, and never changes the USB stick.
* **Many more consoles** from one data-driven table, including **PlayStation 3 (RPCS3)** and **Xbox Classic (xemu)**, with native *and*
  Flatpak emulator detection. A new **Settings → Emulators** page shows what is installed and how to install the rest;
  `atari-install-emulators` (or `scripts/install-emulators.sh`) installs them from a terminal.
* Sort (A-Z, Z-A, Recently played, Recently added), "Show all systems" option, better covers (Steam library art, your own pictures).
* Your settings, favourites and play history carry over from 0.1.0 automatically.

---

## 1. Install (Linux Mint, Ubuntu, Fedora…)

You need a Linux computer with an internet connection (for the first install only).

1. Download **`atari-0.2.1.tar.gz`** from the [Releases page](https://github.com/hoodlumasylum/atari/releases/latest).
2. Open a **Terminal** and type:

   ```bash
   cd ~/Downloads
   tar xzf atari-0.2.1.tar.gz
   cd atari-0.2.1
   ./install.sh
   ```

   It may ask for your password to install a few standard system libraries (it asks first, and skips this when there is no terminal).
   It copies the app to `~/.local/share/atari-launcher`, creates a private Python environment there and adds **Atari** to your
   application menu (under *Games*) and an `atari` command. **You can delete the downloaded folder afterwards.**

   * Want it to open by itself when you log in (like a console)? Use `./install.sh --autostart`.
   * Other options: `--yes` (no questions), `--no-gamepad` (skip the controller library).
   * **Upgrading from 0.1.0** (or any older version): just run the same steps again. Your config (`~/.config/atari/config.toml`),
  favourites and history (`~/.local/share/atari/state.json`) are left alone.

To remove it later: `~/.local/share/atari-launcher/uninstall.sh` (your settings, play history and games are kept).

## 2. Start it

* Open your application menu and click **Atari**, or
* in a terminal: `atari` (add `--windowed` for a normal window instead of full screen; `./run.sh --windowed` works from a source folder too).

**Controls** (Xbox/PlayStation/Switch/8BitDo pads are all recognised by SDL):

| Do this | Keyboard | Controller |
|---|---|---|
| Move around | Arrow keys | D-pad / left stick |
| Select / play | Enter | A |
| Back / close | Esc | B |
| Add/remove favourite | F | X |
| Options menu (Add Games, sort, rescan, quit…) | F10 or O | Y |
| Change system (jump between consoles) | Tab | ≡ Menu/Start |
| Previous / next system | Q / E | LB / RB |
| Search | `/` | View/Back button, or the search icon |
| Sort | S | Y → Sort |
| Full screen on/off | F11 | — |

Search has an on-screen keyboard for controllers; with a real keyboard just type.
The console tile row shows only systems that have games (plus Steam); choose **Show all systems** to see every supported console.

## 3. Add your games

### From a USB stick (easiest)
1. Plug in the stick, choose **Add Games** (top bar, or Settings, or the empty-library screen).
2. Pick the drive (press **Refresh** if it isn't listed; **Browse folder…** lets you choose any folder instead, e.g. a card on another drive).
3. Atari scans the drive (read-only) for games by file type and folder name, and lists them by console with sizes.
   Tick the ones you want — *Select all* is there — and choose **Copy**.
4. Files go to `~/Games/Atari/<console>/` (or the folder you configured for that console) with a progress bar; files that already
   exist are skipped, **Cancel** stops cleanly, and then the library refreshes. The USB stick is never modified, and NTFS/exFAT/FAT
   sticks and big files (multi-GB discs) are fine. PlayStation 3 game folders (`PS3_GAME`/`EBOOT.BIN`), `.iso`, `.pkg`, and Xbox `.iso`/`.xiso` are recognised.

### From folders
On the **first start** Atari shows a setup screen (press **Esc**, or choose **DONE / CONTINUE**, to skip it and add games later). Later: **Options → Settings** (or the Settings tab). Pick a console, press **Enter**, choose the
folder with its games and **Use this folder**. Atari searches sub-folders and tidies names (`Super_Game (USA) [!].sfc` → "Super Game").
Folders like `~/ROMs/snes`, `~/Games/Atari/snes` are pre-filled when they exist.

### Steam
Nothing to do if Steam is installed normally: Atari looks in `~/.steam`, `~/.local/share/Steam`, the Flatpak and Snap locations and reads
**all** your Steam library folders, including drives under `/media`, `/mnt` or `/run/media`. It lists fully installed games (not tools such as Proton)
and starts them with Steam itself (`steam steam://rungameid/<id>`). Steam must be installed and signed in.

> **Steam libraries on NTFS Windows drives often fail under Proton; a Linux Steam library is recommended.** (More below, and in the Settings
> page and empty screen.)

### Covers
* **Steam games:** the artwork Steam already stored locally (`~/.steam/steam/appcache/librarycache/<appid>/library_600x900.jpg`, `header.jpg`).
* **Other games:** put a PNG or JPG named like the game (without extension) in `~/.local/share/atari/covers/`, e.g. `~/.local/share/atari/covers/Super Game.png`.
  (The older `~/.config/atari/covers/<console>/` folder still works.)
* Otherwise Atari draws a coloured placeholder cover. Nothing is downloaded from the internet.
* Optional details (genre, players, release, rating) can be given in `~/.local/share/atari/metadata.json`:
  `{"Super Game": {"genre": "Platformer", "players": "1-2", "release": "1993", "rating": 4.5}}`.

## 4. Emulators

Atari doesn't contain emulators. Each console in the table lists emulators in order of preference — a program on your PATH **or** a Flatpak —
and Atari uses the first one it finds. Consoles without an emulator still show, with an install hint. See **Settings → Emulators**
(press Enter on a console to cycle the emulator or see how to install it), or in a terminal:

```bash
atari-install-emulators --list              # what's installed, and how to get the rest
atari-install-emulators duckstation pcsx2   # install some via Flatpak (per-user, no sudo)
atari-install-emulators --all
```

| Console | Default emulator candidates (Flatpak ID) |
|---|---|
| Atari 2600/5200/7800/Lynx/Jaguar, NES, SNES, Genesis, Master System, Game Gear, Sega CD, Saturn, PC Engine, Neo Geo, GB/GBC/GBA, MSX, Amiga, etc. | RetroArch (`org.libretro.RetroArch`) + the right core, or a standalone emulator (e.g. mGBA, VICE) |
| N64 | RMG, mupen64plus or RetroArch (mupen64plus-next) |
| PlayStation 1 / 2 / 3 / PSP | DuckStation (`org.duckstation.DuckStation`) / PCSX2 (`net.pcsx2.PCSX2`) / RPCS3 (`net.rpcs3.RPCS3`) / PPSSPP (`org.ppsspp.PPSSPP`) |
| GameCube / Wii / Wii U | Dolphin (`org.DolphinEmu.dolphin-emu`) / Cemu (`info.cemu.Cemu`) |
| Nintendo 3DS / DS | Azahar, Lime3DS or Citra / melonDS or DeSmuME |
| Dreamcast | Flycast (`org.flycast.Flycast`) |
| Xbox Classic | xemu (`app.xemu.xemu`) |
| Arcade, DOS, ScummVM, C64, ZX Spectrum… | MAME, DOSBox, ScummVM, VICE, Fuse via native programs or Flatpak |
| Switch | Configurable command only (set your emulator's command in Settings; no firmware or keys involved in Atari) |
| PS Vita | Note only (Vita3K installs games inside its own window) |
| Xbox 360 | Not supported on Linux |

**PlayStation 3:** started as `rpcs3 --no-gui <EBOOT.BIN | game folder | iso>`. Install with `flatpak install flathub net.rpcs3.RPCS3`.
You must install RPCS3's **firmware** and supply your own games; PS3 emulation is heavy on integrated graphics.
**Xbox Classic:** started as `xemu -dvd_path <iso>`. You supply your own BIOS/HDD image/games in xemu's settings.
**You must supply your own BIOS, firmware, keys and games for any emulator that needs them.**

Override anything in `~/.config/atari/config.toml` (or via the Settings page):

```toml
[systems.gba]
roms = ["/home/me/ROMs/gba"]
emulator = "mgba"                                          # pick a specific emulator from the table
command = "mgba-qt -f {rom}"                               # or a full custom command (empty = automatic)

[systems.ps3]
command = "rpcs3 --no-gui {rom}"

[systems.myconsole]                                        # brand-new console of your own
name = "My Console"
roms = ["/home/me/ROMs/mine"]
extensions = ["cdi", "gdi", "chd"]
command = "flycast {rom}"

[emulators]                                                # emulator program overrides
rpcs3 = "flatpak run net.rpcs3.RPCS3"
```

Placeholders in `command`: `{rom}`, `{rom_dir}`, `{rom_name}`, and for RetroArch `{retroarch}`, `{core_path}`, `{core}`, `{cores_dir}`.
Also available: `[steam] extra_libraries = [...]`, `[general] fullscreen = false`. Restart Atari (or *Options → Rescan*) after hand-editing.

Play time, favourites and recents are in `~/.local/share/atari/state.json`. A launch log (useful if an emulator won't start) is in `~/.local/share/atari/launch.log`.

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

* Atari was **tested headlessly only** — with fake Steam libraries, fake ROMs and a fake USB mount — **not with a real controller, real USB stick,
  or real emulators**. Emulator command lines and Flatpak IDs are written from the emulators' documentation and may need a tweak on your system
  (use the `command =` override).
* The console tiles are original glyph art, not photos of consoles (by design: no company artwork).
* Steam play-time is measured by watching for the game's process; if it can't detect the start, the game still launches but no time is recorded.
* Atari does not manage Steam sign-in, downloads, Proton versions, or shader caches — Steam does.
* Controller input only works while Atari is the focused window (so it never steals input from a game).
* Wayland/X11 are both supported by Qt, but only headless (offscreen) testing was done. Full screen on some Wayland setups may need `F11`.
* Animations are kept light (no GPU effects) for integrated graphics, but performance was not measured on real hardware.
* There is **no AppImage**; the tarball + `install.sh` is the supported way.

## Testing

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Covers the Steam parser, ROM scanner (incl. PS3 folders), the USB import (fake mounts, duplicates, cancel), config round-trips and migration,
emulator detection and launch-command building (native + Flatpak), play-time tracking, search/favourites/sort logic, controller logic, and
the real UI started headlessly (first run incl. Esc/B/Enter to leave setup, keyboard-focus loss, mouse clicks, empty, populated, Add Games end to end, Settings/Emulators pages). Screenshots:
`QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software ./run.sh --demo --windowed --size 1920x1080 --screenshot docs/screenshot.png`
(`scripts/make_demo_home.py` builds a fake home with ~20 games and a fake USB stick.)

## How it is built

Python 3 + **PySide6 / Qt Quick (QML)** for the interface; plain Python modules for Steam (`steam.py`, `vdf.py`), ROMs (`roms.py`),
the emulator table (`emulators.py`), USB import (`importer.py`), settings (`config.py`), storage (`store.py`) and launching (`launcher.py`).
Controllers are read by a small helper process using SDL2 (from the `pygame` package) and turned into key presses, so the keyboard and
controller share one code path. MIT licensed — see `LICENSE`.
