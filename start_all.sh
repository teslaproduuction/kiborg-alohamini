#!/bin/bash
# Start AlohaMini robot services
pkill -f lekiwi_host 2>/dev/null
pkill -f robot_cam_server 2>/dev/null
pkill -f ffmpeg 2>/dev/null
sleep 2

cd /home/pi/lerobot_alohamini

# Robot host — video0 camera via OpenCV (direct USB 2.0 480M port)
nohup bash -c 'echo "" | /home/pi/miniforge3/envs/lerobot/bin/python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini1' > /tmp/lekiwi.log 2>&1 &
echo "lekiwi_host PID: $!"

# Camera server — remaining cameras on hub (video2,4,6,8) via ffmpeg
# video0 is handled by lekiwi_host above
sleep 3
CAMS=2,4,6,8 nohup /home/pi/miniforge3/envs/lerobot/bin/python examples/alohamini/robot_cam_server.py > /tmp/camserver.log 2>&1 &
echo "cam_server PID: $!"
