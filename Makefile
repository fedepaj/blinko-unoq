PY ?= python3
.PHONY: headless replay deps
headless:        # a recording through the receiver, messages on stdout: make headless REC=path.rsrec
	$(PY) blinko_kiosk.py --source $(REC) --headless --fast
deps:            # on the UNO Q
	sudo apt-get install -y python3-gi gir1.2-gtk-3.0 python3-gi-cairo gstreamer1.0-plugins-base gstreamer1.0-plugins-good python3-numpy gcc v4l-utils
