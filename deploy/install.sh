#!/bin/sh
# Run on the UNO Q (Debian): copies the kiosk to /opt/blinko and enables the autologin session.
# Prerequisites: the GigaDisplay DTB/panel setup of the uno_flirone project (display + touch)
# and the packages of `make deps` (python3-gi, gir1.2-gtk-3.0, gstreamer1.0-plugins-{base,good},
# python3-numpy, gcc, v4l-utils).
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
sudo mkdir -p /opt/blinko
sudo cp -r "$HERE/blinko_kiosk.py" "$HERE/sources.py" "$HERE/core" /opt/blinko/
sudo cp "$HERE/deploy/blinko-kiosk-session.sh" /opt/blinko/ && sudo chmod +x /opt/blinko/blinko-kiosk-session.sh /opt/blinko/blinko_kiosk.py
# rscore compiles the receiver into core/build/ the first time it is imported. The kiosk runs as
# the autologin user, who cannot write under /opt/blinko: import it once here, as root, so the
# session finds the library already built (and a compiler error shows now, not on the display).
sudo python3 -c 'import sys; sys.path.insert(0, "/opt/blinko/core/tools"); import rscore'
sudo cp "$HERE/deploy/blinko-kiosk.desktop" /usr/share/xsessions/
sudo mkdir -p /etc/lightdm/lightdm.conf.d      # absent on a lightdm that was never configured
sudo cp "$HERE/deploy/60-blinko-kiosk.conf" /etc/lightdm/lightdm.conf.d/
echo "installed: reboot to start the kiosk (or run /opt/blinko/blinko_kiosk.py --windowed from an X session)"
