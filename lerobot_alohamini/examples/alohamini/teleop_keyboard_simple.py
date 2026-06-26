"""Minimal keyboard teleop client for AlohaMini — no full lerobot import needed."""

import json
import time
import threading
import zmq
from pynput import keyboard as kb

REMOTE_IP = "172.24.93.157"
CMD_PORT = 5555
OBS_PORT = 5556
FPS = 30

# Speed settings
BASE_SPEED = 0.3    # m/s
ROTATE_SPEED = 60.0  # deg/s
LIFT_STEP = 2.0      # mm per frame

pressed = set()
lock = threading.Lock()

def on_press(key):
    try:
        with lock:
            pressed.add(key.char.lower() if hasattr(key, 'char') and key.char else key)
    except Exception:
        pass

def on_release(key):
    try:
        with lock:
            k = key.char.lower() if hasattr(key, 'char') and key.char else key
            pressed.discard(k)
        if key == kb.Key.esc or (hasattr(key, 'char') and key.char == 'q'):
            return False
    except Exception:
        pass

def get_action(lift_height):
    global BASE_SPEED, ROTATE_SPEED
    with lock:
        keys = set(pressed)

    x = y = theta = 0.0
    lift_vel = 0

    if 'w' in keys: x = BASE_SPEED
    if 's' in keys: x = -BASE_SPEED
    if 'z' in keys: y = BASE_SPEED
    if 'x' in keys: y = -BASE_SPEED
    if 'a' in keys: theta = ROTATE_SPEED
    if 'd' in keys: theta = -ROTATE_SPEED
    if 'u' in keys: lift_vel = 1
    if 'j' in keys: lift_vel = -1
    if 'r' in keys:
        BASE_SPEED = min(BASE_SPEED + 0.05, 1.0)
        ROTATE_SPEED = min(ROTATE_SPEED + 10, 180)
    if 'f' in keys:
        BASE_SPEED = max(BASE_SPEED - 0.05, 0.05)
        ROTATE_SPEED = max(ROTATE_SPEED - 10, 10)

    new_height = lift_height + lift_vel * LIFT_STEP

    return {
        "x.vel": x,
        "y.vel": y,
        "theta.vel": theta,
        "lift_axis.height_mm": new_height,
        "lift_axis.vel": lift_vel,
    }, new_height

def main():
    ctx = zmq.Context()
    cmd_sock = ctx.socket(zmq.PUSH)
    cmd_sock.connect(f"tcp://{REMOTE_IP}:{CMD_PORT}")
    obs_sock = ctx.socket(zmq.PULL)
    obs_sock.connect(f"tcp://{REMOTE_IP}:{OBS_PORT}")
    obs_sock.setsockopt(zmq.RCVTIMEO, 100)

    print(f"Connected to {REMOTE_IP}")
    print("Controls: W/S=fwd/back  A/D=rotate  Z/X=strafe  U/J=lift  R/F=speed  Q/ESC=quit")

    listener = kb.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    lift_height = 0.0
    dt = 1.0 / FPS

    try:
        while listener.is_alive():
            t0 = time.perf_counter()

            # Get latest observation (non-blocking)
            try:
                raw = obs_sock.recv()
                obs = json.loads(raw.decode())
                lift_height = obs.get("lift_axis.height_mm", lift_height)
            except zmq.Again:
                pass

            action, lift_height = get_action(lift_height)
            cmd_sock.send_string(json.dumps(action))

            with lock:
                keys = set(pressed)
            moving = any(k in keys for k in ['w','s','a','d','z','x','u','j'])
            if moving:
                print(f"[spd={BASE_SPEED:.2f}] x={action['x.vel']:.2f} y={action['y.vel']:.2f} "
                      f"θ={action['theta.vel']:.0f} lift={lift_height:.1f}mm")

            elapsed = time.perf_counter() - t0
            time.sleep(max(0, dt - elapsed))

    except KeyboardInterrupt:
        pass
    finally:
        cmd_sock.send_string(json.dumps({"x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0,
                                          "lift_axis.height_mm": lift_height, "lift_axis.vel": 0}))
        listener.stop()
        ctx.destroy()
        print("Disconnected.")

if __name__ == "__main__":
    main()
