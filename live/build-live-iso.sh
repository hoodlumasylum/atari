#!/bin/bash
# Build the CodeAque Live USB image: Linux Mint 22.3 Cinnamon (official ISO, signature + checksum checked) with CodeAque
# preinstalled, booting straight into CodeAque full screen. Needs: sudo, xorriso, squashfs-tools, curl, gpg, ~25 GB free.
#   sudo -E ./live/build-live-iso.sh <workdir> <codeaque-source-tarball> <version>
# Nothing third-party is added except Linux Mint itself and free packages from its own archive; no games, BIOS, firmware or keys.
set -euo pipefail
W=${1:?workdir}; SRC=${2:?codeaque tarball}; VER=${3:?version}
HERE=$(cd "$(dirname "$0")" && pwd)
MINT=22.3; BASE=linuxmint-$MINT-cinnamon-64bit.iso
MIRROR=${MINT_MIRROR:-https://mirror.rackspace.com/linuxmint/iso/stable/$MINT}
UBUNTU=${UBUNTU_MIRROR:-https://archive.ubuntu.com/ubuntu}
OUT=$W/codeaque-live-$VER.iso
mkdir -p "$W"; cd "$W"

say() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------- 1. the official Linux Mint ISO, verified
if [ ! -f "$BASE.ok" ]; then
    say "Getting $BASE"
    curl -fsSL -o sha256sum.txt "$MIRROR/sha256sum.txt"; curl -fsSL -o sha256sum.txt.gpg "$MIRROR/sha256sum.txt.gpg"
    gpg --batch --keyserver hkps://keyserver.ubuntu.com --recv-keys 27DEB15644C6B3CF3BD7D291300F846BA25BAE09
    gpg --batch --verify sha256sum.txt.gpg sha256sum.txt
    [ -f "$BASE" ] || curl -fL --retry 10 -C - -o "$BASE" "$MIRROR/$BASE"
    grep " \*$BASE\$" sha256sum.txt | sed 's/ \*/  /' | sha256sum -c -
    touch "$BASE.ok"
fi

# ---------------------------------------------------------------- 2. unpack
say "Unpacking"
sudo rm -rf iso root
mkdir iso
xorriso -osirrox on -indev "$BASE" -extract / iso >/dev/null 2>&1
chmod -R u+w iso
sudo unsquashfs -q -d root iso/casper/filesystem.squashfs >/dev/null

# ---------------------------------------------------------------- 3. CodeAque inside (chroot)
say "Installing CodeAque $VER into the image"
cleanup() { for m in run sys proc dev/pts dev; do sudo umount -l "root/$m" 2>/dev/null || true; done; }
trap cleanup EXIT
for m in dev dev/pts proc sys run; do sudo mount --bind "/$m" "root/$m"; done
sudo cp root/etc/resolv.conf root/etc/resolv.conf.codeaque 2>/dev/null || true
sudo rm -f root/etc/resolv.conf; sudo cp -L /etc/resolv.conf root/etc/resolv.conf
sudo mkdir -p root/etc/apt/codeaque-saved
sudo sh -c "mv root/etc/apt/sources.list.d/*.list root/etc/apt/codeaque-saved/ 2>/dev/null || true"
echo "deb $UBUNTU noble main restricted universe multiverse
deb $UBUNTU noble-updates main restricted universe multiverse
deb $UBUNTU noble-security main restricted universe multiverse" | sudo tee root/etc/apt/sources.list.d/codeaque-build.list >/dev/null
sudo mkdir -p root/tmp/codeaque-src
sudo tar xzf "$SRC" -C root/tmp/codeaque-src --strip-components=1
sudo chroot root /bin/bash -euo pipefail -c '
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
apt-get update -q
apt-get install -y -q --no-install-recommends openbox zenity xdotool wmctrl python3-venv python3-pip bluez btmgmt \
    libxcb-cursor0 libxkbcommon-x11-0 >/dev/null || apt-get install -y -q --no-install-recommends openbox zenity xdotool wmctrl \
    python3-venv python3-pip bluez libxcb-cursor0 libxkbcommon-x11-0 >/dev/null
HOME=/etc/skel ATARI_INSTALL_DIR=/opt/codeaque ATARI_ALLOW_ROOT_BUILD=1 bash /tmp/codeaque-src/install.sh --yes </dev/null
test -x /opt/codeaque/.venv/bin/python
/opt/codeaque/.venv/bin/python -c "import atarilauncher, PySide6; print(\"CodeAque\", atarilauncher.__version__)"
chown -R 1000:1000 /opt/codeaque
apt-get clean
'
# CodeAque-only session for the live user (the same files CodeAque > Settings > CodeAque-only mode writes)
sudo chroot root /opt/codeaque/.venv/bin/python -c "
from atarilauncher import kiosk; from pathlib import Path
open('/tmp/kiosk.sh','w').write(kiosk.enable_script('codeaque', run_sh=Path('/opt/codeaque/run.sh'), desktop_exec='cinnamon-session'))"
sudo chroot root sh /tmp/kiosk.sh
# Try / Install mode, the guided installer, the after-install step
sudo install -m 755 "$HERE/files/codeaque-live-mode" root/usr/local/sbin/codeaque-live-mode
sudo install -m 644 "$HERE/files/codeaque-live-mode.service" root/etc/systemd/system/codeaque-live-mode.service
sudo ln -sf /etc/systemd/system/codeaque-live-mode.service root/etc/systemd/system/multi-user.target.wants/codeaque-live-mode.service
sudo install -m 755 "$HERE/files/codeaque-install" root/usr/local/bin/codeaque-install
sudo install -m 644 "$HERE/files/codeaque-install.desktop" root/etc/xdg/autostart/codeaque-install.desktop
sudo install -m 644 "$HERE/files/codeaque-install-menu.desktop" root/usr/share/applications/codeaque-install-menu.desktop
sudo mkdir -p root/opt/codeaque-live
sudo install -m 755 "$HERE/files/postinstall.sh" root/opt/codeaque-live/postinstall.sh
mkdir -p iso/preseed; cp "$HERE/files/codeaque.seed" iso/preseed/codeaque.seed
# CodeAque boot splash (Plymouth) instead of the Mint logo
sudo chroot root /opt/codeaque/.venv/bin/python - <<'PY'
from atarilauncher import quietboot
from pathlib import Path
import shutil, subprocess
d = Path("/usr/share/plymouth/themes/code"); d.mkdir(parents=True, exist_ok=True)
(d / "code.plymouth").write_text(quietboot.render_plymouth(str(d)))
shutil.copy(quietboot.logo_path(), d / "code-logo.png")
(d / "code.script").write_text(quietboot.PLYMOUTH_SCRIPT)
subprocess.run(["update-alternatives", "--install", "/usr/share/plymouth/themes/default.plymouth", "default.plymouth",
                str(d / "code.plymouth"), "200"], check=True)
subprocess.run(["update-alternatives", "--set", "default.plymouth", str(d / "code.plymouth")], check=True)
PY
sudo chroot root sh -c 'update-initramfs -u -k all >/dev/null 2>&1 || update-initramfs -u'
# put the build-only package sources back the way Mint ships them
sudo rm -f root/etc/apt/sources.list.d/codeaque-build.list
sudo sh -c "mv root/etc/apt/codeaque-saved/*.list root/etc/apt/sources.list.d/ 2>/dev/null || true"; sudo rmdir root/etc/apt/codeaque-saved
sudo chroot root apt-get update -q >/dev/null 2>&1 || true
sudo rm -rf root/tmp/* root/var/lib/apt/lists/*_codeaque* root/root/.cache root/etc/skel/.cache
sudo rm -f root/etc/resolv.conf; [ -e root/etc/resolv.conf.codeaque ] && sudo mv root/etc/resolv.conf.codeaque root/etc/resolv.conf || sudo ln -sf ../run/systemd/resolve/stub-resolv.conf root/etc/resolv.conf
cleanup; trap - EXIT

# ---------------------------------------------------------------- 4. new initrd + squashfs
say "Packing the file system (takes a while)"
K=$(ls root/boot/initrd.img-* | sort -V | tail -1)
sudo cp "$K" iso/casper/initrd.lz
sudo chroot root dpkg-query -W --showformat='${Package} ${Version}\n' | sudo tee iso/casper/filesystem.manifest >/dev/null
sudo du -sx --block-size=1 root | cut -f1 | sudo tee iso/casper/filesystem.size >/dev/null
sudo rm -f iso/casper/filesystem.squashfs
sudo mksquashfs root iso/casper/filesystem.squashfs -comp xz -b 1M -noappend -quiet
sudo chown -R "$(id -u)" iso

# ---------------------------------------------------------------- 5. boot menus
say "Boot menus"
UUID=$(sed -n 's/.*uuid=\([0-9a-f-]*\).*/\1/p' iso/isolinux/live.cfg | head -1)
COMMON="boot=casper uuid=$UUID username=codeaque hostname=codeaque"
cat > iso/boot/grub/grub.cfg <<G
loadfont unicode
set color_normal=white/black
set color_highlight=black/light-gray
set timeout=8
set default=0
menuentry "Try CodeAque" {
	set gfxpayload=keep
	linux	/casper/vmlinuz  $COMMON persistent iso-scan/filename=\${iso_path} quiet splash --
	initrd	/casper/initrd.lz
}
menuentry "Install CodeAque" {
	set gfxpayload=keep
	linux	/casper/vmlinuz  $COMMON codeaque.install file=/cdrom/preseed/codeaque.seed iso-scan/filename=\${iso_path} quiet splash --
	initrd	/casper/initrd.lz
}
menuentry "Try CodeAque (safe graphics)" {
	linux	/casper/vmlinuz  $COMMON persistent iso-scan/filename=\${iso_path} nomodeset nosplash --
	initrd	/casper/initrd.lz
}
if [ "\$grub_platform" = "efi" ]; then
menuentry "Boot from next drive" {
	exit 1
}
fi
G
cp iso/boot/grub/grub.cfg iso/boot/grub/loopback.cfg
cat > iso/isolinux/live.cfg <<L
label live
	menu label Try CodeAque
	menu default
	kernel /casper/vmlinuz
	append $COMMON persistent initrd=/casper/initrd.lz quiet splash --
label install
	menu label Install CodeAque
	kernel /casper/vmlinuz
	append $COMMON codeaque.install file=/cdrom/preseed/codeaque.seed initrd=/casper/initrd.lz quiet splash --
label safe
	menu label Try CodeAque (safe graphics)
	kernel /casper/vmlinuz
	append $COMMON persistent initrd=/casper/initrd.lz nomodeset nosplash --
label local
	menu label Boot from local drive
	COM32 chain.c32
	APPEND hd0
L
sed -i 's/^menu title .*/menu title CodeAque Live/; s/^timeout .*/timeout 80/' iso/isolinux/isolinux.cfg iso/isolinux/menu.cfg iso/isolinux/stdmenu.cfg 2>/dev/null || true
sed -i 's/Welcome to Linux Mint.*/CodeAque Live/' iso/isolinux/*.cfg
python3 "$HERE/make_splash.py" root/opt/codeaque/atarilauncher/assets/codeaque-logo.png iso/isolinux/splash.png
echo "CodeAque Live $VER (based on Linux Mint $MINT)" > iso/.disk/info

# ---------------------------------------------------------------- 6. the ISO (same boot records as Mint's: UEFI with the signed shim + legacy BIOS)
say "Writing $OUT"
(cd iso && find . -type f ! -name md5sum.txt ! -path './isolinux/*' ! -path './boot/*' -print0 | xargs -0 md5sum > md5sum.txt)
rm -f "$OUT"
xorriso -indev "$BASE" -outdev "$OUT" -volid "CODEAQUE_LIVE" -boot_image any replay \
    -map iso / 2>&1 | tail -3 || true
[ -s "$OUT" ] || { echo "ISO was not written"; exit 1; }
ls -la "$OUT"
