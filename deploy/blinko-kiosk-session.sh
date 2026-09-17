#!/bin/sh
# X session for the Blinko kiosk on the UNO Q + GigaDisplay (portrait, no blanking).
xset s off; xset -dpms; xset s noblank
xrandr --output DSI-1 --rotate normal 2>/dev/null || true
(
  for _ in $(seq 1 30); do
    if xinput list --name-only 2>/dev/null | grep -qi goodix; then
      xinput set-prop "pointer:Goodix Capacitive TouchScreen" "Coordinate Transformation Matrix" 1 0 0 0 1 0 0 0 1
      break
    fi
    sleep 1
  done
) &
exec /opt/blinko/blinko_kiosk.py --device "${BLINKO_VIDEO:-/dev/video0}" ${BLINKO_ARGS}
