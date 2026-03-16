# grpc-autoware-planning-interface
- Install Docker CLI
```bash
docker build -t autoware-planning-grpc .
```

- Use your favourite API client (e.g. postman/insomnia/yaak.app) to test that the endpoints work

Running headless (no display)
```bash
docker run --rm -it --net=host \
  autoware-planning-grpc
```

Running with VNC (can connect to display in http://localhost:6080/)
```bash
docker run --rm -it --net=host \
  -e ENABLE_VNC=true \
  -e AUTOWARE_RVIZ=true \
  -e VNC_RESOLUTION=1920x1080 \
  -e DISPLAY=:1 \
  autoware-planning-grpc
```
- vnc password = `password`
