#!/usr/bin/env bash
set -e

mkdir -p /root/.vnc
if [ ! -f /root/.vnc/passwd ]; then
  echo "password" | vncpasswd -f > /root/.vnc/passwd
  chmod 600 /root/.vnc/passwd
fi

export DISPLAY=:1.0
vncserver :1 -geometry "${VNC_RESOLUTION}" -depth 24

# noVNC proxy (web UI on 6080 by default)
/usr/lib/novnc/utils/novnc_proxy --vnc localhost:5901 --listen 6080
