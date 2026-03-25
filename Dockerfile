FROM ghcr.io/autowarefoundation/autoware:universe

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      python3-pip unzip \
      xfce4 xfce4-terminal \
      tigervnc-standalone-server tigervnc-common tigervnc-tools \
      dos2unix supervisor wget curl git sudo dbus-x11 \
      build-essential vim tmux bash-completion tzdata terminator && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
      grpcio grpcio-tools grpcio-reflection \
      git+https://github.com/novnc/websockify.git@v0.10.0 \
      gdown

RUN git clone https://github.com/AtsushiSaito/noVNC.git -b add_clipboard_support /usr/lib/novnc && \
    ln -s /usr/lib/novnc/vnc.html /usr/lib/novnc/index.html

WORKDIR /app

COPY planning.proto .
COPY lanelet_sampling.py .
COPY planning_server_node.py .
COPY server_node.py .

RUN python3 -m grpc_tools.protoc \
    -I. \
    --python_out=. \
    --grpc_python_out=. \
    planning.proto

COPY entrypoint.sh /entrypoint.sh
COPY start_vnc.sh /start_vnc.sh
RUN chmod +x /entrypoint.sh /start_vnc.sh

ENV AUTOWARE_MAP_DIR=/root/autoware_map
ENV LAUNCH_ROS2=true
ENV ENABLE_VNC=false
ENV VNC_RESOLUTION=1920x1080

EXPOSE 50051 50052

ENTRYPOINT ["/entrypoint.sh"]
