"""Frame sources for the Blinko kiosk: a V4L2 camera through GStreamer (on the UNO Q) or a
.rsrec recording (development on a computer). Both yield (timestamp, BGRx bytes, w, h)."""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


class RecordingSource:
    """Frames of a .rsrec (Recorder.swift format) at the recorded pace or as fast as possible."""

    def __init__(self, path, realtime=True, loop=False):
        sys.path.insert(0, os.path.join(HERE, "core", "tools"))
        from rsrec import Recording
        self.rec = Recording(path)
        self.realtime, self.loop = realtime, loop
        self.width, self.height = self.rec.header["width"], self.rec.header["height"]
        self.name = os.path.basename(path)

    def frames(self):
        import numpy as np
        while True:
            t_start, first_ts = time.time(), None
            for k in range(len(self.rec)):
                ts, _, _, a = self.rec.frame(k)          # (h, w, 4) BGRA
                if first_ts is None:
                    first_ts = ts
                if self.realtime:
                    lag = (ts - first_ts) - (time.time() - t_start)
                    if lag > 0:
                        time.sleep(lag)
                yield ts, np.ascontiguousarray(a), self.width, self.height
            if not self.loop:
                return


class GstSource:
    """v4l2src -> BGRx appsink. Exposure is set through v4l2-ctl before the pipeline starts
    (the controls differ per sensor: `v4l2-ctl -d DEV --list-ctrls`)."""

    def __init__(self, device="/dev/video0", width=1920, height=1080, fps=30, controls=None):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        self.Gst = Gst
        Gst.init(None)
        self.width, self.height, self.name = width, height, device
        if controls:
            os.system("v4l2-ctl -d %s %s" % (device, " ".join("-c %s=%s" % kv for kv in controls.items())))
        desc = ("v4l2src device=%s ! video/x-raw,width=%d,height=%d,framerate=%d/1 ! videoconvert ! "
                "video/x-raw,format=BGRx ! appsink name=sink emit-signals=false max-buffers=2 drop=true sync=false"
                % (device, width, height, fps))
        self.pipe = Gst.parse_launch(desc)
        self.sink = self.pipe.get_by_name("sink")
        self.pipe.set_state(Gst.State.PLAYING)

    def frames(self):
        import numpy as np
        Gst = self.Gst
        while True:
            sample = self.sink.emit("try-pull-sample", Gst.SECOND)
            if sample is None:
                continue
            buf = sample.get_buffer()
            caps = sample.get_caps().get_structure(0)
            w, h = caps.get_value("width"), caps.get_value("height")
            ok, info = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue
            try:
                a = np.frombuffer(info.data, dtype=np.uint8, count=w * h * 4).reshape(h, w, 4).copy()
            finally:
                buf.unmap(info)
            yield time.time(), a, w, h

    def stop(self):
        self.pipe.set_state(self.Gst.State.NULL)
