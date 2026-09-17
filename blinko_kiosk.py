#!/usr/bin/env python3
"""Blinko kiosk for the Arduino UNO Q + GigaDisplay: reads the LEDs of the boards in front of
the CSI camera with the same C receiver as the phone apps and shows the console on the display.

  blinko_kiosk.py                              camera (/dev/video0), fullscreen GTK UI
  blinko_kiosk.py --source rec.rsrec --headless   development: a recording, messages on stdout
  blinko_kiosk.py --device /dev/video2 --exposure 1 --gain 4

The receiver (core/) is built on first run with the system compiler (`cc`), see core/tools/rscore.py.
"""
import argparse
import json
import os
import sys
import threading
import time
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "core", "tools"))

from rscore import _lib, Multi, LEVELS  # noqa: E402
import ctypes  # noqa: E402

_lib.rs_multi_track_group.restype = ctypes.c_int
_lib.rs_multi_track_group.argtypes = [ctypes.c_void_p, ctypes.c_int]

LEVEL_COLORS = {"DEBUG": (0.6, 0.6, 0.6), "INFO": (0.35, 0.85, 0.35), "WARN": (0.95, 0.85, 0.2), "ERROR": (1.0, 0.6, 0.2),
                "FATAL": (1.0, 0.3, 0.3), "STATUS": (0.3, 0.85, 0.95), "FAULT": (1.0, 0.3, 0.3)}
PALETTE = [(1.0, 0.6, 0.15), (0.3, 0.85, 0.3), (0.3, 0.8, 1.0), (1.0, 0.4, 0.7)]


class Console:
    """Messages (newest first), board ids, source filter; persisted to a JSON file."""

    def __init__(self, path, maxlen=2000):
        self.path, self.maxlen = path, maxlen
        self.messages = deque(maxlen=maxlen)     # dicts: t, slot, level, text, source
        self.board_ids = {}
        self.filter = 0
        self.lock = threading.Lock()
        try:
            with open(path) as f:
                d = json.load(f)
            self.messages.extend(d.get("messages", [])[:maxlen])
            self.board_ids = {int(k): v for k, v in d.get("boards", {}).items()}
        except Exception:
            pass

    def add(self, slot, level, text, source):
        m = {"t": time.time(), "slot": slot, "level": level, "text": text, "source": source}
        with self.lock:
            self.messages.appendleft(m)
            i = text.find("id=")
            if source > 0 and i >= 0 and len(text) >= i + 7:
                self.board_ids[source] = text[i + 3:i + 7]
        return m

    def visible(self):
        with self.lock:
            return [m for m in self.messages if self.filter == 0 or m["source"] == self.filter]

    def sources(self):
        with self.lock:
            ids = sorted({m["source"] for m in self.messages if m["source"] > 0})
            return [(i, self.board_ids.get(i)) for i in ids]

    def clear(self):
        with self.lock:
            self.messages.clear(); self.board_ids.clear()

    def save(self):
        with self.lock:
            d = {"messages": list(self.messages), "boards": {str(k): v for k, v in self.board_ids.items()}}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path + ".tmp", "w") as f:
                json.dump(d, f)
            os.replace(self.path + ".tmp", self.path)
        except Exception:
            pass


class Receiver:
    """Runs the multi-source receiver on a frame source in a thread; keeps the latest frame,
    tracks and stats for the UI."""

    def __init__(self, source, console, on_message=None):
        self.source, self.console, self.on_message = source, console, on_message
        self.multi = Multi()
        self.latest = None            # (bgrx ndarray, w, h)
        self.tracks = []
        self.fps = 0.0
        self.pkt_per_s = 0.0
        self.total_packets = 0
        self.lock = threading.Lock()
        self.stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        frames, pkts, t_last = 0, 0, time.time()
        for ts, a, w, h in self.source.frames():
            if self.stop:
                break
            n, msgs = self.multi.process(a, ts)
            tr = self.multi.tracks()
            for i, t in enumerate(tr):
                t["group"] = _lib.rs_multi_track_group(self.multi.buf, i)
            frames += 1; pkts += n; self.total_packets += n
            now = time.time()
            if now - t_last >= 1.0:
                self.fps, self.pkt_per_s = frames / (now - t_last), pkts / (now - t_last)
                frames, pkts, t_last = 0, 0, now
            with self.lock:
                self.latest = (a, w, h)
                self.tracks = tr
            for tid, slot, level, text in msgs:
                m = self.console.add(slot, LEVELS.index(level) if level in LEVELS else 7, text, tid)
                if self.on_message:
                    self.on_message(m)


def run_headless(receiver, console, seconds):
    def printer(m):
        lvl = LEVELS[m["level"]] if m["level"] < len(LEVELS) else "?"
        print("[%s] src%d slot%d %s" % (lvl, m["source"], m["slot"], m["text"]), flush=True)
    receiver.on_message = printer
    receiver.start()
    end = time.time() + seconds if seconds else None
    try:
        while receiver.thread.is_alive() and (end is None or time.time() < end):
            time.sleep(0.5)
            tr = " ".join("#%d%s(%s %dp)" % (t["group"], "" if t["group"] == t["id"] else "·%d" % t["id"], t["mode"], t["packets"]) for t in receiver.tracks)
            print("fps %.0f pkt/s %.0f %s" % (receiver.fps, receiver.pkt_per_s, tr), file=sys.stderr)
    except KeyboardInterrupt:
        pass
    receiver.stop = True
    console.save()


def run_gtk(receiver, console, fullscreen=True, canvas=(480, 800)):
    """Fullscreen touch UI: camera preview with markers on top, console below."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    import cairo

    W, H = canvas
    preview_h = H * 2 // 5

    class Kiosk(Gtk.Window):
        def __init__(self):
            super().__init__(title="Blinko")
            self.set_default_size(W, H)
            self.area = Gtk.DrawingArea()
            self.area.connect("draw", self.on_draw)
            self.area.add_events(4 | 256)   # BUTTON_PRESS | POINTER_MOTION
            self.area.connect("button-press-event", self.on_press)
            self.add(self.area)
            self.scroll = 0
            if fullscreen:
                self.fullscreen()
            self.show_all()
            GLib.timeout_add(66, self.tick)          # 15 Hz redraw is plenty for a console
            GLib.timeout_add(5000, lambda: (console.save(), True)[1])

        def tick(self):
            self.area.queue_draw()
            return True

        def on_press(self, widget, ev):
            if ev.y < 40 and ev.x < W / 2:           # source filter button: cycle All -> #1 -> #2 ...
                ids = [0] + [s[0] for s in console.sources()]
                console.filter = ids[(ids.index(console.filter) + 1) % len(ids)] if console.filter in ids else 0
            elif ev.y < 40:                           # clear button
                console.clear(); self.multi_reset()
            elif ev.y > preview_h:                    # console scrolling by tapping upper/lower half
                self.scroll = max(0, self.scroll + (-5 if ev.y < preview_h + (H - preview_h) / 2 else 5))
            return True

        def multi_reset(self):
            receiver.multi = Multi()

        def on_draw(self, widget, cr):
            cr.set_source_rgb(0.04, 0.05, 0.08); cr.paint()
            with receiver.lock:
                latest, tracks = receiver.latest, list(receiver.tracks)
            # preview: the BGRx frame is what cairo RGB24 wants on little-endian machines
            if latest is not None:
                a, w, h = latest
                step = max(1, w // W)
                sub = a[::step, ::step].copy()
                sh, sw = sub.shape[0], sub.shape[1]
                surf = cairo.ImageSurface.create_for_data(memoryview(sub), cairo.FORMAT_RGB24, sw, sh, sw * 4)
                scale = min(W / sw, preview_h / sh)
                cr.save(); cr.translate((W - sw * scale) / 2, 40); cr.scale(scale, scale)
                cr.set_source_surface(surf, 0, 0); cr.paint(); cr.restore()
                # markers and links
                cr.set_line_width(2)
                for t in tracks:
                    col = PALETTE[(max(t["group"], 1) - 1) % len(PALETTE)]
                    x = (W - sw * scale) / 2 + t["cx"] / step * scale; y = 40 + t["cy"] / step * scale
                    r = max(10, t["radius"] / step * scale)
                    cr.set_source_rgb(*col)
                    if t["group"] != t["id"]:
                        for u in tracks:
                            if u["id"] == t["group"]:
                                ux = (W - sw * scale) / 2 + u["cx"] / step * scale; uy = 40 + u["cy"] / step * scale
                                cr.set_dash([6, 4]); cr.move_to(x, y); cr.line_to(ux, uy); cr.stroke(); cr.set_dash([])
                    cr.arc(x, y, r, 0, 6.2832); cr.stroke()
                    label = "#%d%s %s %dp" % (t["group"], "" if t["group"] == t["id"] else "·%d" % t["id"], t["mode"], t["packets"])
                    b = console.board_ids.get(t["group"])
                    if b:
                        label += " " + b
                    cr.set_font_size(12); cr.move_to(x - r, y + r + 14); cr.show_text(label)
            # top bar: filter, clear, stats
            cr.set_source_rgb(0.8, 0.8, 0.8); cr.set_font_size(14)
            cr.move_to(8, 26); cr.show_text("Source: " + ("All" if console.filter == 0 else "#%d %s" % (console.filter, console.board_ids.get(console.filter, ""))))
            cr.set_source_rgb(1.0, 0.45, 0.45); cr.move_to(W - 60, 26); cr.show_text("Clear")
            cr.set_source_rgb(0.6, 0.6, 0.6); cr.set_font_size(11)
            cr.move_to(8, preview_h + 34); cr.show_text("fps %.0f  pkt/s %.0f  packets %d  %s" % (receiver.fps, receiver.pkt_per_s, receiver.total_packets, receiver.source.name))
            # console
            y = preview_h + 56
            cr.set_font_size(13)
            for m in console.visible()[self.scroll:]:
                if y > H - 8:
                    break
                lvl = LEVELS[m["level"]] if m["level"] < len(LEVELS) else "?"
                cr.set_source_rgb(*LEVEL_COLORS.get(lvl, (1, 1, 1)))
                head = "%s [%s]%s" % (time.strftime("%H:%M:%S", time.localtime(m["t"])), lvl,
                                      (" #%d%s" % (m["source"], " " + console.board_ids[m["source"]] if m["source"] in console.board_ids else "")) if m["source"] else "")
                cr.move_to(8, y); cr.show_text(head); y += 15
                cr.set_source_rgb(0.95, 0.95, 0.95); cr.move_to(8, y); cr.show_text(m["text"]); y += 20
            return True

    win = Kiosk()
    win.connect("destroy", Gtk.main_quit)
    receiver.start()
    try:
        Gtk.main()
    finally:
        receiver.stop = True
        console.save()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", help=".rsrec recording instead of the camera")
    ap.add_argument("--device", default="/dev/video0")
    ap.add_argument("--width", type=int, default=1920); ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--exposure", help="v4l2 exposure control value (sensor units, usually lines)")
    ap.add_argument("--gain", help="v4l2 gain control value")
    ap.add_argument("--control", action="append", default=[], help="extra v4l2 control name=value")
    ap.add_argument("--headless", action="store_true"); ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--fast", action="store_true", help="recording: no real-time pacing")
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--history", default=os.path.expanduser("~/.blinko/history.json"))
    a = ap.parse_args()
    console = Console(a.history)
    if a.source:
        src = RecordingSourceLazy(a.source, realtime=not a.fast, loop=not a.headless)
    else:
        controls = {}
        if a.exposure: controls["exposure_auto"] = 1; controls["exposure_absolute"] = a.exposure
        if a.gain: controls["gain"] = a.gain
        for c in a.control:
            k, v = c.split("=", 1); controls[k] = v
        from sources import GstSource
        src = GstSource(a.device, a.width, a.height, a.fps, controls)
    rx = Receiver(src, console)
    if a.headless:
        run_headless(rx, console, a.seconds)
    else:
        run_gtk(rx, console, fullscreen=not a.windowed)


def RecordingSourceLazy(path, realtime, loop):
    from sources import RecordingSource
    return RecordingSource(path, realtime=realtime, loop=loop)


if __name__ == "__main__":
    main()
