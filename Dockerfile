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
ENV ENABLE_VNC=false
ENV VNC_RESOLUTION=1920x1080
ENV PATH="${PATH}:/root/.local/bin"
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV CMAKE_PREFIX_PATH="/opt/acados:${CMAKE_PREFIX_PATH}"
ENV ACADOS_SOURCE_DIR=/opt/acados
ENV LD_LIBRARY_PATH="/opt/acados/lib:${LD_LIBRARY_PATH}"

EXPOSE 50051

ENTRYPOINT ["/entrypoint.sh"]
CMD []
