#!/bin/sh
# Run on the UNO Q (Debian): copies the kiosk to /opt/blinko and enables the autologin session.
# Prerequisites: the GigaDisplay DTB/panel setup of the uno_flirone project (display + touch),
# python3-gi, gir1.2-gtk-3.0, gstreamer1.0-plugins-{base,good}, python3-numpy, gcc, v4l-utils.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
sudo mkdir -p /opt/blinko
sudo cp -r "$HERE/blinko_kiosk.py" "$HERE/sources.py" "$HERE/core" /opt/blinko/
sudo cp "$HERE/deploy/blinko-kiosk-session.sh" /opt/blinko/ && sudo chmod +x /opt/blinko/blinko-kiosk-session.sh /opt/blinko/blinko_kiosk.py
sudo cp "$HERE/deploy/blinko-kiosk.desktop" /usr/share/xsessions/
sudo cp "$HERE/deploy/60-blinko-kiosk.conf" /etc/lightdm/lightdm.conf.d/
echo "installed: reboot to start the kiosk (or run /opt/blinko/blinko_kiosk.py --windowed from an X session)"
