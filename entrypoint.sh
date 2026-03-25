#!/usr/bin/env bash
set -e

MAP_DIR="${AUTOWARE_MAP_DIR:-$HOME/autoware_map}"
MAP_ZIP="${MAP_DIR}/sample-map-planning.zip"

LAUNCH_ROS2="${LAUNCH_ROS2:-true}"

if [ ! -d "$MAP_DIR/sample-map-planning" ]; then
  mkdir -p "$MAP_DIR"
  gdown -O "$MAP_ZIP" 'https://docs.google.com/uc?export=download&id=1499_nsbUbIeturZaDj7jhUownh5fvXHd'
  unzip -d "$MAP_DIR" "$MAP_ZIP"
fi

if [ "$ENABLE_VNC" = "true" ]; then
  export DISPLAY=${DISPLAY:-:1}
  /start_vnc.sh &
fi

source /opt/autoware/setup.bash

python3 /app/planning_server_node.py &
python3 /app/server_node.py &
GRPC_PID=$!

if [ "$LAUNCH_ROS2" = "true" ]; then
  ros2 launch autoware_launch planning_simulator.launch.xml \
    map_path:=$MAP_DIR/sample-map-planning \
    vehicle_model:=sample_vehicle \
    sensor_model:=sample_sensor_kit \
    rviz:=$ENABLE_VNC &
  PLANNING_PID=$!
  wait -n "$PLANNING_PID" "$GRPC_PID"
else
  wait "$GRPC_PID"
fi
exit $?
