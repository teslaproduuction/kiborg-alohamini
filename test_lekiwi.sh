#!/bin/bash
pkill -f lekiwi_host 2>/dev/null; pkill -f ffmpeg 2>/dev/null; sleep 1
cd /home/pi/lerobot_alohamini
echo "" | /home/pi/miniforge3/envs/lerobot/bin/python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini1 > /tmp/lekiwi_direct.log 2>&1 &
PID=$!
echo "PID: $PID"
sleep 15
echo "=== LOG ==="
cat /tmp/lekiwi_direct.log
echo "=== PROC ==="
ps aux | grep lekiwi | grep -v grep
