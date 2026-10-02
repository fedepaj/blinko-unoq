"""Frame sources for the Blinko kiosk: a V4L2 camera through GStreamer (on the UNO Q) or a
.rsrec recording (development on a computer). Both yield (seconds since the first frame, BGRx
bytes, w, h).

The time starts at 0 because the receiver takes it as a C float, which keeps 24 bits: seconds
since the epoch (1.7e9) would move in steps of two minutes and a recording's uptime stamps
(~8e5 s) in steps of 60 ms, while the receiver compares frame times down to a fraction of a chip."""
import os
import subprocess
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
        self.exposure_us = float(self.rec.header.get("exposureUs") or 0)
        self.name = os.path.basename(path)

    def frames(self):
        import numpy as np
        n = len(self.rec)
        if n == 0:
            return
        first_ts = self.rec.frames[0][1]
        # A loop restarts one frame period after the last frame of the previous one, so time keeps
        # increasing: the receiver compares the times of successive frames (track time-outs,
        # stitching across frames) and a step back to 0 would be a frame from the past.
        period = self.rec.duration / (n - 1) if n > 1 else 0.0
        offset, t_start = 0.0, time.monotonic()
        while True:
            for k in range(n):
                ts, _, _, a = self.rec.frame(k)          # (h, w, 4) BGRA
                t = offset + (ts - first_ts)
                if self.realtime:
                    lag = t - (time.monotonic() - t_start)
                    if lag > 0:
                        time.sleep(lag)
                yield t, np.ascontiguousarray(a), self.width, self.height
            if not self.loop:
                return
            offset = t + period


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
            # an argument list, not a shell line: names and values come from the command line.
            # A control that is not applied is reported and the camera still starts: the picture
            # then shows what the exposure is.
            cmd = ["v4l2-ctl", "-d", device] + [x for kv in controls.items() for x in ("-c", "%s=%s" % kv)]
            try:
                r = subprocess.run(cmd, check=False)
                if r.returncode != 0:
                    print("camera controls not applied: `%s` exited with %d" % (" ".join(cmd), r.returncode), file=sys.stderr)
            except OSError as e:
                print("camera controls not applied: v4l2-ctl could not be run (%s)" % e, file=sys.stderr)
        desc = ("v4l2src device=%s ! video/x-raw,width=%d,height=%d,framerate=%d/1 ! videoconvert ! "
                "video/x-raw,format=BGRx ! appsink name=sink emit-signals=false max-buffers=2 drop=true sync=false"
                % (device, width, height, fps))
        self.pipe = Gst.parse_launch(desc)
        self.sink = self.pipe.get_by_name("sink")
        self.bus = self.pipe.get_bus()
        if self.pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("camera %s: the pipeline did not start: %s" % (device, self._failure() or desc))

    def _failure(self):
        """Why the pipeline stopped (its error message, or "end of stream"); None while it runs."""
        Gst = self.Gst
        msg = self.bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if msg is None:
            return None
        if msg.type == Gst.MessageType.EOS:
            return "end of stream"
        err, debug = msg.parse_error()
        return "%s (%s)" % (err.message, debug) if debug else err.message

    def frames(self):
        import numpy as np
        Gst = self.Gst
        t0 = use_pts = None
        while True:
            # A pipeline that fails (camera unplugged, format refused) says so on its bus and then
            # delivers nothing: without this check the loop would wait for a frame for ever.
            why = self._failure()
            if why:
                raise RuntimeError("camera %s: %s" % (self.name, why))
            sample = self.sink.emit("try-pull-sample", Gst.SECOND)
            if sample is None:
                continue
            buf = sample.get_buffer()
            caps = sample.get_caps().get_structure(0)
            w, h = caps.get_value("width"), caps.get_value("height")
            # The buffer's timestamp is when the frame was captured; the time it is pulled here
            # also carries the conversion and the queueing. It is used when the driver stamps its
            # buffers (decided on the first frame), the monotonic clock otherwise.
            if use_pts is None:
                use_pts = buf.pts != Gst.CLOCK_TIME_NONE
            if use_pts and buf.pts == Gst.CLOCK_TIME_NONE:
                continue
            t = buf.pts / Gst.SECOND if use_pts else time.monotonic()
            if t0 is None:
                t0 = t
            ok, info = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue
            try:
                a = np.frombuffer(info.data, dtype=np.uint8, count=w * h * 4).reshape(h, w, 4).copy()
            finally:
                buf.unmap(info)
            yield t - t0, a, w, h

    def stop(self):
        self.pipe.set_state(self.Gst.State.NULL)
