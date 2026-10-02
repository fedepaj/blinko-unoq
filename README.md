# blinko-unoq — Blinko receiver on the Arduino UNO Q + GigaDisplay

A kiosk that reads the LEDs of the boards in front of a camera and shows their messages. It
runs the same C receiver as the phone apps (`core/`, through ctypes), takes its frames from
a CSI camera on the Media Carrier (GStreamer `v4l2src`, BGRx) and draws a fullscreen GTK
console on the GigaDisplay: the camera preview with a marker on every light, the links
between the lights of one board, the board ids, the messages and a touch source filter.
The same script runs on a computer on a `.rsrec` recording, without camera or display.
Layout and boot setup follow the `uno_flirone` kiosk (autologin → X session → app).

## Requirements

- On the UNO Q (Debian): the GigaDisplay DTB/panel setup of the `uno_flirone` project
  (display + touch), lightdm, and the packages installed by `make deps` (PyGObject with
  GTK 3 and cairo, GStreamer base/good plugins, numpy, gcc, v4l-utils).
- On a computer, for recordings: Python 3 with numpy, `lz4` for compressed recordings, and
  a C compiler as `cc`.
- The `core/` submodule checked out (`git submodule update --init`). The receiver is
  compiled into `core/build/` the first time it is used.

## Install on the board

```
make deps              # apt packages
deploy/install.sh      # copies the kiosk to /opt/blinko, builds the receiver, enables the session
```

`install.sh` copies `blinko_kiosk.py`, `sources.py` and `core/` to `/opt/blinko`, compiles
the receiver there, installs the X session `blinko-kiosk` and the lightdm configuration that
logs the user `arduino` into it. After a reboot the kiosk starts by itself.

## Run

```
make headless REC=rec.rsrec                               # a recording, as fast as possible, messages on stdout
blinko_kiosk.py --source rec.rsrec --headless --fast      # the same
blinko_kiosk.py --source rec.rsrec --windowed             # a recording in a loop, in a window
blinko_kiosk.py --device /dev/video0 --exposure 2 --exposure-us 40 --row-us 20    # on the board: camera, fullscreen
```

Headless, every message is a line `[LEVEL] src<N> slot<M> text` on stdout, and twice a
second a status line (fps, packets per second, tracks) goes to stderr. The exit status is 1
when the frame source fails.

On the display: the left half of the top bar cycles the source filter (All, #1, #2, …),
the right half clears the console and restarts the receiver, and a tap on the upper or
lower half of the console scrolls it.

## Options

| option | default | |
|---|---|---|
| `--source FILE` | | a `.rsrec` recording instead of the camera |
| `--device DEV` | `/dev/video0` | V4L2 camera |
| `--width N`, `--height N` | 1920, 1080 | frame size asked of the camera |
| `--fps N` | 30 | frame rate asked of the camera |
| `--exposure V` | | V4L2 `exposure_absolute` (sets `exposure_auto=1` too); units depend on the driver |
| `--gain V` | | V4L2 `gain` |
| `--control NAME=VALUE` | | any other V4L2 control; repeatable |
| `--exposure-us US` | the recording's | exposure time in µs, for the receiver |
| `--row-us US` | | time between two rows of a frame in µs, for the receiver |
| `--headless` | | no display: messages on stdout |
| `--seconds S` | 0 (no limit) | headless: stop after S seconds |
| `--fast` | | recording: no real-time pacing |
| `--windowed` | | a window instead of fullscreen |
| `--history FILE` | `~/.blinko/history.json` | where the messages are kept between runs |

The V4L2 controls are applied with `v4l2-ctl` before the camera starts; the names and units
of a sensor are listed by `v4l2-ctl -d /dev/video0 --list-ctrls`. A control that cannot be
applied is reported on stderr and the camera starts anyway.

## Exposure and row time

Exposure is the critical setting: it should stay below the boards' T (60 µs by default; the
phones expose 15–57 µs). Set the sensor's shortest exposure with `--exposure` and, if the
sensor cannot go short enough, use a longer T on the boards (`chip 90`, with `rep 2`).

The receiver also wants to know the camera: `--row-us` is the time between two rows of the
frames as they are delivered (a binned or scaled mode has a longer row time than the
sensor's), `--exposure-us` the exposure time. With both, the detector is told the exposure
in rows (exposure / row time); with the row time alone the receiver can still predict the
phase of a light's signal from one frame to the next. Without them the detector assumes an
exposure of half a chip. A wrong row time is worse than none: the exposure in rows comes
out wrong and packets stop decoding. A recording carries its exposure, so `--row-us` is
enough for it.

## Environment

| variable | read by | |
|---|---|---|
| `BLINKO_VIDEO` | the X session (`deploy/blinko-kiosk-session.sh`) | camera device, default `/dev/video0` |
| `BLINKO_ARGS` | the X session | extra options for `blinko_kiosk.py`, e.g. `--exposure 2 --row-us 20` |
| `RS_CFLAGS` | `core/tools/rscore.py` | extra compiler flags for the receiver |
| `RS_LIB` | `core/tools/rscore.py` | a receiver library already built, used instead of compiling |
| `PY` | `make headless` | the Python interpreter, default `python3` |

## Limits

- Not verified on the UNO Q: the camera pipeline, the V4L2 control names of the sensor, the
  display and touch session and `deploy/install.sh`. What is exercised is the receiver on
  recordings, headless, on a computer.
- The row time of the sensor is not measured by the kiosk: it has to be given.
- `/opt/blinko` belongs to root: after a change of `core/`, run `deploy/install.sh` again
  so the receiver is rebuilt there.
