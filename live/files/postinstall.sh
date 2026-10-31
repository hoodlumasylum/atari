#!/bin/sh
# Runs inside the newly installed system at the end of the install (Ubiquity success_command).
# The PC then starts straight into CodeAque full screen for the user created during the install.
U=$(getent passwd 1000 | cut -d: -f1)
[ -n "$U" ] || exit 0
chown -R 1000:1000 /opt/codeaque 2>/dev/null || true
if [ -f /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf ]; then
    sed -i "s/^autologin-user=.*/autologin-user=$U/" /etc/lightdm/lightdm.conf.d/90-atari-kiosk.conf
fi
rm -f /etc/lightdm/lightdm.conf.d/95-codeaque-live.conf /etc/xdg/autostart/codeaque-install.desktop \
      /usr/share/applications/codeaque-install-menu.desktop
systemctl disable codeaque-live-mode.service >/dev/null 2>&1 || true
exit 0
