"""
AlohaMini Controller v3
- Camera feeds (MJPEG streaming from Pi ZMQ observations)
- Neural network inference control (ACT/Diffusion policy evaluation)
- Waypoint route planner with 2D map
- RadioMaster Pocket / gamepad support
- Full web UI
"""

import json, threading, time, math, os, base64, subprocess, sys
from pathlib import Path
import zmq
import pygame
from flask import Flask, request, jsonify, Response, send_from_directory

# ── Config (env-overridable for Docker) ──────────────────────────────────────
REMOTE_IP  = os.environ.get("ROBOT_IP", "192.168.31.170")
CMD_PORT   = int(os.environ.get("CMD_PORT", 5555))
OBS_PORT   = int(os.environ.get("OBS_PORT", 5556))
WEB_PORT   = int(os.environ.get("WEB_PORT", 8080))
# Extra camera server running on Pi (robot_cam_server.py) for cameras not in lekiwi_host
CAM_SERVER_PORT = int(os.environ.get("CAM_SERVER_PORT", 8091))
# /dev/videoN indices served by cam server (not via ZMQ obs)
CAM_SERVER_DEVS = [int(x) for x in os.environ.get("CAM_SERVER_DEVS", "2,4,6,8").split(",")]
BINDINGS_FILE      = Path(__file__).parent / "gamepad_bindings.json"
ARM_BINDINGS_FILE  = Path(__file__).parent / "arm_bindings.json"
CAM_LABELS_FILE    = Path(__file__).parent / "camera_labels.json"
MESH_DIR   = Path(r"D:\Проекты\Kiborg\AlohaMini\simulation\src\Aloha\meshes")

# ── ZMQ ───────────────────────────────────────────────────────────────────────
ctx = zmq.Context()
cmd_sock = ctx.socket(zmq.PUSH)
cmd_sock.connect(f"tcp://{REMOTE_IP}:{CMD_PORT}")
obs_sock = ctx.socket(zmq.PULL)
obs_sock.connect(f"tcp://{REMOTE_IP}:{OBS_PORT}")
obs_sock.setsockopt(zmq.RCVTIMEO, 80)

ARM_JOINTS = ["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"]
REC_DIR = Path(__file__).parent / "recordings"

# ── State ─────────────────────────────────────────────────────────────────────
state = {
    "lift_height":    10.0,
    "base_speed":     0.30,
    "rot_speed":      60.0,
    "base_cmd":       {"x":0.0,"y":0.0,"theta":0.0},
    "arm_left":       {j:0.0 for j in ARM_JOINTS},
    "arm_right":      {j:0.0 for j in ARM_JOINTS},
    "selected_joint": 0,
    "gamepad_name":     "none",
    "gamepad_axes":     {},
    "gamepad_buttons":  {},
    # Arm gamepad (PS4, second device)
    "arm_gamepad_name": "none",
    "arm_gamepad_axes": {},
    "arm_gamepad_buttons": {},
    "arm_control_side": "left",   # "left" | "right" | "both"
    "arms_disarmed":    False,
    "connected":        False,
    # Cameras: name → base64 jpeg
    "cameras":        {},
    "camera_names":   [],
    # Odometry (dead reckoning)
    "odom":           {"x":0.0,"y":0.0,"theta":0.0},
    # Inference
    "inference_mode": False,
    "inference_model": "",
    "inference_status":"idle",
    # Recording
    "recording":      False,
    "rec_dataset":    "",
    "rec_episode":    0,
    "rec_frames":     0,
    # Waypoints
    "waypoints":      [],
    "waypoint_active": False,
    "waypoint_idx":    0,
}
lock = threading.Lock()
initialized = threading.Event()

# ── Bindings ──────────────────────────────────────────────────────────────────
DEFAULT_BINDINGS = {
    "axes": {
        "0": {"action":"y_vel",    "scale":1.0,"deadzone":0.10,"invert":False,"label":"Left Gimbal X"},
        "1": {"action":"x_vel",    "scale":1.0,"deadzone":0.10,"invert":True, "label":"Left Gimbal Y"},
        "2": {"action":"theta_vel","scale":1.0,"deadzone":0.10,"invert":False,"label":"Right Gimbal X"},
        "3": {"action":"lift",     "scale":1.0,"deadzone":0.10,"invert":False,"label":"Right Gimbal Y"},
        "4": {"action":"arm_left", "scale":1.0,"deadzone":0.05,"invert":False,"label":"Left Wheel"},
        "5": {"action":"arm_right","scale":1.0,"deadzone":0.05,"invert":False,"label":"Right Wheel"},
    },
    "buttons": {
        "0": {"action":"none",       "label":"SYS"},
        "1": {"action":"none",       "label":"TELE"},
        "2": {"action":"none",       "label":"MDL"},
        "3": {"action":"stop_base",  "label":"RTN"},
        "4": {"action":"speed_down", "label":"PAGE"},
        "5": {"action":"speed_up",   "label":"PWR"},
        "6": {"action":"joint_prev", "label":"SA"},
        "7": {"action":"joint_next", "label":"SB"},
    },
}

# ── PS4 arm bindings defaults ─────────────────────────────────────────────────
# PS4 axes (pygame): 0=LX 1=LY 2=RX 3=RY 4=L2(-1..+1) 5=R2(-1..+1)
# PS4 buttons: 0=Cross 1=Circle 2=Square 3=Triangle 4=L1 5=R1 9=Options
DEFAULT_ARM_BINDINGS = {
    "device_index": 1,          # second connected gamepad (auto-detected by name if possible)
    "arm_speed":    0.6,        # deg/frame — lower = smoother, raise in /arm_settings
    "axes": {
        "0": {"joint":"shoulder_pan",  "invert":False,"deadzone":0.18,"scale":1.0},
        "1": {"joint":"shoulder_lift", "invert":True, "deadzone":0.18,"scale":1.0},
        "2": {"joint":"elbow_flex",    "invert":False,"deadzone":0.18,"scale":1.0},
        "3": {"joint":"wrist_flex",    "invert":True, "deadzone":0.18,"scale":1.0},
    },
    "trigger_l2": 4,    # L2 → wrist_roll negative
    "trigger_r2": 5,    # R2 → wrist_roll positive
    "buttons": {
        "4": {"action":"gripper_close"},   # L1 held
        "5": {"action":"gripper_open"},    # R1 held
        "2": {"action":"switch_left"},     # Square
        "3": {"action":"switch_right"},    # Triangle
        "0": {"action":"switch_cycle"},    # Cross → cycles left/right/both
        "1": {"action":"speed_up"},        # Circle
        "9": {"action":"home_arms"},       # Options
    },
}

bindings = {}
def load_bindings():
    global bindings
    if BINDINGS_FILE.exists():
        try: bindings = json.loads(BINDINGS_FILE.read_text()); return
        except: pass
    bindings = json.loads(json.dumps(DEFAULT_BINDINGS))
def save_bindings():
    BINDINGS_FILE.write_text(json.dumps(bindings, indent=2))
load_bindings()

# ── Camera labels ─────────────────────────────────────────────────────────────
# Maps camera key (from ZMQ obs) → robot part label + display metadata
ROBOT_PARTS = ["front","rear","top","wrist_left","wrist_right","custom"]

cam_labels = {}
def load_cam_labels():
    global cam_labels
    if CAM_LABELS_FILE.exists():
        try: cam_labels = json.loads(CAM_LABELS_FILE.read_text()); return
        except: pass
    cam_labels = {}
def save_cam_labels():
    CAM_LABELS_FILE.write_text(json.dumps(cam_labels, indent=2))
load_cam_labels()

arm_bindings = {}
def load_arm_bindings():
    global arm_bindings
    if ARM_BINDINGS_FILE.exists():
        try: arm_bindings = json.loads(ARM_BINDINGS_FILE.read_text()); return
        except: pass
    arm_bindings = json.loads(json.dumps(DEFAULT_ARM_BINDINGS))
def save_arm_bindings():
    ARM_BINDINGS_FILE.write_text(json.dumps(arm_bindings, indent=2))
load_arm_bindings()

# ── Arm presets (safe positions, units = calibrated -100..100) ───────────────
# All values in middle of calibration range; tested not to cause self-collision.
ARM_PRESETS = {
    # flat rest: everything at neutral
    "home": {"shoulder_pan":0, "shoulder_lift":0, "elbow_flex":0, "wrist_flex":0, "wrist_roll":0, "gripper":0},
    # ready/observation: arms slightly raised and bent forward
    "ready": {"shoulder_pan":0, "shoulder_lift":25, "elbow_flex":-45, "wrist_flex":20, "wrist_roll":0, "gripper":20},
    # gripper actions only
    "gripper_open":  {"gripper": 80},
    "gripper_close": {"gripper":-60},
}

_move_thread = None

def smooth_move(sides, target: dict, steps=40, duration=1.5):
    """Interpolate arm joints to target over duration seconds."""
    global _move_thread
    def _run():
        dt = duration / steps
        with lock:
            starts = {s: dict(state[f"arm_{s}"]) for s in sides}
        for i in range(1, steps+1):
            t = i / steps
            with lock:
                if state["arms_disarmed"]: break
                for s in sides:
                    for j, tgt in target.items():
                        cur = starts[s][j]
                        state[f"arm_{s}"][j] = cur + (tgt - cur) * t
            time.sleep(dt)
    _move_thread = threading.Thread(target=_run, daemon=True)
    _move_thread.start()

# ── Action builder ────────────────────────────────────────────────────────────
def build_action():
    with lock:
        lh   = state["lift_height"]
        bc   = state["base_cmd"]
        left = dict(state["arm_left"])
        right= dict(state["arm_right"])
    action = {
        "x.vel": bc["x"], "y.vel": bc["y"], "theta.vel": bc["theta"],
        "lift_axis.height_mm": lh,
    }
    for j in ARM_JOINTS:
        action[f"arm_left_{j}.pos"]  = left[j]
        action[f"arm_right_{j}.pos"] = right[j]
    return action

# ── Odometry update ───────────────────────────────────────────────────────────
_last_odom_t = time.time()
def update_odom(x_vel, y_vel, theta_vel):
    global _last_odom_t
    now = time.time(); dt = min(now - _last_odom_t, 0.1); _last_odom_t = now
    with lock:
        th = state["odom"]["theta"] * math.pi / 180
        state["odom"]["x"]     += (x_vel * math.cos(th) - y_vel * math.sin(th)) * dt
        state["odom"]["y"]     += (x_vel * math.sin(th) + y_vel * math.cos(th)) * dt
        state["odom"]["theta"] += theta_vel * dt

# ── Observation thread ────────────────────────────────────────────────────────
def obs_loop():
    while True:
        try:
            obs = json.loads(obs_sock.recv().decode())
            with lock:
                state["lift_height"] = obs.get("lift_axis.height_mm", state["lift_height"])
                for j in ARM_JOINTS:
                    v = obs.get(f"arm_left_{j}.pos");
                    if v is not None: state["arm_left"][j] = v
                    v = obs.get(f"arm_right_{j}.pos")
                    if v is not None: state["arm_right"][j] = v
                # Cameras
                cam_names = []
                for k, v in obs.items():
                    if isinstance(v, str) and len(v) > 100 and k not in ("lift_axis.height_mm",):
                        # likely base64 image
                        state["cameras"][k] = v
                        cam_names.append(k)
                if cam_names: state["camera_names"] = cam_names
                state["connected"] = True
            initialized.set()
        except zmq.Again:
            with lock: state["connected"] = False
        except Exception:
            time.sleep(0.05)

threading.Thread(target=obs_loop, daemon=True).start()

# ── Demo cameras (synthetic video for testing without a robot) ────────────────
# Enable with env DEMO_CAMERAS=1 — generates moving test patterns so the
# Cameras tab shows live video even when the Pi is offline.
def demo_camera_loop():
    import io
    from PIL import Image, ImageDraw
    cams = ["front", "wrist_left", "wrist_right"]
    w, h = 640, 480
    frame = 0
    while True:
        t = time.time()
        for ci, cam in enumerate(cams):
            img = Image.new("RGB", (w, h), (12, 16, 26))
            d = ImageDraw.Draw(img)
            # grid
            for x in range(0, w, 40): d.line([(x,0),(x,h)], fill=(26,32,48))
            for y in range(0, h, 40): d.line([(0,y),(w,y)], fill=(26,32,48))
            # moving box (different phase per cam)
            import math as _m
            bx = int(w/2 + _m.sin(t*1.5 + ci*2) * (w/3))
            by = int(h/2 + _m.cos(t*1.2 + ci*2) * (h/3))
            col = [(74,158,255),(80,255,120),(255,170,80)][ci % 3]
            d.ellipse([bx-30,by-30,bx+30,by+30], fill=col)
            # labels
            d.rectangle([0,0,w,30], fill=(0,0,0))
            d.text((8,8), f"DEMO · {cam} · frame {frame} · {time.strftime('%H:%M:%S')}", fill=col)
            d.text((8,h-22), "synthetic feed (no robot) — set DEMO_CAMERAS=0 for real", fill=(90,110,140))
            buf = io.BytesIO(); img.save(buf, format="JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode()
            with lock:
                state["cameras"][cam] = b64
                if cam not in state["camera_names"]:
                    state["camera_names"] = cams
        frame += 1
        time.sleep(1/15)

if os.environ.get("DEMO_CAMERAS") == "1":
    threading.Thread(target=demo_camera_loop, daemon=True).start()
    print("[Demo] synthetic camera feeds ON (DEMO_CAMERAS=1)")

# ── Recording ─────────────────────────────────────────────────────────────────
_rec_fh = None      # open jsonl file handle
_rec_path = None    # current episode dir
_rec_t0 = 0.0

def rec_start(dataset):
    global _rec_fh, _rec_path, _rec_t0
    rec_stop()
    ds_dir = REC_DIR / dataset
    ds_dir.mkdir(parents=True, exist_ok=True)
    # next episode index
    existing = sorted(ds_dir.glob("episode_*"))
    ep = len(existing)
    _rec_path = ds_dir / f"episode_{ep:03d}"
    _rec_path.mkdir(parents=True, exist_ok=True)
    (_rec_path / "frames").mkdir(exist_ok=True)
    _rec_fh = open(_rec_path / "data.jsonl", "w", encoding="utf-8")
    _rec_t0 = time.time()
    with lock:
        state["recording"]=True; state["rec_dataset"]=dataset
        state["rec_episode"]=ep; state["rec_frames"]=0

def rec_stop():
    global _rec_fh, _rec_path
    if _rec_fh:
        _rec_fh.close(); _rec_fh=None
        # write meta
        try:
            with lock: nframes=state["rec_frames"]
            (_rec_path / "meta.json").write_text(json.dumps({
                "frames": nframes, "fps": 30, "joints": ARM_JOINTS,
                "duration_s": time.time()-_rec_t0,
            }, indent=2))
        except Exception: pass
    _rec_path=None
    with lock: state["recording"]=False

def rec_frame(action):
    """Append one (observation, action) frame; save camera jpegs."""
    global _rec_fh
    if not _rec_fh: return
    with lock:
        fi = state["rec_frames"]
        obs_joints = {f"left_{j}": state["arm_left"][j] for j in ARM_JOINTS}
        obs_joints.update({f"right_{j}": state["arm_right"][j] for j in ARM_JOINTS})
        obs_joints["lift_mm"] = state["lift_height"]
        odom = dict(state["odom"])
        cams = list(state["camera_names"])
        cam_data = {c: state["cameras"].get(c,"") for c in cams}
    # save camera frames as jpg
    cam_files = {}
    for c, b64 in cam_data.items():
        if b64:
            try:
                fn = f"frames/{c}_{fi:05d}.jpg"
                (_rec_path / fn).write_bytes(base64.b64decode(b64))
                cam_files[c] = fn
            except Exception: pass
    rec = {
        "t": round(time.time()-_rec_t0, 3),
        "observation": {"joints": obs_joints, "odom": odom, "cameras": cam_files},
        "action": action,
    }
    _rec_fh.write(json.dumps(rec) + "\n")
    with lock: state["rec_frames"] = fi + 1

# ── Send / waypoint loop ──────────────────────────────────────────────────────
def send_loop():
    initialized.wait(timeout=5.0)
    while True:
        # Pause our command stream while AI inference drives the robot
        with lock: infer = state["inference_mode"]
        if infer:
            time.sleep(0.1)
            continue
        # Waypoint navigation
        with lock:
            wp_active = state["waypoint_active"]
            wps = state["waypoints"]
            idx = state["waypoint_idx"]
            odom = dict(state["odom"])
            sp = state["base_speed"]

        if wp_active and idx < len(wps):
            tx, ty = wps[idx]["x"], wps[idx]["y"]
            dx = tx - odom["x"]; dy = ty - odom["y"]
            dist = math.sqrt(dx*dx + dy*dy)
            if dist < 0.15:  # reached waypoint
                with lock:
                    state["waypoint_idx"] = idx + 1
                    if state["waypoint_idx"] >= len(wps):
                        state["waypoint_active"] = False
            else:
                # Steer toward waypoint
                target_angle = math.atan2(dy, dx) * 180 / math.pi
                heading_err  = target_angle - odom["theta"]
                while heading_err > 180:  heading_err -= 360
                while heading_err < -180: heading_err += 360
                x_vel  = min(sp, dist * 0.5) * math.cos(heading_err * math.pi / 180)
                y_vel  = min(sp, dist * 0.5) * math.sin(heading_err * math.pi / 180)
                theta_vel = max(-60, min(60, heading_err * 1.5))
                with lock: state["base_cmd"] = {"x": x_vel, "y": y_vel, "theta": theta_vel}
                update_odom(x_vel, y_vel, theta_vel)
        else:
            with lock: bc = state["base_cmd"]
            update_odom(bc["x"], bc["y"], bc["theta"])

        act = build_action()
        cmd_sock.send_string(json.dumps(act))
        with lock: rec = state["recording"]
        if rec:
            try: rec_frame(act)
            except Exception as e: print(f"[rec] {e}")
        time.sleep(1/30)

threading.Thread(target=send_loop, daemon=True).start()

# ── Gamepad thread (base RadioMaster + PS4 arms, merged) ─────────────────────
def apply_dz(v, dz):
    if abs(v) < dz: return 0.0
    return (v - math.copysign(dz, v)) / (1.0 - dz)

_SIDE_CYCLE = ["left", "right", "both"]

def gamepad_loop():
    pygame.init(); pygame.joystick.init()
    last_btns = {}; arm_last_btns = {}; last_count = -1
    while True:
        pygame.joystick.quit(); pygame.joystick.init()
        count = pygame.joystick.get_count()
        arm_idx = arm_bindings.get("device_index", 1)
        if count != last_count:
            print(f"[Gamepad] {count} device(s) detected")
        last_count = count

        # Detect gamepads by name — RadioMaster=base, Sony/DualShock=arms
        # Falls back to index if names don't match
        _BASE_KEYWORDS = ("radiomaster","opentx","frsky","tx16","tx12","boxer","pocket")
        _ARM_KEYWORDS  = ("sony","dualshock","dualsense","playstation","wireless controller","ps4","ps5")
        all_names = [pygame.joystick.Joystick(i).get_name().lower() for i in range(count)]
        print(f"[Gamepad] devices: {all_names}")

        base_idx, arm_idx_auto = 0, arm_bindings.get("device_index", 1)
        if count >= 2:
            for i, n in enumerate(all_names):
                if any(k in n for k in _BASE_KEYWORDS): base_idx = i
                if any(k in n for k in _ARM_KEYWORDS):  arm_idx_auto = i

        joy_base = None
        if count > base_idx:
            joy_base = pygame.joystick.Joystick(base_idx); joy_base.init()
            with lock: state["gamepad_name"] = joy_base.get_name()
            print(f"[BaseGamepad] idx={base_idx}: {joy_base.get_name()}")
        else:
            with lock: state["gamepad_name"]="none"; state["gamepad_axes"]={}; state["gamepad_buttons"]={}

        joy_arm = None
        if count > arm_idx_auto and arm_idx_auto != base_idx:
            joy_arm = pygame.joystick.Joystick(arm_idx_auto); joy_arm.init()
            with lock: state["arm_gamepad_name"] = joy_arm.get_name()
            print(f"[ArmGamepad]  idx={arm_idx_auto}: {joy_arm.get_name()}")
        else:
            with lock: state["arm_gamepad_name"]="none"; state["arm_gamepad_axes"]={}; state["arm_gamepad_buttons"]={}

        if not joy_base and not joy_arm:
            time.sleep(1); continue

        try:
            while True:
                pygame.event.pump()

                # ── Base gamepad (RadioMaster) ────────────────────────────
                if joy_base:
                    axes = {str(i): round(joy_base.get_axis(i),4) for i in range(joy_base.get_numaxes())}
                    btns = {str(i): bool(joy_base.get_button(i)) for i in range(joy_base.get_numbuttons())}
                    with lock:
                        state["gamepad_axes"]=axes; state["gamepad_buttons"]=btns
                        sp=state["base_speed"]; rs=state["rot_speed"]
                        lh=state["lift_height"]; sel=state["selected_joint"]
                    nx=ny=nth=0.0; nlh=lh
                    for ai,cfg in bindings.get("axes",{}).items():
                        raw=float(axes.get(ai,0)); v=apply_dz(raw,cfg.get("deadzone",.1))*cfg.get("scale",1)
                        if cfg.get("invert"): v=-v
                        act=cfg.get("action","none")
                        if act=="x_vel": nx=v*sp
                        elif act=="y_vel": ny=v*sp
                        elif act=="theta_vel": nth=v*rs
                        elif act=="lift" and abs(v)>.05: nlh=max(0,lh-v*3)
                        elif act in("arm_left","arm_right") and abs(v)>.05:
                            j=ARM_JOINTS[sel]; side="arm_left" if act=="arm_left" else "arm_right"
                            with lock: state[side][j]=max(-100,min(100,state[side][j]+v*2))
                    with lock: state["base_cmd"]={"x":nx,"y":ny,"theta":nth}; state["lift_height"]=nlh
                    for bi,cfg in bindings.get("buttons",{}).items():
                        cur=btns.get(bi,False); prev=last_btns.get(bi,False)
                        if cur and not prev:
                            act=cfg.get("action","none")
                            with lock:
                                if act=="joint_next": state["selected_joint"]=(sel+1)%len(ARM_JOINTS)
                                elif act=="joint_prev": state["selected_joint"]=(sel-1)%len(ARM_JOINTS)
                                elif act=="speed_up": state["base_speed"]=min(1.0,sp+.05)
                                elif act=="speed_down": state["base_speed"]=max(.05,sp-.05)
                                elif act=="stop_base": state["base_cmd"]={"x":0,"y":0,"theta":0}
                    last_btns=dict(btns)

                # ── Arm gamepad (PS4) ─────────────────────────────────────
                if joy_arm:
                    a_axes = {str(i): round(joy_arm.get_axis(i),4) for i in range(joy_arm.get_numaxes())}
                    a_btns = {str(i): bool(joy_arm.get_button(i)) for i in range(joy_arm.get_numbuttons())}
                    with lock:
                        state["arm_gamepad_axes"]=a_axes; state["arm_gamepad_buttons"]=a_btns
                        asp = arm_bindings.get("arm_speed", 2.0)
                        side = state["arm_control_side"]

                    # Sticks → joint deltas (joints 1-4)
                    deltas = {j: 0.0 for j in ARM_JOINTS}
                    for ai, cfg in arm_bindings.get("axes", {}).items():
                        raw = float(a_axes.get(ai, 0))
                        v = apply_dz(raw, cfg.get("deadzone", 0.12)) * cfg.get("scale", 1.0)
                        if cfg.get("invert"): v = -v
                        joint = cfg.get("joint")
                        if joint in deltas: deltas[joint] += v * asp

                    # L2/R2 → wrist_roll differential  (rest=-1 → normalized 0..1)
                    l2_v = float(a_axes.get(str(arm_bindings.get("trigger_l2",4)), -1.0))
                    r2_v = float(a_axes.get(str(arm_bindings.get("trigger_r2",5)), -1.0))
                    l2 = max(0.0, (l2_v + 1.0) / 2.0)
                    r2 = max(0.0, (r2_v + 1.0) / 2.0)
                    wr = (r2 - l2) * asp * 0.8
                    if abs(wr) > 0.01: deltas["wrist_roll"] = wr

                    sides = ["arm_left","arm_right"] if side=="both" else [f"arm_{side}"]
                    with lock:
                        for s in sides:
                            for j, d in deltas.items():
                                if j != "gripper" and abs(d) > 0.01:
                                    state[s][j] = max(-100, min(100, state[s][j] + d))

                    # Held buttons → gripper open/close
                    for bi, cfg in arm_bindings.get("buttons", {}).items():
                        if a_btns.get(bi, False):
                            act = cfg.get("action","")
                            with lock:
                                for s in sides:
                                    if act=="gripper_close":
                                        state[s]["gripper"] = max(-100, state[s]["gripper"] - asp*0.8)
                                    elif act=="gripper_open":
                                        state[s]["gripper"] = min(100,  state[s]["gripper"] + asp*0.8)

                    # Rising-edge button actions
                    for bi, cfg in arm_bindings.get("buttons", {}).items():
                        cur=a_btns.get(bi,False); prev=arm_last_btns.get(bi,False)
                        if cur and not prev:
                            act = cfg.get("action","")
                            with lock:
                                asp2 = arm_bindings.get("arm_speed", 2.0)
                                cur_side = state["arm_control_side"]
                                if act=="switch_left":    state["arm_control_side"]="left"
                                elif act=="switch_right": state["arm_control_side"]="right"
                                elif act=="switch_both":  state["arm_control_side"]="both"
                                elif act=="switch_cycle":
                                    nxt = _SIDE_CYCLE[(_SIDE_CYCLE.index(cur_side)+1) % len(_SIDE_CYCLE)]
                                    state["arm_control_side"] = nxt
                                    print(f"[ArmGamepad] arm control → {nxt}")
                                elif act=="speed_up":   arm_bindings["arm_speed"]=min(10.0,asp2+0.5)
                                elif act=="speed_down": arm_bindings["arm_speed"]=max(0.2, asp2-0.5)
                                elif act=="home_arms":
                                    state["arm_left"]  = {j:0.0 for j in ARM_JOINTS}
                                    state["arm_right"] = {j:0.0 for j in ARM_JOINTS}
                    arm_last_btns = dict(a_btns)

                time.sleep(1/60)
        except Exception as e:
            print(f"[Gamepad] {e}"); time.sleep(1)

threading.Thread(target=gamepad_loop, daemon=True).start()

# ── Inference thread ──────────────────────────────────────────────────────────
_infer_proc = None

def start_inference(model_path):
    global _infer_proc
    stop_inference()
    # Pure inference via lerobot_rollout (no dataset recording).
    # Uses alohamini_client → connects to same Pi host over ZMQ.
    # controller send_loop pauses while inference_mode is True (avoid cmd-port conflict).
    cmd = [sys.executable, "-m", "lerobot.scripts.lerobot_rollout",
           "--strategy.type=base",
           "--robot.type=alohamini_client",
           f"--robot.remote_ip={REMOTE_IP}",
           "--robot.robot_model=alohamini1",
           f"--policy.path={model_path}",
           "--task=teleop policy",
           "--fps=20",
           "--display_data=false"]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "src"))
    _infer_proc = subprocess.Popen(cmd, env=env)
    with lock: state["inference_mode"]=True; state["inference_status"]="running"

def stop_inference():
    global _infer_proc
    if _infer_proc:
        _infer_proc.terminate()
        _infer_proc = None
    with lock: state["inference_mode"]=False; state["inference_status"]="idle"

def infer_watch():
    global _infer_proc
    while True:
        if _infer_proc and _infer_proc.poll() is not None:
            rc = _infer_proc.returncode
            _infer_proc = None
            with lock:
                state["inference_mode"]=False
                state["inference_status"]= "idle" if rc==0 else f"exited({rc})"
            print(f"[Inference] process exited rc={rc}")
        time.sleep(1)

threading.Thread(target=infer_watch, daemon=True).start()

# ── Flask ─────────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/rawcam/<int:idx>')
def rawcam_stream(idx):
    """Proxy MJPEG stream from robot_cam_server.py on Pi — simple passthrough."""
    import urllib.request
    url = f"http://{REMOTE_IP}:{CAM_SERVER_PORT}/cam/{idx}"
    def gen():
        while True:
            try:
                req = urllib.request.urlopen(url, timeout=10)
                while True:
                    chunk = req.read(8192)
                    if not chunk: break
                    yield chunk
            except Exception:
                time.sleep(2)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route('/rawcam_snap/<int:idx>')
def rawcam_snap(idx):
    import urllib.request
    try:
        data = urllib.request.urlopen(f"http://{REMOTE_IP}:{CAM_SERVER_PORT}/snap/{idx}", timeout=3).read()
        return Response(data, mimetype="image/jpeg")
    except Exception:
        return "no frame", 404

@app.route('/camera/<name>')
def camera_stream(name):
    def gen():
        while True:
            with lock: b64 = state["cameras"].get(name, "")
            if b64:
                try:
                    data = base64.b64decode(b64)
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
                except: pass
            time.sleep(1/25)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route('/camera_labels', methods=['GET'])
def get_cam_labels():
    return jsonify(labels=cam_labels, parts=ROBOT_PARTS)

@app.route('/camera_labels', methods=['POST'])
def set_cam_labels():
    d = request.json
    cam_name = d.get('camera')
    part     = d.get('part', '')
    note     = d.get('note', '')
    if cam_name:
        cam_labels[cam_name] = {'part': part, 'note': note}
        save_cam_labels()
    return jsonify(ok=True, labels=cam_labels)

@app.route('/camera_snapshot/<name>')
def camera_snapshot(name):
    with lock: b64 = state["cameras"].get(name, "")
    if not b64: return "no image", 404
    return Response(base64.b64decode(b64), mimetype="image/jpeg")

@app.route('/base', methods=['POST'])
def base_cmd():
    cmd = request.json.get('cmd','stop')
    with lock: sp=state["base_speed"]; rs=state["rot_speed"]; lh=state["lift_height"]
    x=y=theta=0.0; lv=0
    if   cmd=='w': x=sp
    elif cmd=='s': x=-sp
    elif cmd=='a': theta=rs
    elif cmd=='d': theta=-rs
    elif cmd=='z': y=sp
    elif cmd=='x': y=-sp
    elif cmd=='u': lv=1
    elif cmd=='j': lv=-1
    elif cmd=='r':
        with lock: state["base_speed"]=min(1.0,sp+.05)
    elif cmd=='f':
        with lock: state["base_speed"]=max(.05,sp-.05)
    nlh=lh+lv*3.0
    with lock: state["base_cmd"]={"x":x,"y":y,"theta":theta}; state["lift_height"]=nlh; sp=state["base_speed"]
    return jsonify(lift=nlh,speed=sp)

@app.route('/arm', methods=['POST'])
def arm_cmd():
    d=request.json; side=d.get('side','left'); joint=d.get('joint'); val=float(d.get('value',0))
    with lock:
        if side=='left': state["arm_left"][joint]=val
        else: state["arm_right"][joint]=val
    return jsonify(ok=True)

@app.route('/status')
def status():
    with lock:
        return jsonify(
            lift=state["lift_height"], speed=state["base_speed"],
            gamepad=state["gamepad_name"], connected=state["connected"],
            selected_joint=state["selected_joint"],
            arms={"left":dict(state["arm_left"]),"right":dict(state["arm_right"])},
            gamepad_axes=state["gamepad_axes"], gamepad_buttons=state["gamepad_buttons"],
            arm_gamepad=state["arm_gamepad_name"],
            arm_gamepad_axes=state["arm_gamepad_axes"],
            arm_gamepad_buttons=state["arm_gamepad_buttons"],
            arm_control_side=state["arm_control_side"],
            arms_disarmed=state["arms_disarmed"],
            arm_speed=arm_bindings.get("arm_speed", 2.0),
            odom=dict(state["odom"]),
            cameras=state["camera_names"],
            camera_labels=cam_labels,
            rawcam_devs=CAM_SERVER_DEVS,
            inference_mode=state["inference_mode"],
            inference_status=state["inference_status"],
            recording=state["recording"],
            rec_dataset=state["rec_dataset"],
            rec_episode=state["rec_episode"],
            rec_frames=state["rec_frames"],
            waypoints=state["waypoints"],
            waypoint_active=state["waypoint_active"],
            waypoint_idx=state["waypoint_idx"],
        )

@app.route('/arm/side', methods=['POST'])
def arm_side():
    side = request.json.get('side','left')
    if side not in ('left','right','both'): return jsonify(error="invalid"), 400
    with lock: state["arm_control_side"] = side
    return jsonify(side=side)

@app.route('/arm/disarm', methods=['POST'])
def arm_disarm():
    """Disable torque on all arm motors (Pi-side via ZMQ special key)."""
    with lock: state["arms_disarmed"] = True
    # Send disarm command a few times to ensure delivery
    payload = json.dumps({"__disarm_arms": True,
                          "x.vel":0,"y.vel":0,"theta.vel":0,
                          "lift_axis.height_mm": state["lift_height"]}).encode()
    for _ in range(5):
        try: cmd_sock.send(payload, flags=1)
        except: pass
        time.sleep(0.05)
    return jsonify(ok=True, disarmed=True)

@app.route('/arm/rearm', methods=['POST'])
def arm_rearm():
    """Re-enable torque on arm motors and sync positions from current obs."""
    with lock:
        state["arms_disarmed"] = False
    payload = json.dumps({"__arm_arms": True,
                          "x.vel":0,"y.vel":0,"theta.vel":0,
                          "lift_axis.height_mm": state["lift_height"]}).encode()
    for _ in range(5):
        try: cmd_sock.send(payload, flags=1)
        except: pass
        time.sleep(0.05)
    return jsonify(ok=True, disarmed=False)

@app.route('/arm/preset', methods=['POST'])
def arm_preset():
    """Execute a named preset position smoothly."""
    name = request.json.get('preset','home')
    sides_req = request.json.get('sides', None)  # None = use arm_control_side
    preset = ARM_PRESETS.get(name)
    if not preset: return jsonify(error=f"unknown preset: {name}"), 400
    with lock:
        disarmed = state["arms_disarmed"]
        s = sides_req or state["arm_control_side"]
    if disarmed: return jsonify(error="arms are disarmed"), 400
    sides = ["arm_left","arm_right"] if s == "both" else [f"arm_{s}"]
    smooth_move([x.replace("arm_","") for x in sides], preset)
    return jsonify(ok=True, preset=name, sides=sides)

@app.route('/arm_bindings', methods=['GET'])
def get_arm_bindings(): return jsonify(arm_bindings)

@app.route('/arm_bindings', methods=['POST'])
def set_arm_bindings():
    global arm_bindings; arm_bindings=request.json; save_arm_bindings(); return jsonify(ok=True)

@app.route('/arm_bindings/reset', methods=['POST'])
def reset_arm_bindings():
    global arm_bindings; arm_bindings=json.loads(json.dumps(DEFAULT_ARM_BINDINGS))
    save_arm_bindings(); return jsonify(arm_bindings)

@app.route('/arm_settings')
def arm_settings_page():
    p = Path(__file__).parent / "ui_arm_settings.html"
    if p.exists(): return p.read_text(encoding="utf-8")
    return "<h2>ui_arm_settings.html missing</h2>"

@app.route('/bindings', methods=['GET'])
def get_bindings(): return jsonify(bindings)

@app.route('/bindings', methods=['POST'])
def set_bindings():
    global bindings; bindings=request.json; save_bindings(); return jsonify(ok=True)

@app.route('/bindings/reset', methods=['POST'])
def reset_bindings():
    global bindings; bindings=json.loads(json.dumps(DEFAULT_BINDINGS)); save_bindings(); return jsonify(bindings)

@app.route('/waypoints', methods=['POST'])
def waypoints_api():
    d=request.json; action=d.get('action')
    with lock:
        if action=='add':
            state["waypoints"].append({"x":d.get('x',0),"y":d.get('y',0),"label":d.get('label','')})
        elif action=='clear':
            state["waypoints"]=[]; state["waypoint_active"]=False; state["waypoint_idx"]=0
        elif action=='start':
            state["waypoint_active"]=True; state["waypoint_idx"]=0
        elif action=='stop':
            state["waypoint_active"]=False
        elif action=='reset_odom':
            state["odom"]={"x":0,"y":0,"theta":0}
    return jsonify(ok=True)

@app.route('/record', methods=['POST'])
def record_api():
    d = request.json; action = d.get('action')
    if action == 'start':
        ds = d.get('dataset', 'demo').strip() or 'demo'
        rec_start(ds)
    elif action == 'stop':
        rec_stop()
    with lock:
        return jsonify(recording=state["recording"], episode=state["rec_episode"], frames=state["rec_frames"])

@app.route('/recordings')
def recordings_list():
    out = []
    if REC_DIR.exists():
        for ds in sorted(REC_DIR.iterdir()):
            if ds.is_dir():
                eps = sorted(ds.glob("episode_*"))
                out.append({"dataset": ds.name, "episodes": len(eps)})
    return jsonify(out)

@app.route('/checkpoints')
def checkpoints():
    """Scan for trained model checkpoints on this PC."""
    found = []
    roots = [Path(__file__).parents[1] / "outputs" / "train",
             Path.cwd() / "outputs" / "train"]
    for root in roots:
        if not root.exists(): continue
        for pm in root.glob("*/checkpoints/*/pretrained_model"):
            found.append(str(pm))
        for pm in root.glob("*/checkpoints/last/pretrained_model"):
            s = str(pm)
            if s not in found: found.append(s)
    return jsonify(sorted(set(found)))

@app.route('/inference', methods=['POST'])
def inference_api():
    d=request.json; action=d.get('action')
    if action=='start':
        model=d.get('model','')
        with lock: state["inference_model"]=model
        start_inference(model)
    elif action=='stop':
        stop_inference()
    return jsonify(status=state["inference_status"])

@app.route('/mesh/<path:filename>')
def serve_mesh(filename):
    return send_from_directory(str(MESH_DIR), filename)

@app.route('/')
def index(): return MAIN_HTML

@app.route('/settings')
def settings_page(): return SETTINGS_HTML

# ── Load HTML pages ───────────────────────────────────────────────────────────
def _load_main_html():
    p = Path(__file__).parent / "ui_main.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "<h2>ui_main.html missing</h2>"

def _load_settings_html():
    # Extract SETTINGS_HTML constant from controller_v2.py (no import → no side effects)
    v2 = Path(__file__).parent / "controller_v2.py"
    if v2.exists():
        txt = v2.read_text(encoding="utf-8")
        marker = 'SETTINGS_HTML = """'
        i = txt.find(marker)
        if i != -1:
            start = i + len(marker)
            end = txt.find('"""', start)
            if end != -1:
                return txt[start:end]
    return "<h2>settings unavailable</h2>"

MAIN_HTML     = _load_main_html()
SETTINGS_HTML = _load_settings_html()

if __name__ == '__main__':
    print(f"Open:     http://localhost:{WEB_PORT}")
    print(f"Settings: http://localhost:{WEB_PORT}/settings")
    print(f"Robot:    {REMOTE_IP}  (cmd:{CMD_PORT} obs:{OBS_PORT})")
    app.run(host='0.0.0.0', port=WEB_PORT, threaded=True)
