# grpc-autoware-planning-interface

### Build Docker Image
- Install Docker CLI
```bash
docker build -t autoware-planning-grpc .
```


### Running Docker container
Running headless (no display)
```bash
docker run --rm -it --net=host \
  autoware-planning-grpc
```


Running with VNC (can connect to display in http://localhost:6080/)
```bash
docker run --rm -it --net=host \
  -e ENABLE_VNC=true \
  -e VNC_RESOLUTION=1920x1080 \
  -e DISPLAY=:1 \
  autoware-planning-grpc
```
- vnc password = `password`

### Other
- Use your favourite API client (e.g. postman/insomnia/yaak.app) to test that the endpoints work


List of env arguments to use with Docker file:
- `ENABLE_VNC`: Whether to activate VNC for connecting to display, defaults to false.
  - Use alongside `VNC_RESOLUTION=1920x1080`
- `LAUNCH_ROS2`: Whether or not to launch the autoware ros2 simulation on docker launch
Other tips:
- Changing the `Dockerfile`? Ensure you rebuild before running the container
