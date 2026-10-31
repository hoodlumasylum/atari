# CodeAque Live USB

A USB stick that starts the PC straight into CodeAque. You can **try** it without changing anything on the PC,
or **install** it on the PC's internal drive next to Windows.

It is Linux Mint 22.3 (Cinnamon) with CodeAque already inside. No games, ROMs, BIOS files, firmware or keys are included.

## What you need

* A USB stick of **16 GB or more** (the image is about 3 GB; the rest of the stick is used to save your settings and games in Try mode).
  Everything on the stick is deleted when you write the image.
* A Windows PC to write the stick, and about 10 minutes.

## 1. Download

From the release page download **both** `codeaque-live-<version>.iso.part1` and `.part2` files and `SHA256SUMS` into the same folder
(for example `Downloads`). GitHub only allows files up to 2 GB, so the image is cut into parts.

## 2. Join the parts (Windows)

1. Open the `Downloads` folder, click the address bar at the top, type `cmd` and press Enter. A black window opens in that folder.
2. Type this and press Enter (version number as in the file names):

       copy /b codeaque-live-0.5.9.iso.part1 + codeaque-live-0.5.9.iso.part2 codeaque-live-0.5.9.iso

3. Optional but recommended, check the file is perfect:

       certutil -hashfile codeaque-live-0.5.9.iso SHA256

   The long number it prints must be the same as the `codeaque-live-0.5.9.iso` line in `SHA256SUMS`.

(On Linux: `cat codeaque-live-0.5.9.iso.part* > codeaque-live-0.5.9.iso` and `sha256sum -c SHA256SUMS --ignore-missing`.)

## 3. Write the stick with Rufus (Windows)

1. Download **Rufus** from rufus.ie (the normal or portable version) and open it. Say Yes if Windows asks.
2. Plug in the USB stick. **Device**: pick the stick (check the size so you do not pick another drive).
3. **Boot selection**: click **SELECT** and choose `codeaque-live-0.5.9.iso`.
4. **Persistent partition size**: drag the slider to the right (for example 8 GB or more). This is where Try mode keeps your
   settings, Wi-Fi and games between starts. Leave it at 0 and Try mode forgets everything at every start.
5. Leave **Partition scheme** (GPT) and **Target system** (UEFI) as Rufus sets them.
6. Click **START**. If Rufus asks "ISO image mode" or "DD image mode", choose **ISO image mode** (the recommended one).
   If it offers to download something extra (syslinux / GRUB files), say **Yes**.
7. Rufus warns that the stick will be wiped: click **OK**. When the bar says **READY**, close Rufus.

Without persistence, other tools (balenaEtcher, Ventoy, `dd`) work too.

## 4. Start the PC from the stick

1. Plug the stick into the PC and switch it on (or restart).
2. Straight away tap the boot menu key - often **F12** (Dell, Lenovo), **F8** (ASUS), **F9** (HP), **F11** (MSI) or **Esc**.
3. Pick the USB stick (it may appear twice; choose the one with **UEFI** in its name).

If Windows starts instead: in Windows hold **Shift** and click **Restart**, then *Troubleshoot > Advanced options > UEFI Firmware Settings*.

Secure Boot can stay on: the stick uses the same signed boot loader as Linux Mint.

## 5. The menu

| Entry | What it does |
|---|---|
| **Try CodeAque** (default, starts by itself after 8 seconds) | Starts CodeAque full screen from the stick. Nothing on the PC changes. |
| **Install CodeAque** | Starts the guided installer (see below). |
| **Try CodeAque (safe graphics)** | Same as Try, for screens that stay black or garbled. |
| **Boot from next drive / local drive** | Starts whatever is on the PC (usually Windows). |

## 6. Installing next to Windows (dual boot)

The installer first shows CodeAque's own warnings, then Linux Mint's installer (CodeAque is already inside it).

* **Back up first.** Copy anything important to another drive or the cloud.
* **BitLocker:** if the Windows drive is encrypted, the installer stops and says so. Turn BitLocker off in Windows first (or have your
  recovery key ready).
* **Fast Startup / hibernation:** if Windows was not fully shut down, the installer stops and tells you to start Windows, then hold
  **Shift** while clicking **Shut down** (or turn off Fast Startup in Control Panel > Power Options).
* On the **Installation type** page keep **Install CodeAque Live alongside Windows Boot Manager** (the first choice, already selected).
  If there is a slider, drag it to choose CodeAque's space (60 GB or more is good for games).
* **If that choice is not there, press Quit.** The installer did not see Windows, and the other choices can delete it.
* **Erase disk** deletes Windows and everything on the drive. Only choose it on a PC you want to give completely to CodeAque.
* **Something else** is for experts (your own partitions).
* Nothing on the drive changes until you press **Install Now** and confirm.

After the install, take the stick out and restart: a menu asks **Linux Mint** (CodeAque) or **Windows Boot Manager**. CodeAque starts
by itself, full screen, logged in automatically.

## After starting

* **Emulators are not on the stick** (to keep it small). The first time, connect to the internet and use
  *Settings > Emulators > Install emulators and apps*. In Try mode they are kept only if the stick has persistence.

* **Wi-Fi:** CodeAque's Wi-Fi button (top right), or Settings.
* **Controllers:** Xbox and PlayStation pads by USB work at once; for Bluetooth use *Controllers > Pair a controller*.
* **Updates:** Settings > Update CodeAque (CodeAque itself). Linux Mint's own updates: in Install mode use Mint's Update Manager.

## What was tested, and what was not

Tested in virtual machines (QEMU) only:

* UEFI with Secure Boot on (Microsoft keys): boots, shows the menu, the CodeAque start-up screen, and lands in CodeAque full screen.
* UEFI without Secure Boot, and old-style BIOS: both boot to CodeAque; the BIOS menu starts Try CodeAque by itself after 8 seconds.
* Persistence: a stick image with a `casper-rw` partition keeps settings after a restart (first-run setup not shown again).
* Install mode: the warnings, Windows detection (a pretend Windows partition) and the installer's "alongside Windows Boot Manager" choice.
  See the release notes for how far the install itself got.

Not tested: real PCs and real USB sticks, Rufus itself, Wi-Fi chips, Bluetooth pads, a real Windows (BitLocker, Fast Startup),
and every graphics card.
