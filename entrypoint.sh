#!/usr/bin/env bash
set -e

MAP_DIR="${AUTOWARE_MAP_DIR:-$HOME/autoware_map}"
MAP_ZIP="${MAP_DIR}/sample-map-planning.zip"

# One-time map download (dev convenience)
if [ ! -d "$MAP_DIR/sample-map-planning" ]; then
  mkdir -p "$MAP_DIR"
  gdown -O "$MAP_ZIP" 'https://docs.google.com/uc?export=download&id=1499_nsbUbIeturZaDj7jhUownh5fvXHd'
  unzip -d "$MAP_DIR" "$MAP_ZIP"
fi

# Optional VNC / noVNC desktop
if [ "$ENABLE_VNC" = "true" ]; then
  # Ensure everything (including RViz) uses the VNC X server
  export DISPLAY=${DISPLAY:-:1}
  /start_vnc.sh &
fi

# Source Autoware
source /opt/autoware/setup.bash

# Decide whether to launch RViz (AUTOWARE_RVIZ overrides, defaults to ENABLE_VNC)
RVIZ_ENABLE="${AUTOWARE_RVIZ:-$ENABLE_VNC}"

# Start planning simulator
ros2 launch autoware_launch planning_simulator.launch.xml \
  map_path:=$MAP_DIR/sample-map-planning \
  vehicle_model:=sample_vehicle \
  sensor_model:=sample_sensor_kit \
  rviz:=$RVIZ_ENABLE &
PLANNING_PID=$!

# Start gRPC ROS 2 node
python3 /app/example_server_node.py &
GRPC_PID=$!

wait -n "$PLANNING_PID" "$GRPC_PID"
exit $?
