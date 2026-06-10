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

# ── Config ────────────────────────────────────────────────────────────────────
REMOTE_IP  = "192.168.31.170"
CMD_PORT   = 5555
OBS_PORT   = 5556
WEB_PORT   = 8080
BINDINGS_FILE = Path(__file__).parent / "gamepad_bindings.json"
MESH_DIR   = Path(r"D:\Проекты\Kiborg\AlohaMini\simulation\src\Aloha\meshes")

# ── ZMQ ───────────────────────────────────────────────────────────────────────
ctx = zmq.Context()
cmd_sock = ctx.socket(zmq.PUSH)
cmd_sock.connect(f"tcp://{REMOTE_IP}:{CMD_PORT}")
obs_sock = ctx.socket(zmq.PULL)
obs_sock.connect(f"tcp://{REMOTE_IP}:{OBS_PORT}")
obs_sock.setsockopt(zmq.RCVTIMEO, 80)

ARM_JOINTS = ["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"]

# ── State ─────────────────────────────────────────────────────────────────────
state = {
    "lift_height":    10.0,
    "base_speed":     0.30,
    "rot_speed":      60.0,
    "base_cmd":       {"x":0.0,"y":0.0,"theta":0.0},
    "arm_left":       {j:0.0 for j in ARM_JOINTS},
    "arm_right":      {j:0.0 for j in ARM_JOINTS},
    "selected_joint": 0,
    "gamepad_name":   "none",
    "gamepad_axes":   {},
    "gamepad_buttons":{},
    "connected":      False,
    # Cameras: name → base64 jpeg
    "cameras":        {},
    "camera_names":   [],
    # Odometry (dead reckoning)
    "odom":           {"x":0.0,"y":0.0,"theta":0.0},
    # Inference
    "inference_mode": False,
    "inference_model": "",
    "inference_status":"idle",
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
        "3": {"action":"lift",     "scale":1.0,"deadzone":0.10,"invert":True, "label":"Right Gimbal Y"},
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

        cmd_sock.send_string(json.dumps(build_action()))
        time.sleep(1/30)

threading.Thread(target=send_loop, daemon=True).start()

# ── Gamepad thread ────────────────────────────────────────────────────────────
def apply_dz(v, dz):
    if abs(v) < dz: return 0.0
    return (v - math.copysign(dz, v)) / (1.0 - dz)

def gamepad_loop():
    pygame.init(); pygame.joystick.init()
    last_btns = {}; last_count = 0
    while True:
        pygame.joystick.quit(); pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count == 0:
            if last_count != 0:
                with lock: state["gamepad_name"]="none"; state["gamepad_axes"]={}; state["gamepad_buttons"]={}
            last_count = 0; time.sleep(1); continue
        if count != last_count:
            print(f"[Gamepad] {count} device(s) detected")
        last_count = count
        joy = pygame.joystick.Joystick(0); joy.init()
        with lock: state["gamepad_name"] = joy.get_name()
        try:
            while True:
                pygame.event.pump()
                axes = {str(i): round(joy.get_axis(i),4) for i in range(joy.get_numaxes())}
                btns = {str(i): bool(joy.get_button(i)) for i in range(joy.get_numbuttons())}
                with lock: state["gamepad_axes"]=axes; state["gamepad_buttons"]=btns
                with lock: sp=state["base_speed"]; rs=state["rot_speed"]; lh=state["lift_height"]; sel=state["selected_joint"]
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
                last_btns=dict(btns); time.sleep(1/60)
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
            odom=dict(state["odom"]),
            cameras=state["camera_names"],
            inference_mode=state["inference_mode"],
            inference_status=state["inference_status"],
            waypoints=state["waypoints"],
            waypoint_active=state["waypoint_active"],
            waypoint_idx=state["waypoint_idx"],
        )

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
