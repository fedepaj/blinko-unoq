# blinko-unoq — Blinko receiver on the Arduino UNO Q + GigaDisplay

The same C receiver as the phone apps (`core/`, via ctypes), a CSI camera on the Media
Carrier as the frame source (GStreamer `v4l2src`, BGRx) and a fullscreen GTK console on
the GigaDisplay with the markers of every light, the links between lights of one board,
the board ids and a touch source filter. Layout and boot setup follow the `uno_flirone`
kiosk (autologin → X session → app).

```
blinko_kiosk.py --source rec.rsrec --headless --fast    # on a computer: a recording, messages on stdout
blinko_kiosk.py --device /dev/video0 --exposure 2       # on the board: camera, fullscreen
deploy/install.sh                                       # on the board: /opt/blinko + autologin session
```

Exposure is the critical setting: the chips are 30 µs, the phones expose 15 µs. Set the
sensor's shortest exposure with `--exposure` (V4L2 `exposure_absolute`, units depend on
the driver: `v4l2-ctl -d /dev/video0 --list-ctrls`) and, if the sensor cannot go short
enough, use a longer chip on the boards (`chip 45`).

Status: written against the recordings; camera and display still to be verified on the
board (see the umbrella roadmap).
