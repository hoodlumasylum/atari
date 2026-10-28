# Atari OS - design plan (not built yet)

Goal: a flashable USB image that wipes a machine and installs a minimal Linux that boots straight into Atari (no desktop). First target: Dell Latitude 5420. Later: tablets / handhelds.

* **Base:** Ubuntu 24.04 LTS minimal (same package base as Linux Mint 22, so every Atari path - Flatpak, apt, pkexec, LightDM - behaves as in the app today). Built with `live-build` (reproducible, scriptable in CI); Cubic only for quick experiments.
* **Installer:** Ubuntu Subiquity autoinstall (cloud-init `user-data`) on the live image: wipes the chosen disk (default: the single internal NVMe, confirmed on screen), GPT + EFI, ext4 (+ optional LUKS), creates user `atari` with auto-login.
* **Session:** LightDM or plain `getty` autologin + `startx`/`cage` -> Atari full screen; reuse the 0.3.2 session script (crash loop falls back to a text console shell, not a desktop). Tiny WM (openbox) or a Wayland kiosk compositor (`cage`) later.
* **Packages:** `flatpak` + Flathub pre-configured, `pipewire-pulse`, `mesa-vulkan-drivers`, `intel-media-va-driver`, `network-manager`, firmware (`linux-firmware`, Intel wifi/BT for the 5420), `steam-devices`, `xemu`/emulators installed on demand by Atari's own Install buttons (keeps the image small, legal and current).
* **First boot / wifi:** an Atari "Welcome" screen: pick wifi (nmcli through a controller-friendly list + on-screen keyboard, which Atari already has), timezone, then the existing getting-started checklist.
* **Updates:** Atari's in-app updater; OS security updates via `unattended-upgrades`.
* **Flashing:** `dd`/balenaEtcher/`rpi-imager`-style; publish `atari-os-<ver>.iso` + SHA256SUMS on GitHub Releases; document `sha256sum -c` and a safety warning.
* **Testing:** (1) CI: build in a container, boot in QEMU/OVMF headless, screenshot via VNC and assert the Atari window; (2) install into a VM disk with autoinstall; (3) Latitude 5420 test only on a spare machine, never before (1)+(2) pass; (4) hardware checklist: wifi, sound, touchpad/keyboard, Secure Boot (signed shim from Ubuntu), suspend/resume, HDMI out, gamepad (Bluetooth).
* **Risks:** disk wipe safety (explicit confirm + target disk shown), Secure Boot, proprietary firmware licences, image size, handheld-specific kernels/quirks.
