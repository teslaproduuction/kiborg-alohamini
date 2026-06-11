#!/bin/bash
pkill -f lekiwi_host 2>/dev/null
sleep 1
cd /home/pi/lerobot_alohamini
nohup bash -c 'echo "" | /home/pi/miniforge3/envs/lerobot/bin/python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini1' > /tmp/lekiwi.log 2>&1 &
echo "lekiwi_host PID: $!"
