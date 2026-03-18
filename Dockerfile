FROM ghcr.io/autowarefoundation/autoware:universe

# Basic tools + Python + VNC stack
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      python3-pip unzip \
      xfce4 xfce4-terminal \
      tigervnc-standalone-server tigervnc-common tigervnc-tools \
      dos2unix supervisor wget curl git sudo dbus-x11 \
      build-essential vim tmux bash-completion tzdata terminator && \
    rm -rf /var/lib/apt/lists/*

# Python deps (gRPC + noVNC websockify + map downloader)
RUN pip3 install --no-cache-dir \
      grpcio grpcio-tools \
      git+https://github.com/novnc/websockify.git@v0.10.0 \
      gdown

# noVNC
RUN git clone https://github.com/AtsushiSaito/noVNC.git -b add_clipboard_support /usr/lib/novnc && \
    ln -s /usr/lib/novnc/vnc.html /usr/lib/novnc/index.html

WORKDIR /app

# gRPC proto + server
COPY planning.proto .
COPY planning_server_node.py .
COPY lanelet_sampling.py .

# Generate gRPC stubs at build time
RUN python3 -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    planning.proto

# Scripts
COPY entrypoint.sh /entrypoint.sh
COPY start_vnc.sh /start_vnc.sh
RUN chmod +x /entrypoint.sh /start_vnc.sh

ENV AUTOWARE_MAP_DIR=/root/autoware_map
# Launch ROS2 planning simulator (default: true). Set to false to run only gRPC (+ optional VNC).
ENV LAUNCH_ROS2=true
# Control RViz and VNC from env (defaults: no RViz, no VNC)
ENV ENABLE_VNC=false
ENV VNC_RESOLUTION=1920x1080

# Only gRPC is exposed by default; VNC ports are opt-in via docker -p
EXPOSE 50051

ENTRYPOINT ["/entrypoint.sh"]
