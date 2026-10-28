# Code OS - design plan (not built yet)

(The public-release "Install Code" interface - dual boot or Code-only - is designed at the end of this file.)

Goal: a flashable USB image that wipes a machine and installs a minimal Linux that boots straight into Code (no desktop). First target: Dell Latitude 5420. Later: tablets / handhelds.

* **Base:** Ubuntu 24.04 LTS minimal (same package base as Linux Mint 22, so every Code path - Flatpak, apt, pkexec, LightDM - behaves as in the app today). Built with `live-build` (reproducible, scriptable in CI); Cubic only for quick experiments.
* **Installer:** Ubuntu Subiquity autoinstall (cloud-init `user-data`) on the live image: wipes the chosen disk (default: the single internal NVMe, confirmed on screen), GPT + EFI, ext4 (+ optional LUKS), creates user `atari` with auto-login.
* **Session:** LightDM or plain `getty` autologin + `startx`/`cage` -> Code full screen; reuse the 0.3.2 session script (crash loop falls back to a text console shell, not a desktop). Tiny WM (openbox) or a Wayland kiosk compositor (`cage`) later.
* **Packages:** `flatpak` + Flathub pre-configured, `pipewire-pulse`, `mesa-vulkan-drivers`, `intel-media-va-driver`, `network-manager`, firmware (`linux-firmware`, Intel wifi/BT for the 5420), `steam-devices`, `xemu`/emulators installed on demand by Code's own Install buttons (keeps the image small, legal and current).
* **First boot / wifi:** an Code "Welcome" screen: pick wifi (nmcli through a controller-friendly list + on-screen keyboard, which Code already has), timezone, then the existing getting-started checklist.
* **Updates:** Code's in-app updater; OS security updates via `unattended-upgrades`.
* **Flashing:** `dd`/balenaEtcher/`rpi-imager`-style; publish `atari-os-<ver>.iso` + SHA256SUMS on GitHub Releases; document `sha256sum -c` and a safety warning.
* **Testing:** (1) CI: build in a container, boot in QEMU/OVMF headless, screenshot via VNC and assert the Code window; (2) install into a VM disk with autoinstall; (3) Latitude 5420 test only on a spare machine, never before (1)+(2) pass; (4) hardware checklist: wifi, sound, touchpad/keyboard, Secure Boot (signed shim from Ubuntu), suspend/resume, HDMI out, gamepad (Bluetooth).
* **Risks:** disk wipe safety (explicit confirm + target disk shown), Secure Boot, proprietary firmware licences, image size, handheld-specific kernels/quirks.

---

# Public release: the "Install Code" interface (dual boot or Code-only) - design only, nothing built yet

Status: **a plan, not code.** Nothing here may be implemented until the design is reviewed, and nothing must be tried on a real machine
until it has passed VM testing (see *Testing*). Partitioning is the one thing in this project that can destroy someone's data, so the rule
for every section below is: **read-only until the person has confirmed, then do the smallest change, with a way back where one exists.**

## 1. What the person sees (controller friendly, same look as Code)

A full-screen "Install Code" app that runs from the live USB (Code's own QML screens, on-screen keyboard, big buttons, Esc / B = back).
Pages, in order. Every page is read-only until page 7.

1. **Welcome.** What Code is, what the next pages do, "Nothing is changed until you confirm on the last page."
2. **Look at this computer** (read only): firmware (UEFI / legacy BIOS), Secure Boot on/off, internal disks (name, size, free space), what is on them
   (Windows? Linux? BitLocker? Fast Startup / hibernation file?), RAM, battery / power connected (laptops: refuse to start on battery below ~40 %).
3. **Choose how to install** - two big cards, plus a third "Try Code from the USB first" card (live session, no install, the safest default):
   - **Alongside Windows (dual boot)** - keeps Windows and all files; shrinks the Windows partition to make room; adds a boot menu entry for Windows.
   - **Code only** - **erases the whole disk you pick** and uses it for Code.
   - Each card says in plain words what happens, how long it takes, and what the worst case is.
4. **Choose the disk (and size).** Dual boot: a bar showing Windows | Code | free with a slider (minimum 40 GB, recommended 100 GB+; the slider can
   never go below what Windows needs plus a safety margin). Code only: a list of disks; the one with Windows / other data is marked in red; the installer USB itself is hidden.
5. **Account and basics:** computer name, user name, password (typed with the on-screen keyboard), WiFi, time zone, keyboard layout, optional disk encryption.
6. **Review** - a plain list of exactly what will be done ("Shrink partition C: from 476 GB to 300 GB", "Create 176 GB for Code", "Add Windows to the boot menu").
7. **Confirm** - a separate page: the warning text for the chosen mode, a tick box ("I have backed up what I care about"), and for Code-only the person must **type the disk's name** (e.g. `nvme0n1`) to continue.
   Only after this page does anything write to a disk. A big **Cancel - change nothing** button is the default focus.
8. **Installing** (progress, no cancel in the middle of the point-of-no-return steps, honest messages) -> **Done: restart** (installer USB can be removed).

Warnings (fixed text, not hidden in small print):
- Dual boot: "Windows is shrunk, not erased. Resizing can fail, and any disk operation has a small risk of data loss. Back up first. Turn off BitLocker / Windows Fast Startup first."
- Code only: "Everything on <disk> (<size>, <model>) will be erased, including Windows, and cannot be recovered."
- "Code is free software with no warranty." (links to LICENSE).

## 2. How the installer works (recommended approach)

**Do not write a partitioner.** Reuse what millions of installs have exercised, and wrap it:

- **Option A (recommended for the first public release): a guided wrapper around Linux Mint's / Ubuntu's own installer (Ubiquity on Mint 21/22, Calamares where used).** Code's "Install Code" screens
  collect the choices above, run the read-only inspection itself, and then drive the distro installer *non-interactively* (a preseed / config file generated from the choices, with the
  partition plan already decided) so the distro's proven code does the partitioning, copying, bootloader and initramfs. Code then adds its own post-install step (a chroot script):
  install Code to `/opt`/`~/.local`, enable the kiosk session (existing `kiosk.py` scripts), quiet boot (existing `quietboot.py`), user and autologin.
  Pros: smallest custom code touching disks, hardware / Secure Boot handled by the distro. Cons: the distro installer's automation hooks differ between Mint versions - pin one release (Mint 22 / Ubuntu 24.04 base, as in the plan above).
- **Option B (later): Calamares as the front end** with a Code-branded theme and a custom module for the post-install step. Calamares already has partitioning (KDE Partition Manager core, `kpmcore`), "install alongside" and "erase disk" modes and a
  proven GRUB module. Pros: no dependence on Ubiquity internals, full branding, controller support would need Qt/QML-skin work (Calamares is mouse/keyboard first). Cons: bigger integration job.
- **Option C (not recommended): a fully custom installer** (own `parted`/`sgdisk` + `debootstrap`). Maximum control, maximum risk; not for a public release.

Autoinstall (Subiquity, from the base plan above) stays the path for the **Code-only wipe** image on known hardware (the Dell); the guided interface is for the general public.

## 3. Safe partition resizing (dual boot)

All of this happens inside the distro installer / its libraries; Code's job is to **check the preconditions and refuse when they are not met**:

1. **Detect and read only:** `lsblk -J`, `blkid`, `parted -s print`, UEFI `efibootmgr -v`, `ntfsresize --info` / `ntfsinfo` on the Windows partition (reports how far it can shrink).
2. **Preconditions (refuse with a plain message and a "how to fix" page, never "try anyway"):**
   - The Windows NTFS partition is **clean** (not hibernated / Fast Startup, `ntfs-3g` reports no dirty flag) - otherwise: "Restart Windows, choose Shut down with Shift held (or run `powercfg /h off`), then try again."
   - **BitLocker / device encryption is off** (resizing an encrypted volume from Linux is not possible safely). Detect the BitLocker signature (`-FVE-FS-`) and stop with instructions to suspend / decrypt in Windows.
   - **`chkdsk` has been run** (offer instructions: Windows `chkdsk /f`; Code only reads the dirty flag).
   - Enough shrinkable space: requested Code size <= (free space reported by `ntfsresize --info`) minus a margin (10 % or 5 GB, whichever is larger). Windows' own unmovable files can limit this; the page then explains defragmenting in Windows.
   - GPT disk, UEFI boot with an existing EFI System Partition (ESP). MBR / legacy BIOS dual boot is a separate, riskier path: **unsupported in v1** (offer Code-only or Live USB).
   - No more than the partition layout can hold (GPT: 128 entries; no extended-partition tricks).
3. **Order of operations** (all after the Confirm page): (a) an **automatic backup** of the partition table (`sgdisk --backup=/target/gpt.bak` and `sfdisk -d`) and a copy of the Windows ESP / BCD to the USB or `/boot/efi/EFI/code-backup/`;
   (b) `ntfsresize --no-action` (dry run) must succeed; (c) the real `ntfsresize` then partition-table shrink - **the filesystem is shrunk first, then the partition, never the other way round**; (d) create the new partitions in the freed space (root ext4, optional swap file, **reuse** the existing ESP, never reformat it);
   (e) install; (f) verify (see below). Each step's output goes to a log shown on screen and saved to the new system (`/var/log/code-installer.log`) and to the USB.
4. **Never** resize while the machine is on battery below the threshold, and block closing the lid / suspend during the operation.
5. **Rollback story (honest):** before step (c) everything is reversible (nothing written). After (c) the filesystem is already shrunk: if the later install fails, the shrunk Windows still boots and the person is told so; the free space can be handed back by `Code > Installer > Undo` or from Windows Disk Management (extend volume). A power cut *during* `ntfsresize` can corrupt NTFS; this is the single largest risk, and the reason for the battery rule, the dry run and the "back up first" confirmation.

## 4. GRUB and the Windows boot entry

- Install GRUB in **UEFI mode into the existing ESP** at `\EFI\code\` (or `\EFI\ubuntu\` as the distro does), via `grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=Code`, and register it with `efibootmgr` **without deleting** Windows' `Boot Manager` entry or touching `\EFI\Microsoft\Boot\`.
- `os-prober` (enabled in dual-boot mode: `GRUB_DISABLE_OS_PROBER=false`) finds "Windows Boot Manager" and `update-grub` writes its menu entry (chainload of `\EFI\Microsoft\Boot\bootmgfw.efi`). The Code installer **checks the entry exists** in `grub.cfg` as a verification step; if not it writes a fallback `40_custom` entry (`chainloader /EFI/Microsoft/Boot/bootmgfw.efi` on the ESP by UUID).
- **Default entry = Code**; the menu shows for 5 s (not hidden) in dual boot, so Windows is always one key press away. The existing *Quiet boot* feature already refuses to hide the menu when a real Windows is present - the installer keeps that rule.
- Firmware boot order: Code's entry first, Windows Boot Manager kept second; the person can switch in the firmware boot menu (F12) - this fallback is explained on the Done page.
- **Secure Boot:** use the distro's signed shim + GRUB (Ubuntu / Mint ship them); no custom-signed binaries in v1. If Secure Boot is on and the distro shim is unavailable, the installer says so and stops before changing anything.
- Windows updates can reorder the firmware boot order or replace the boot entry; docs include "Repair: boot the Code USB > Repair boot menu" (re-runs `grub-install` + `update-grub`, read-only inspection first).

## 5. Code-only mode (whole disk)

- Lists internal disks only (the installer USB is excluded); shows model, size, and what is on it. Requires **typing the disk name** on the Confirm page.
- Creates GPT: ESP (512 MB, FAT32), root (ext4, optional LUKS), no swap partition (swap file / zram). Deletes the Windows boot entry? **No** - the installer does not touch the firmware's other entries; stale ones can be removed from the Quiet boot / Settings page (already handled for the stale "Windows Boot Manager" menu entry).
- Existing 0.4.x kiosk and quiet-boot scripts run in the post-install chroot step, so the result is the same Code-only session users already get.

## 6. What must never happen (hard rules, each with a test)

- No write to any disk, partition table, firmware variable or the ESP before the Confirm page's explicit confirmation (tested: a fake `parted` / `sgdisk` / `ntfsresize` / `efibootmgr` that records calls; the call log must be empty until confirmation).
- No "automatic" mode: the installer never starts by itself from the USB's autorun; the first boot menu entry is "Try Code (no changes)".
- The installer USB's own disk is never offered as a target; removable disks are not offered in Code-only mode unless "show external disks" is ticked.
- Any failed precondition = a stop with plain words, not a warning that can be clicked through.
- Windows partitions are only ever shrunk by a size the dry run accepted; never formatted; the ESP is never reformatted in dual boot.

## 7. Testing needs (before anyone outside the project runs it)

1. **Unit tests** of the decision logic with fake `lsblk` / `parted` / `ntfsresize` output (BitLocker, dirty NTFS, hibernated, MBR, not enough space, USB disk hidden, exact slider limits). Pure Python, runs in CI like the current suite.
2. **VM matrix** (QEMU + OVMF, scripted via the autoinstall / preseed path, screenshot assertions like the base plan): (a) blank disk Code-only; (b) a Windows 10/11 evaluation-style image (or a Windows-like NTFS + ESP + BCD fixture) with free space -> dual boot -> both entries boot; (c) BitLocker / hibernated refusal; (d) low-space refusal; (e) power-off in the middle of the resize (does Windows still boot? what do we tell the person?); (f) Secure Boot on (OVMF with keys) and off; (g) legacy BIOS refusal.
3. **Real hardware**, in this order, only after 1 and 2 pass: a spare machine with a throwaway Windows, then the Dell Latitude 5420 (only if the owner has backups and says so); document exact results - what was tested and what was not.
4. **Honest unknowns:** Windows' unmovable files limiting the shrink, vendor firmware that ignores `efibootmgr` order, Fast Startup on some OEM images, Intel RST / RAID-mode disks (Linux cannot see them - detect and stop with instructions to switch SATA mode, which itself can break Windows), BitLocker auto-enabled on many new laptops, Secure Boot / dbx updates changing what signed GRUB boots.

## 8. Risks and what we say about them

Disk operations can lose data even when done correctly; a power cut during a resize is the worst case; Windows updates can overwrite boot settings; some laptops (RAID / Intel RST, vendor-locked Secure Boot, ARM) are not supported. The installer, the README and the release notes say this plainly,
the licence is "free, no warranty", and the first public version ships as **"beta - back up first"** with the live-USB "Try Code" mode as the recommended first step.

## 9. Suggested milestones (small, each shippable and testable)

1. Read-only **"Check this computer"** page in the live session (disks, firmware, Windows / BitLocker / dirty / Fast Startup detection, partition plan preview) - no installer, no writes; safe to test on real machines.
2. Decision engine + plan renderer with the full test matrix from section 7.1; "Review" and "Confirm" pages wired to fakes only.
3. Option A wrapper for **Code-only** in a VM; then dual boot in a VM; then the repair page.
4. Beta image + USB writer docs; hardware tests as in 7.3; public beta only after those results are written down.
