# CodeAque Live USB - plan (no code yet, after 0.5.3)

Goal: plug a stick into any PC, pick it in the boot menu, and land in CodeAque full screen - no install. Saves and settings kept
on the stick. Legal only: the image contains CodeAque, Linux Mint / Ubuntu and free emulators - no games, BIOS or keys.

## Image
- Base: Linux Mint 22 (Ubuntu 24.04) live ISO, remastered with `cubic` (or a scripted `live-build`/squashfs remaster in CI).
- Add: CodeAque (pip/venv as install.sh does), the free emulators install.sh offers, xdotool/wmctrl, brightnessctl, bluez,
  qemu-utils, fonts. Flatpak emulators pre-pulled into the squashfs (size!) or installed on first boot.
- Session: a "CodeAque" LightDM session as the default with autologin of the live user (`mint`), CodeAque-only kiosk mode,
  full screen; CodeAque's GRUB theme + Plymouth splash in the ISO's boot menu.
- Size: ~3.5-4.5 GB ISO with RetroArch cores + a few Flatpaks; 8 GB stick minimum, 32 GB+ recommended for games.

## Boot menu on the stick
- **Try CodeAque** (default): live session with persistence, straight into CodeAque full screen.
- **Install CodeAque to this PC**: starts the installer (Mint's Ubiquity / its successor) with CodeAque preinstalled in the
  image; after install CodeAque's boot screen (GRUB theme, Plymouth splash, CodeAque + Windows menu) is applied by a
  post-install hook, and CodeAque-only mode is offered on first start.
- **Safe graphics** (nomodeset) as a hidden third entry for problem GPUs.

## Installer: simple partition choices
- First screen: "Back up anything important first - installing changes the internal drive." Link to a backup how-to.
- **Install alongside Windows** (shown only when Windows is found): a size slider for CodeAque's share; Windows' partition is
  shrunk with ntfsresize/parted only after an NTFS check. Before going on, two checks with plain warnings:
  - **BitLocker** on: refuse to shrink until it is suspended/turned off in Windows (shrinking an encrypted volume from Linux
    can lose data) and tell the user to have the recovery key;
  - **Fast Startup / hibernation** on: the NTFS volume is "dirty" and cannot be resized safely - tell them to switch Fast Startup
    off in Windows and shut down fully, then try again.
- **Use whole drive** (danger): red screen "EVERYTHING ON <model, size> WILL BE ERASED - including Windows and all files",
  typed confirm of the drive name.
- **Advanced**: the installer's manual partitioning, unchanged.
- Never touches the USB stick it booted from or other external drives unless picked in Advanced; summary screen of every
  change before anything is written; nothing is written before the final Install press.
- Extra size for the plan: installer hooks + checks + post-install boot-screen step ~1 week; testing on real dual-boot PCs
  (BitLocker, fast startup, UEFI/legacy) is the slow part and cannot be done here.

## Persistence
- Ubuntu's `casper` persistence: a `writable` ext4 partition (or `casper-rw` file) after the ISO; kernel option `persistent`.
- Keeps ~/.local/share/atari, emulator saves, Steam login, Wi-Fi passwords. Games live in a separate exFAT data partition
  (`CodeAque/<system>`) so the stick also works as a normal CodeAque USB on Windows/Mac.

## "Make CodeAque Live USB" in the app
- Downloads the CodeAque Live ISO from our GitHub releases (checksum + signature checked), lists USB sticks (never the system
  disk), shows a big red "EVERYTHING ON <stick> WILL BE ERASED" confirm (typed confirm), then writes it with a pkexec helper
  (dd-style raw write + sync), creates the persistence and data partitions (sfdisk/mkfs), and verifies by reading back.
- Windows users: point them to Rufus / balenaEtcher with the same ISO.

## Hard parts / risks
- Secure Boot: use Ubuntu's signed shim/grub/kernel unchanged (works on most PCs); NVIDIA needs the open driver or nomodeset fallback.
- Every PC's GPU / Wi-Fi differs: a "safe graphics" boot entry; first-boot hardware check page.
- ISO hosting: GitHub release assets are limited to 2 GB per file -> split the image or use another download host.
- Updates: CodeAque's in-app update works inside persistence; the base OS ages (rebuild per Mint point release).
- Writing raw disks is the most dangerous thing CodeAque would ever do: heavy tests with loop devices, never a fixed disk.

## How big
- Image build pipeline (scripted remaster + CI + hosting): ~1-2 weeks of work.
- Persistence + data partition layout + first-boot setup: ~3-5 days.
- In-app maker (download, verify, safe disk pick, write, partition, verify): ~1 week, plus careful testing.
- Real-hardware testing on several PCs (Secure Boot, NVIDIA/AMD/Intel): ongoing; cannot be done from here.
- Overall: a multi-week project, best done as its own release (0.6.0).
