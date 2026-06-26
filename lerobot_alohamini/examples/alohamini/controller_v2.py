"""
AlohaMini Controller v2
- 3D arm visualization via Three.js + URDF Loader
- Steam Input-style gamepad binding (axis calibration, remapping, deadzone)
- Key remapping
- Flask + ZMQ
"""

import json, threading, time, math, os
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response
import zmq
import pygame

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
URDF_PATH  = Path(r"D:\Проекты\Kiborg\AlohaMini\simulation\src\Aloha\urdf\Aloha.urdf")
MESH_DIR   = Path(r"D:\Проекты\Kiborg\AlohaMini\simulation\src\Aloha\meshes")
BINDINGS_FILE = BASE_DIR / "gamepad_bindings.json"

REMOTE_IP = "172.24.93.157"
CMD_PORT  = 5555
OBS_PORT  = 5556
WEB_PORT  = 8080

# ── ZMQ ───────────────────────────────────────────────────────────────────────
ctx = zmq.Context()
cmd_sock = ctx.socket(zmq.PUSH)
cmd_sock.connect(f"tcp://{REMOTE_IP}:{CMD_PORT}")
obs_sock = ctx.socket(zmq.PULL)
obs_sock.connect(f"tcp://{REMOTE_IP}:{OBS_PORT}")
obs_sock.setsockopt(zmq.RCVTIMEO, 50)

# ── Constants ─────────────────────────────────────────────────────────────────
ARM_JOINTS = ["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"]

# Default gamepad bindings (Steam-style)
DEFAULT_BINDINGS = {
    "axes": {
        "0": {"action": "y_vel",    "scale": 1.0,  "deadzone": 0.10, "invert": False, "label": "Left X"},
        "1": {"action": "x_vel",    "scale": 1.0,  "deadzone": 0.10, "invert": True,  "label": "Left Y"},
        "2": {"action": "theta_vel","scale": 1.0,  "deadzone": 0.10, "invert": False, "label": "Right X"},
        "3": {"action": "lift",     "scale": 1.0,  "deadzone": 0.10, "invert": True,  "label": "Right Y"},
        "4": {"action": "arm_left", "scale": 1.0,  "deadzone": 0.05, "invert": False, "label": "L Trigger"},
        "5": {"action": "arm_right","scale": 1.0,  "deadzone": 0.05, "invert": False, "label": "R Trigger"},
    },
    "buttons": {
        "0": {"action": "joint_prev", "label": "A"},
        "1": {"action": "joint_next", "label": "B"},
        "2": {"action": "none",       "label": "X"},
        "3": {"action": "none",       "label": "Y"},
        "4": {"action": "speed_down", "label": "LB"},
        "5": {"action": "speed_up",   "label": "RB"},
    },
    "key_map": {
        "w": "x_vel+", "s": "x_vel-",
        "a": "theta+", "d": "theta-",
        "z": "y_vel+", "x": "y_vel-",
        "u": "lift+",  "j": "lift-",
        "r": "speed+", "f": "speed-",
    }
}

# ── State ─────────────────────────────────────────────────────────────────────
state = {
    "lift_height": 10.0,
    "base_speed":  0.30,
    "rot_speed":   60.0,
    "base_cmd":    {"x": 0.0, "y": 0.0, "theta": 0.0},
    "arm_left":    {j: 0.0 for j in ARM_JOINTS},
    "arm_right":   {j: 0.0 for j in ARM_JOINTS},
    "selected_joint": 0,
    "gamepad_name":   "none",
    "gamepad_axes":   {},
    "gamepad_buttons":{},
    "connected":      False,
}
lock = threading.Lock()
bindings = {}
initialized = threading.Event()

def load_bindings():
    global bindings
    if BINDINGS_FILE.exists():
        try:
            bindings = json.loads(BINDINGS_FILE.read_text())
            return
        except Exception:
            pass
    bindings = json.loads(json.dumps(DEFAULT_BINDINGS))

def save_bindings():
    BINDINGS_FILE.write_text(json.dumps(bindings, indent=2))

load_bindings()

# ── Build ZMQ action ──────────────────────────────────────────────────────────
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

# ── Observation thread ────────────────────────────────────────────────────────
def obs_loop():
    while True:
        try:
            obs = json.loads(obs_sock.recv().decode())
            with lock:
                state["lift_height"] = obs.get("lift_axis.height_mm", state["lift_height"])
                for j in ARM_JOINTS:
                    v = obs.get(f"arm_left_{j}.pos")
                    if v is not None: state["arm_left"][j] = v
                    v = obs.get(f"arm_right_{j}.pos")
                    if v is not None: state["arm_right"][j] = v
                state["connected"] = True
            initialized.set()
        except zmq.Again:
            pass
        except Exception:
            time.sleep(0.05)

threading.Thread(target=obs_loop, daemon=True).start()

# ── Send loop ─────────────────────────────────────────────────────────────────
def send_loop():
    initialized.wait(timeout=5.0)
    print("[Controller] Sending commands.")
    while True:
        cmd_sock.send_string(json.dumps(build_action()))
        time.sleep(1/30)

threading.Thread(target=send_loop, daemon=True).start()

# ── Gamepad thread ────────────────────────────────────────────────────────────
AXIS_ACTIONS = {
    "x_vel":    lambda v, s: setattr_state("base_cmd", "x", v * s["base_speed"]),
    "y_vel":    lambda v, s: setattr_state("base_cmd", "y", v * s["base_speed"]),
    "theta_vel":lambda v, s: setattr_state("base_cmd", "theta", v * s["rot_speed"]),
}

def setattr_state(key, sub, val):
    state[key][sub] = val

def apply_deadzone(v, dz):
    if abs(v) < dz: return 0.0
    return (v - math.copysign(dz, v)) / (1.0 - dz)

def gamepad_loop():
    pygame.init()
    pygame.joystick.init()
    last_buttons = {}
    last_count = 0

    while True:
        # Hot-plug: reinit joystick subsystem to detect new devices
        pygame.joystick.quit()
        pygame.joystick.init()
        count = pygame.joystick.get_count()

        if count == 0:
            if last_count != 0:
                print("[Gamepad] Disconnected")
                with lock: state["gamepad_name"] = "none"; state["gamepad_axes"] = {}; state["gamepad_buttons"] = {}
            last_count = 0
            time.sleep(1); continue

        if count != last_count:
            print(f"[Gamepad] {count} device(s) detected")
        last_count = count

        joy = pygame.joystick.Joystick(0)
        joy.init()
        with lock: state["gamepad_name"] = joy.get_name()
        print(f"[Gamepad] {joy.get_name()} — {joy.get_numaxes()} axes, {joy.get_numbuttons()} buttons")

        try:
            while True:
                pygame.event.pump()
                axes_raw = {str(i): round(joy.get_axis(i), 4) for i in range(joy.get_numaxes())}
                btns_raw = {str(i): bool(joy.get_button(i)) for i in range(joy.get_numbuttons())}

                with lock:
                    state["gamepad_axes"] = axes_raw
                    state["gamepad_buttons"] = btns_raw
                    sp = state["base_speed"]
                    rs = state["rot_speed"]
                    lh = state["lift_height"]
                    sel = state["selected_joint"]

                new_x = new_y = new_theta = 0.0
                new_lh = lh

                for ai, cfg in bindings.get("axes", {}).items():
                    raw = float(axes_raw.get(ai, 0.0))
                    dz = cfg.get("deadzone", 0.1)
                    v  = apply_deadzone(raw, dz) * cfg.get("scale", 1.0)
                    if cfg.get("invert"): v = -v
                    act = cfg.get("action", "none")
                    if   act == "x_vel":     new_x     = v * sp
                    elif act == "y_vel":     new_y     = v * sp
                    elif act == "theta_vel": new_theta = v * rs
                    elif act == "lift":
                        if abs(v) > 0.05: new_lh = max(0, lh - v * 3.0)
                    elif act == "arm_left":
                        if abs(v) > 0.05:
                            j = ARM_JOINTS[sel]
                            with lock:
                                state["arm_left"][j] = max(-100, min(100, state["arm_left"][j] + v * 2))
                    elif act == "arm_right":
                        if abs(v) > 0.05:
                            j = ARM_JOINTS[sel]
                            with lock:
                                state["arm_right"][j] = max(-100, min(100, state["arm_right"][j] + v * 2))

                with lock:
                    state["base_cmd"] = {"x": new_x, "y": new_y, "theta": new_theta}
                    state["lift_height"] = new_lh

                # Buttons
                for bi, cfg in bindings.get("buttons", {}).items():
                    cur = btns_raw.get(bi, False)
                    prev = last_buttons.get(bi, False)
                    if cur and not prev:
                        act = cfg.get("action", "none")
                        with lock:
                            if   act == "joint_next": state["selected_joint"] = (sel + 1) % len(ARM_JOINTS)
                            elif act == "joint_prev": state["selected_joint"] = (sel - 1) % len(ARM_JOINTS)
                            elif act == "speed_up":   state["base_speed"] = min(1.0, sp + 0.05)
                            elif act == "speed_down": state["base_speed"] = max(0.05, sp - 0.05)
                last_buttons = dict(btns_raw)
                time.sleep(1/60)
        except Exception as e:
            print(f"[Gamepad] error: {e}")
            time.sleep(1)

threading.Thread(target=gamepad_loop, daemon=True).start()

# ── Flask ─────────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/mesh/<path:filename>')
def serve_mesh(filename):
    return send_from_directory(str(MESH_DIR), filename)

@app.route('/urdf')
def serve_urdf():
    if not URDF_PATH.exists():
        return "URDF not found", 404
    content = URDF_PATH.read_text()
    content = content.replace('package://Aloha/meshes/', '/mesh/')
    return Response(content, mimetype='application/xml')

@app.route('/base', methods=['POST'])
def base_cmd():
    cmd = request.json.get('cmd', 'stop')
    with lock:
        sp = state["base_speed"]
        rs = state["rot_speed"]
        lh = state["lift_height"]

    x = y = theta = 0.0; lv = 0
    if   cmd == 'w': x = sp
    elif cmd == 's': x = -sp
    elif cmd == 'a': theta = rs
    elif cmd == 'd': theta = -rs
    elif cmd == 'z': y = sp
    elif cmd == 'x': y = -sp
    elif cmd == 'u': lv = 1
    elif cmd == 'j': lv = -1
    elif cmd == 'r':
        with lock: state["base_speed"] = min(1.0, state["base_speed"] + 0.05)
    elif cmd == 'f':
        with lock: state["base_speed"] = max(0.05, state["base_speed"] - 0.05)

    new_lh = lh + lv * 3.0
    with lock:
        state["base_cmd"] = {"x": x, "y": y, "theta": theta}
        state["lift_height"] = new_lh
        sp = state["base_speed"]

    return jsonify(lift=new_lh, speed=sp)

@app.route('/arm', methods=['POST'])
def arm_cmd():
    d = request.json
    side = d.get('side', 'left')
    joint = d.get('joint')
    value = float(d.get('value', 0))
    with lock:
        if side == 'left':  state["arm_left"][joint] = value
        else:               state["arm_right"][joint] = value
    return jsonify(ok=True)

@app.route('/status')
def status():
    with lock:
        return jsonify(
            lift=state["lift_height"],
            speed=state["base_speed"],
            gamepad=state["gamepad_name"],
            connected=state["connected"],
            selected_joint=state["selected_joint"],
            arms={"left": dict(state["arm_left"]), "right": dict(state["arm_right"])},
            gamepad_axes=state["gamepad_axes"],
            gamepad_buttons=state["gamepad_buttons"],
        )

@app.route('/bindings', methods=['GET'])
def get_bindings():
    return jsonify(bindings)

@app.route('/bindings', methods=['POST'])
def set_bindings():
    global bindings
    bindings = request.json
    save_bindings()
    return jsonify(ok=True)

@app.route('/bindings/reset', methods=['POST'])
def reset_bindings():
    global bindings
    bindings = json.loads(json.dumps(DEFAULT_BINDINGS))
    save_bindings()
    return jsonify(bindings)

@app.route('/')
def index():
    return INDEX_HTML

@app.route('/settings')
def settings():
    return SETTINGS_HTML

# ── HTML pages ────────────────────────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>AlohaMini Control</title>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#0a0a0a;color:#ddd;font-family:monospace;overflow-x:hidden}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:6px 12px;
        background:#111;border-bottom:1px solid #222;font-size:12px}
.dot{width:9px;height:9px;border-radius:50%;background:#f00;display:inline-block;margin-right:5px;transition:.3s}
.dot.ok{background:#0f0}
a.nav{color:#0af;text-decoration:none;padding:4px 8px;border:1px solid #0af;border-radius:5px;font-size:11px}

.main{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:8px}
@media(max-width:700px){.main{grid-template-columns:1fr}}

.card{background:#131313;border:1px solid #222;border-radius:10px;padding:10px}
.card-title{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}

/* Dpad */
.dpad{display:grid;grid-template-columns:repeat(3,60px);grid-template-rows:repeat(3,60px);gap:4px;margin:0 auto 8px;width:max-content}
.db{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;
    display:flex;align-items:center;justify-content:center;font-size:20px;
    cursor:pointer;touch-action:none;color:#aaa;user-select:none}
.db:active,.db.on{background:#0af;color:#000;border-color:#0af}
.stopb{background:#1a0000;border-color:#400}
.stopb:active,.stopb.on{background:#f33;color:#fff}

/* Lift */
.lift-wrap{display:flex;flex-direction:column;gap:4px}
.lift-bar-outer{flex:1;background:#111;border:1px solid #222;border-radius:8px;overflow:hidden;min-height:120px;position:relative}
.lift-bar-inner{position:absolute;bottom:0;left:0;right:0;background:linear-gradient(0deg,#06f,#0af);border-radius:8px;transition:height .15s}
.lift-label{text-align:center;font-size:11px;color:#666;margin-top:2px}
.sm-btn{padding:6px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:6px;
        color:#aaa;cursor:pointer;touch-action:none;font-size:16px;flex:1;text-align:center}
.sm-btn:active,.sm-btn.on{background:#0af;color:#000}

/* 3D viewer */
#viewer{width:100%;height:300px;background:#0d0d14;border-radius:8px;position:relative}
#viewer canvas{border-radius:8px}
.arm-sel{display:flex;gap:4px;margin-bottom:6px}
.arm-tab{flex:1;padding:5px;background:#1a1a1a;border:1px solid #222;border-radius:6px;
         cursor:pointer;text-align:center;font-size:11px;color:#777}
.arm-tab.active{background:#0af;color:#000;border-color:#0af}
.arm-panel{display:none}.arm-panel.active{display:block}

/* Joint rows */
.jr{display:flex;align-items:center;gap:6px;padding:4px 2px;border-radius:6px;cursor:pointer}
.jr:hover{background:#1a1a1a}
.jr.sel{background:#0a1a2a;border-left:2px solid #0af;padding-left:6px}
.jdot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.jname{font-size:11px;color:#aaa;min-width:90px}
.jval{font-size:11px;color:#0af;min-width:38px;text-align:right}
.jbtns{margin-left:auto;display:flex;gap:3px}
.jb{width:26px;height:26px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:5px;
    color:#aaa;cursor:pointer;touch-action:none;font-size:14px}
.jb:active,.jb.on{background:#0af;color:#000}

/* Gamepad bar */
.gp-axis{display:flex;align-items:center;gap:6px;margin:3px 0;font-size:11px}
.gp-axis-label{min-width:70px;color:#666}
.gp-bar-wrap{flex:1;height:14px;background:#111;border-radius:7px;overflow:hidden;position:relative}
.gp-bar-neg{position:absolute;right:50%;top:0;bottom:0;background:#f55;border-radius:7px 0 0 7px}
.gp-bar-pos{position:absolute;left:50%;top:0;bottom:0;background:#0af;border-radius:0 7px 7px 0}
.gp-bar-center{position:absolute;left:50%;top:2px;bottom:2px;width:2px;transform:translateX(-50%);background:#333}
.gp-val{min-width:40px;text-align:right;color:#888}

/* Speed */
.speed-row{display:flex;align-items:center;gap:8px;font-size:12px;margin-top:6px}
</style>
</head>
<body>

<div class="topbar">
  <span><span class="dot" id="dot"></span><span id="conn_txt">Connecting…</span></span>
  <span id="gp_txt" style="color:#fa0;font-size:11px">No gamepad</span>
  <a class="nav" href="/settings">⚙ Bindings</a>
</div>

<div class="main">

  <!-- LEFT: Base + Lift -->
  <div>
    <div class="card">
      <div class="card-title">Base &nbsp;
        <span id="spd_v" style="color:#0af">0.30 m/s</span>
        <button class="sm-btn" id="r" style="width:40px;height:24px;font-size:12px;margin-left:6px">+</button>
        <button class="sm-btn" id="f" style="width:40px;height:24px;font-size:12px">−</button>
      </div>
      <div style="display:flex;gap:10px">
        <div class="dpad">
          <div></div><div class="db" id="w">▲</div><div></div>
          <div class="db" id="z">◄</div>
          <div class="db stopb" id="stop">■</div>
          <div class="db" id="x">►</div>
          <div class="db" id="a">↺</div>
          <div class="db" id="s">▼</div>
          <div class="db" id="d">↻</div>
        </div>
        <div style="flex:1;display:flex;flex-direction:column;gap:6px">
          <div class="card-title">Lift <span id="lift_v">0.0</span>mm</div>
          <div class="lift-bar-outer">
            <div class="lift-bar-inner" id="lift_bar" style="height:0%"></div>
          </div>
          <div style="display:flex;gap:4px">
            <div class="sm-btn" id="u">▲</div>
            <div class="sm-btn" id="j">▼</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Gamepad axes preview -->
    <div class="card" style="margin-top:8px">
      <div class="card-title">Gamepad Axes</div>
      <div id="gp_axes_preview"></div>
    </div>
  </div>

  <!-- RIGHT: 3D viewer + arm control -->
  <div>
    <div class="card">
      <div class="card-title">Arms</div>
      <div id="viewer"></div>
      <div class="arm-sel" style="margin-top:6px">
        <div class="arm-tab active" onclick="showArm('left',this)">◄ LEFT</div>
        <div class="arm-tab" onclick="showArm('right',this)">RIGHT ►</div>
      </div>
      <div class="arm-panel active" id="panel_left"></div>
      <div class="arm-panel" id="panel_right"></div>
    </div>
  </div>

</div>

<!-- Three.js + URDF Loader -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js"></script>
<script>
// ── Simple arm visualization (no URDF dependency, works offline) ─────────────
const JOINTS=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper'];
const JLABELS=['Shoulder Pan','Shoulder Lift','Elbow Flex','Wrist Flex','Wrist Roll','Gripper'];
const JCOLORS=['#f55','#fa5','#ff5','#5f5','#5af','#a5f'];
const armVals={left:{},right:{}};
JOINTS.forEach(j=>{armVals.left[j]=0;armVals.right[j]=0});
let selJoint=0;

// Three.js arm scene
let scene,camera,renderer,armMeshes={left:[],right:[]};
const SEG_LENGTHS=[0,70,60,50,35,20,14]; // base + 6 joints

function initThree(){
  const el=document.getElementById('viewer');
  scene=new THREE.Scene();
  scene.background=new THREE.Color(0x0d0d14);
  camera=new THREE.PerspectiveCamera(50,el.clientWidth/300,0.1,2000);
  camera.position.set(0,200,300);camera.lookAt(0,100,0);
  renderer=new THREE.WebGLRenderer({antialias:true});
  renderer.setSize(el.clientWidth,300);
  el.appendChild(renderer.domElement);
  scene.add(new THREE.AmbientLight(0xffffff,0.6));
  const dl=new THREE.DirectionalLight(0xffffff,0.8);
  dl.position.set(1,2,1);scene.add(dl);
  // Grid
  scene.add(new THREE.GridHelper(400,20,0x222222,0x1a1a1a));
  buildArmObjects('left',-60);
  buildArmObjects('right',60);
  animate();
}

function buildArmObjects(side,xoff){
  const mats=JCOLORS.map(c=>new THREE.MeshLambertMaterial({color:c}));
  const segs=[];
  for(let i=0;i<6;i++){
    const geo=new THREE.CylinderGeometry(4,4,SEG_LENGTHS[i+1],8);
    geo.translate(0,SEG_LENGTHS[i+1]/2,0);
    const mesh=new THREE.Mesh(geo,mats[i]);
    const pivot=new THREE.Object3D();
    pivot.add(mesh);
    segs.push({pivot,mesh});
  }
  // chain them
  let parent=scene;
  segs[0].pivot.position.set(xoff,10,0);
  for(let i=0;i<6;i++){
    parent.add(segs[i].pivot);
    if(i<5){
      segs[i+1].pivot.position.set(0,SEG_LENGTHS[i+1],0);
      segs[i].pivot.add(segs[i+1].pivot);
    }
    parent=segs[i].pivot;
  }
  armMeshes[side]=segs;
}

function updateArmPose(side){
  const v=armVals[side];
  const segs=armMeshes[side];
  if(!segs||!segs.length)return;
  const toRad=d=>d*Math.PI/180*0.9; // scale down for visual
  segs[0].pivot.rotation.y= toRad(v['shoulder_pan']||0);
  segs[1].pivot.rotation.z=-toRad(v['shoulder_lift']||0);
  segs[2].pivot.rotation.z=-toRad(v['elbow_flex']||0);
  segs[3].pivot.rotation.z=-toRad(v['wrist_flex']||0);
  segs[4].pivot.rotation.y= toRad(v['wrist_roll']||0);
  // gripper: scale mesh
  const g=v['gripper']||0;
  segs[5].mesh.scale.y=0.5+0.5*(100-g)/100;
}

function animate(){
  requestAnimationFrame(animate);
  updateArmPose('left');updateArmPose('right');
  renderer.render(scene,camera);
}

window.addEventListener('resize',()=>{
  const el=document.getElementById('viewer');
  if(!renderer)return;
  renderer.setSize(el.clientWidth,300);
  camera.aspect=el.clientWidth/300;camera.updateProjectionMatrix();
});

initThree();

// ── Mouse orbit ──────────────────────────────────────────────────────────────
let drag=false,lx=0,ly=0,camTheta=0,camPhi=0.7,camR=350;
const el=document.getElementById('viewer');
el.addEventListener('mousedown',e=>{drag=true;lx=e.clientX;ly=e.clientY});
window.addEventListener('mouseup',()=>drag=false);
window.addEventListener('mousemove',e=>{
  if(!drag)return;
  camTheta-=(e.clientX-lx)*0.01;camPhi=Math.max(0.1,Math.min(1.5,camPhi-(e.clientY-ly)*0.01));
  lx=e.clientX;ly=e.clientY;
  camera.position.set(camR*Math.sin(camTheta)*Math.cos(camPhi),camR*Math.sin(camPhi),camR*Math.cos(camTheta)*Math.cos(camPhi));
  camera.lookAt(0,100,0);
});
el.addEventListener('wheel',e=>{camR=Math.max(100,Math.min(800,camR+e.deltaY*0.5));
  camera.position.setLength(camR);camera.lookAt(0,100,0);});

// ── Joint panels ─────────────────────────────────────────────────────────────
function buildPanel(side){
  const p=document.getElementById('panel_'+side);
  p.innerHTML='';
  JOINTS.forEach((j,i)=>{
    const row=document.createElement('div');
    row.className='jr'+(i===0?' sel':'');row.id=`jr_${side}_${j}`;
    row.onclick=()=>selectJoint(i);
    row.innerHTML=`<div class="jdot" style="background:${JCOLORS[i]}"></div>
      <span class="jname">${JLABELS[i]}</span>
      <span class="jval" id="jv_${side}_${j}">0°</span>
      <div class="jbtns">
        <button class="jb" id="jm_${side}_${j}">−</button>
        <button class="jb" id="jp_${side}_${j}">+</button>
      </div>`;
    p.appendChild(row);
  });
  JOINTS.forEach((j,i)=>{
    let iv=null;
    const minus=document.getElementById(`jm_${side}_${j}`);
    const plus=document.getElementById(`jp_${side}_${j}`);
    function start(d){stop();selectJoint(i);adjust(side,j,d);iv=setInterval(()=>adjust(side,j,d),80);}
    function stop(){clearInterval(iv);}
    minus.addEventListener('pointerdown',e=>{e.preventDefault();start(-5)});
    minus.addEventListener('pointerup',e=>{e.preventDefault();stop()});
    minus.addEventListener('pointerleave',stop);
    plus.addEventListener('pointerdown',e=>{e.preventDefault();start(5)});
    plus.addEventListener('pointerup',e=>{e.preventDefault();stop()});
    plus.addEventListener('pointerleave',stop);
  });
}

function selectJoint(i){
  selJoint=i;
  ['left','right'].forEach(side=>{
    JOINTS.forEach((j,k)=>document.getElementById(`jr_${side}_${j}`)?.classList.toggle('sel',k===i));
  });
  fetch('/bindings').then(r=>r.json()).then(b=>{
    fetch('/status').then(r=>r.json()).then(d=>{
      // update server selected joint
    });
  });
}

async function adjust(side,joint,delta){
  armVals[side][joint]=Math.max(-100,Math.min(100,(armVals[side][joint]||0)+delta));
  document.getElementById(`jv_${side}_${joint}`).innerText=(armVals[side][joint]).toFixed(0)+'°';
  await fetch('/arm',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({side,joint,value:armVals[side][joint]})});
}

function showArm(side,el){
  document.querySelectorAll('.arm-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.arm-panel').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');document.getElementById('panel_'+side).classList.add('active');
}

buildPanel('left');buildPanel('right');

// ── Base buttons ─────────────────────────────────────────────────────────────
let activeCmd=null,cmdIv=null;
function startCmd(c){
  if(activeCmd===c)return;stopCmd();activeCmd=c;
  document.getElementById(c)?.classList.add('on');
  sendCmd(c);cmdIv=setInterval(()=>sendCmd(c),80);
}
function stopCmd(){
  if(activeCmd)document.getElementById(activeCmd)?.classList.remove('on');
  activeCmd=null;clearInterval(cmdIv);sendCmd('stop');
}
async function sendCmd(c){
  try{
    const r=await fetch('/base',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:c})});
    const d=await r.json();
    document.getElementById('spd_v').innerText=(d.speed||0.3).toFixed(2)+' m/s';
    const lh=d.lift||0;
    document.getElementById('lift_v').innerText=lh.toFixed(1);
    document.getElementById('lift_bar').style.height=Math.max(0,Math.min(100,lh/6)).toFixed(0)+'%';
    document.getElementById('dot').className='dot ok';
    document.getElementById('conn_txt').innerText='Connected ✓';
  }catch(e){document.getElementById('conn_txt').innerText='Error';}
}

['w','s','a','d','z','x','u','j','stop'].forEach(id=>{
  const el=document.getElementById(id);if(!el)return;
  el.addEventListener('pointerdown',e=>{e.preventDefault();startCmd(id)});
  el.addEventListener('pointerup',e=>{e.preventDefault();stopCmd()});
  el.addEventListener('pointerleave',e=>{if(activeCmd===id)stopCmd()});
});
['r','f'].forEach(id=>{document.getElementById(id)?.addEventListener('click',()=>sendCmd(id))});

document.addEventListener('keydown',e=>{
  const k=e.key.toLowerCase();
  if(['w','s','a','d','z','x','u','j','r','f'].includes(k)){e.preventDefault();startCmd(k);}
});
document.addEventListener('keyup',()=>stopCmd());

// ── Status poll ───────────────────────────────────────────────────────────────
setInterval(async()=>{
  try{
    const d=await(await fetch('/status')).json();
    const lh=d.lift||0;
    document.getElementById('lift_v').innerText=lh.toFixed(1);
    document.getElementById('lift_bar').style.height=Math.max(0,Math.min(100,lh/6)).toFixed(0)+'%';
    document.getElementById('spd_v').innerText=(d.speed||0.3).toFixed(2)+' m/s';
    document.getElementById('gp_txt').innerText=d.gamepad!=='none'?'🎮 '+d.gamepad:'No gamepad';
    if(d.connected){document.getElementById('dot').className='dot ok';document.getElementById('conn_txt').innerText='Connected ✓';}
    // Update arm vals from obs
    if(d.arms){['left','right'].forEach(side=>{
      JOINTS.forEach(j=>{
        const v=d.arms[side]?.[j];
        if(v!==undefined&&Math.abs((armVals[side][j]||0)-v)>0.3){
          armVals[side][j]=v;
          const el=document.getElementById(`jv_${side}_${j}`);
          if(el)el.innerText=v.toFixed(0)+'°';
        }
      });
    });}
    // Gamepad axes
    if(d.gamepad_axes){
      const cont=document.getElementById('gp_axes_preview');
      const html=Object.entries(d.gamepad_axes).map(([i,v])=>`
        <div class="gp-axis">
          <div class="gp-axis-label">Axis ${i}</div>
          <div class="gp-bar-wrap">
            <div class="gp-bar-center"></div>
            ${v>=0?`<div class="gp-bar-pos" style="width:${(v*50).toFixed(1)}%"></div>`
                  :`<div class="gp-bar-neg" style="width:${(-v*50).toFixed(1)}%"></div>`}
          </div>
          <div class="gp-val">${v.toFixed(3)}</div>
        </div>`).join('');
      cont.innerHTML=html;
    }
  }catch(e){}
},200);
</script>
</body>
</html>"""

SETTINGS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>AlohaMini — Controller Config</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
body{margin:0;background:#0d0d12;color:#c8d0e0;font-family:'Segoe UI',Arial,monospace;overflow-x:hidden}
.topbar{display:flex;align-items:center;gap:16px;padding:10px 16px;background:#111318;border-bottom:1px solid #1e2030}
a.back{color:#4a9eff;text-decoration:none;font-size:13px}
h2{color:#4a9eff;margin:0;font-size:16px;font-weight:600}
.layout{display:grid;grid-template-columns:1fr 360px;gap:12px;padding:12px}
@media(max-width:900px){.layout{grid-template-columns:1fr}}

/* Controller visual */
.gp-wrap{background:#111318;border:1px solid #1e2030;border-radius:12px;padding:16px;text-align:center}
.gp-title{font-size:11px;color:#4a6080;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px}
#gp-svg{width:100%;max-width:580px;height:auto}

/* Popup panel */
.config-panel{background:#111318;border:1px solid #1e2030;border-radius:12px;padding:16px;position:sticky;top:12px}
.cp-title{font-size:13px;color:#4a9eff;margin-bottom:12px;font-weight:600}
.cp-input-name{font-size:18px;font-weight:700;color:#fff;margin-bottom:4px}
.cp-live{font-size:12px;color:#4a6080;margin-bottom:16px}
.cp-row{margin-bottom:14px}
.cp-label{font-size:11px;color:#4a6080;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
select,input[type=text]{width:100%;background:#0a0d14;border:1px solid #253040;color:#c8d0e0;
  border-radius:6px;padding:7px 10px;font-size:13px;outline:none}
select:focus,input:focus{border-color:#4a9eff}
input[type=range]{width:100%;accent-color:#4a9eff;height:6px}
.range-row{display:flex;align-items:center;gap:8px}
.range-val{min-width:36px;text-align:right;font-size:12px;color:#4a9eff}
.toggle-row{display:flex;align-items:center;justify-content:space-between}
.toggle{position:relative;width:44px;height:24px;cursor:pointer}
.toggle input{opacity:0;width:0;height:0}
.toggle-slider{position:absolute;inset:0;background:#1e2030;border-radius:12px;transition:.2s}
.toggle-slider:before{content:'';position:absolute;width:18px;height:18px;left:3px;bottom:3px;
  background:#4a6080;border-radius:50%;transition:.2s}
.toggle input:checked+.toggle-slider{background:#0a3a6a}
.toggle input:checked+.toggle-slider:before{transform:translateX(20px);background:#4a9eff}

/* Axis preview canvas */
#axis-preview{display:block;margin:8px auto;background:#0a0d14;border:1px solid #1e2030;border-radius:8px}

/* Buttons row */
.btn-row{display:flex;gap:8px;margin-top:16px}
.btn{flex:1;padding:9px;border-radius:8px;border:1px solid #253040;background:#0a0d14;
     color:#c8d0e0;cursor:pointer;font-size:13px;transition:.15s}
.btn:hover{border-color:#4a9eff;color:#4a9eff}
.btn.primary{background:#0a2040;border-color:#4a9eff;color:#4a9eff}
.btn.primary:hover{background:#0d3060}
.btn.danger{background:#200a0a;border-color:#603030;color:#ff6060}
.btn.danger:hover{border-color:#ff6060}

/* Bottom table */
.btable{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
.btable th{color:#4a6080;font-weight:normal;text-align:left;padding:5px 8px;border-bottom:1px solid #1e2030}
.btable td{padding:5px 8px;border-bottom:1px solid #141820;vertical-align:middle}
.btable tr:hover td{background:#141820}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;border:1px solid #253040;color:#4a9eff;background:#0a1a2a}
.live-dot{width:8px;height:8px;border-radius:50%;background:#1e2030;display:inline-block;transition:.1s}
.live-dot.on{background:#4a9eff;box-shadow:0 0 6px #4a9eff}
kbd{background:#1a1e2a;padding:2px 7px;border:1px solid #2a3040;border-bottom:2px solid #3a4060;
    border-radius:4px;font-size:12px;color:#8090b0}
</style>
</head>
<body>

<div class="topbar">
  <a class="back" href="/">← Back</a>
  <h2>🎮 Controller Configuration</h2>
  <span id="gp_name" style="color:#4a6080;font-size:12px;margin-left:auto">No gamepad detected</span>
  <button class="btn primary" onclick="saveAll()" style="width:auto;padding:6px 16px">💾 Save</button>
  <button class="btn danger" onclick="resetAll()" style="width:auto;padding:6px 16px">↺ Reset</button>
</div>

<div class="layout">

  <!-- LEFT: Controller SVG + button table -->
  <div>
    <div class="gp-wrap">
      <div class="gp-title">Click any input to configure · Live inputs highlighted</div>
      <svg id="gp-svg" viewBox="0 0 640 310" xmlns="http://www.w3.org/2000/svg" style="max-height:320px">
        <defs>
          <linearGradient id="bodyGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#1e2535"/>
            <stop offset="100%" stop-color="#111620"/>
          </linearGradient>
          <linearGradient id="screenGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#0a1a2a"/>
            <stop offset="100%" stop-color="#060e16"/>
          </linearGradient>
        </defs>

        <!-- ── Body ─────────────────────────────────────────────────────── -->
        <rect x="20" y="20" width="600" height="270" rx="18" fill="url(#bodyGrad)" stroke="#2a3550" stroke-width="1.5"/>
        <!-- Top ridge -->
        <rect x="20" y="20" width="600" height="28" rx="18" fill="#181e2e" stroke="none"/>
        <rect x="20" y="36" width="600" height="12" fill="#181e2e" stroke="none"/>
        <!-- Bottom grip texture -->
        <rect x="20" y="250" width="600" height="40" rx="18" fill="#0e1220" stroke="none"/>

        <!-- ── SCREEN (top center) ──────────────────────────────────────── -->
        <rect x="248" y="30" width="144" height="72" rx="6" fill="url(#screenGrad)" stroke="#2a4060" stroke-width="1.5"/>
        <rect x="252" y="34" width="136" height="64" rx="4" fill="#040c14" stroke="none"/>
        <!-- Screen content hint -->
        <text x="320" y="62" text-anchor="middle" fill="#1e4060" font-size="9" font-family="monospace">RadioMaster</text>
        <text x="320" y="74" text-anchor="middle" fill="#1e4060" font-size="8" font-family="monospace">POCKET</text>
        <!-- Screen glare -->
        <rect x="252" y="34" width="60" height="10" rx="2" fill="rgba(255,255,255,0.03)"/>

        <!-- ── TOP SWITCHES ─────────────────────────────────────────────── -->
        <!-- SA (2-pos, top left) -->
        <g id="btn_6" data-btn="6" onclick="selectBtn(6)" style="cursor:pointer">
          <rect x="50" y="24" width="14" height="32" rx="5" fill="#0a0e16" stroke="#253040" stroke-width="1.5"/>
          <rect id="sw_SA" x="50" y="24" width="14" height="16" rx="5" fill="#1a2535" stroke="#2a4060" stroke-width="1"/>
          <text x="57" y="67" text-anchor="middle" fill="#4a6080" font-size="9">SA</text>
        </g>
        <!-- SB (3-pos, top left-center) -->
        <g id="btn_7" data-btn="7" onclick="selectBtn(7)" style="cursor:pointer">
          <rect x="80" y="24" width="14" height="44" rx="5" fill="#0a0e16" stroke="#253040" stroke-width="1.5"/>
          <rect id="sw_SB" x="80" y="24" width="14" height="16" rx="5" fill="#1a2535" stroke="#2a4060" stroke-width="1"/>
          <text x="87" y="79" text-anchor="middle" fill="#4a6080" font-size="9">SB</text>
        </g>
        <!-- SE (3-pos, top right-center) -->
        <g id="btn_8" data-btn="8" onclick="selectBtn(8)" style="cursor:pointer">
          <rect x="546" y="24" width="14" height="44" rx="5" fill="#0a0e16" stroke="#253040" stroke-width="1.5"/>
          <rect id="sw_SE" x="546" y="24" width="14" height="16" rx="5" fill="#1a2535" stroke="#2a4060" stroke-width="1"/>
          <text x="553" y="79" text-anchor="middle" fill="#4a6080" font-size="9">SE</text>
        </g>
        <!-- SF (2-pos, top right) -->
        <g id="btn_9" data-btn="9" onclick="selectBtn(9)" style="cursor:pointer">
          <rect x="576" y="24" width="14" height="32" rx="5" fill="#0a0e16" stroke="#253040" stroke-width="1.5"/>
          <rect id="sw_SF" x="576" y="24" width="14" height="16" rx="5" fill="#1a2535" stroke="#2a4060" stroke-width="1"/>
          <text x="583" y="67" text-anchor="middle" fill="#4a6080" font-size="9">SF</text>
        </g>

        <!-- SC / SD (middle area between gimbals) -->
        <g id="btn_10" data-btn="10" onclick="selectBtn(10)" style="cursor:pointer">
          <rect x="266" y="112" width="12" height="36" rx="4" fill="#0a0e16" stroke="#253040" stroke-width="1.5"/>
          <rect id="sw_SC" x="266" y="112" width="12" height="16" rx="4" fill="#1a2535" stroke="#2a4060" stroke-width="1"/>
          <text x="272" y="158" text-anchor="middle" fill="#4a6080" font-size="8">SC</text>
        </g>
        <g id="btn_11" data-btn="11" onclick="selectBtn(11)" style="cursor:pointer">
          <rect x="362" y="112" width="12" height="36" rx="4" fill="#0a0e16" stroke="#253040" stroke-width="1.5"/>
          <rect id="sw_SD" x="362" y="112" width="12" height="16" rx="4" fill="#1a2535" stroke="#2a4060" stroke-width="1"/>
          <text x="368" y="158" text-anchor="middle" fill="#4a6080" font-size="8">SD</text>
        </g>

        <!-- ── LEFT GIMBAL (Axis 0=X, 1=Y) ─────────────────────────────── -->
        <g id="stick_left" onclick="selectStick('left')" style="cursor:pointer">
          <!-- Outer ring -->
          <circle cx="148" cy="162" r="52" fill="#0a0e18" stroke="#1e2840" stroke-width="2"/>
          <!-- Rubber grip texture -->
          <circle cx="148" cy="162" r="48" fill="#0d1220" stroke="#253040" stroke-width="1"/>
          <!-- Inner circle (gimbal range indicator) -->
          <circle cx="148" cy="162" r="36" fill="#0a0d16" stroke="#1e2535" stroke-width="1" stroke-dasharray="4,4"/>
          <!-- Stick dot -->
          <circle id="stick_left_dot" cx="148" cy="162" r="20" fill="#161e2e" stroke="#2a4060" stroke-width="2"/>
          <!-- Stick top surface -->
          <circle id="stick_left_top" cx="148" cy="162" r="16" fill="#1a2438" stroke="#2a3a50" stroke-width="1"/>
          <circle cx="148" cy="162" r="6" fill="#0a1020" stroke="#1e2a3a" stroke-width="1"/>
          <!-- Cross hairs -->
          <line x1="148" y1="115" x2="148" y2="210" stroke="#0d1520" stroke-width="1"/>
          <line x1="101" y1="162" x2="195" y2="162" stroke="#0d1520" stroke-width="1"/>
          <!-- Label -->
          <text x="148" y="226" text-anchor="middle" fill="#253040" font-size="9">LEFT GIMBAL</text>
          <text id="lbl_stick_left" x="148" y="237" text-anchor="middle" fill="#4a9eff" font-size="8" opacity=".9"></text>
          <!-- Axis number badges -->
          <text x="110" y="168" fill="#1e3050" font-size="8">AX0</text>
          <text x="152" y="125" fill="#1e3050" font-size="8">AX1</text>
        </g>

        <!-- ── RIGHT GIMBAL (Axis 2=X, 3=Y) ─────────────────────────────── -->
        <g id="stick_right" onclick="selectStick('right')" style="cursor:pointer">
          <circle cx="492" cy="162" r="52" fill="#0a0e18" stroke="#1e2840" stroke-width="2"/>
          <circle cx="492" cy="162" r="48" fill="#0d1220" stroke="#253040" stroke-width="1"/>
          <circle cx="492" cy="162" r="36" fill="#0a0d16" stroke="#1e2535" stroke-width="1" stroke-dasharray="4,4"/>
          <circle id="stick_right_dot" cx="492" cy="162" r="20" fill="#161e2e" stroke="#2a4060" stroke-width="2"/>
          <circle id="stick_right_top" cx="492" cy="162" r="16" fill="#1a2438" stroke="#2a3a50" stroke-width="1"/>
          <circle cx="492" cy="162" r="6" fill="#0a1020" stroke="#1e2a3a" stroke-width="1"/>
          <line x1="492" y1="115" x2="492" y2="210" stroke="#0d1520" stroke-width="1"/>
          <line x1="445" y1="162" x2="539" y2="162" stroke="#0d1520" stroke-width="1"/>
          <text x="492" y="226" text-anchor="middle" fill="#253040" font-size="9">RIGHT GIMBAL</text>
          <text id="lbl_stick_right" x="492" y="237" text-anchor="middle" fill="#4a9eff" font-size="8" opacity=".9"></text>
          <text x="454" y="168" fill="#1e3050" font-size="8">AX2</text>
          <text x="496" y="125" fill="#1e3050" font-size="8">AX3</text>
        </g>

        <!-- ── TRIM BUTTONS (around gimbals) ─────────────────────────────── -->
        <!-- Left gimbal trims -->
        <g id="btn_12" data-btn="12" onclick="selectBtn(12)" style="cursor:pointer">
          <rect x="88" y="156" width="22" height="12" rx="3" fill="#0a0e16" stroke="#1e2535" stroke-width="1"/>
          <text x="99" y="165" text-anchor="middle" fill="#2a3a50" font-size="8">◄</text>
        </g>
        <g id="btn_13" data-btn="13" onclick="selectBtn(13)" style="cursor:pointer">
          <rect x="230" y="156" width="22" height="12" rx="3" fill="#0a0e16" stroke="#1e2535" stroke-width="1"/>
          <text x="241" y="165" text-anchor="middle" fill="#2a3a50" font-size="8">►</text>
        </g>
        <g id="btn_14" data-btn="14" onclick="selectBtn(14)" style="cursor:pointer">
          <rect x="142" y="100" width="12" height="22" rx="3" fill="#0a0e16" stroke="#1e2535" stroke-width="1"/>
          <text x="148" y="114" text-anchor="middle" fill="#2a3a50" font-size="8">▲</text>
        </g>
        <g id="btn_15" data-btn="15" onclick="selectBtn(15)" style="cursor:pointer">
          <rect x="142" y="210" width="12" height="22" rx="3" fill="#0a0e16" stroke="#1e2535" stroke-width="1"/>
          <text x="148" y="224" text-anchor="middle" fill="#2a3a50" font-size="8">▼</text>
        </g>

        <!-- ── NAVIGATION BUTTONS (bottom center) ────────────────────────── -->
        <!-- SYS -->
        <g id="btn_0" data-btn="0" onclick="selectBtn(0)" style="cursor:pointer">
          <rect x="248" y="255" width="40" height="22" rx="5" fill="#0a0e16" stroke="#1e2535" stroke-width="1.5"/>
          <text x="268" y="269" text-anchor="middle" fill="#4a6080" font-size="9">SYS</text>
        </g>
        <!-- TELE -->
        <g id="btn_1" data-btn="1" onclick="selectBtn(1)" style="cursor:pointer">
          <rect x="296" y="255" width="40" height="22" rx="5" fill="#0a0e16" stroke="#1e2535" stroke-width="1.5"/>
          <text x="316" y="269" text-anchor="middle" fill="#4a6080" font-size="9">TELE</text>
        </g>
        <!-- MDL -->
        <g id="btn_2" data-btn="2" onclick="selectBtn(2)" style="cursor:pointer">
          <rect x="344" y="255" width="40" height="22" rx="5" fill="#0a0e16" stroke="#1e2535" stroke-width="1.5"/>
          <text x="364" y="269" text-anchor="middle" fill="#4a6080" font-size="9">MDL</text>
        </g>
        <!-- RTN (right of center) -->
        <g id="btn_3" data-btn="3" onclick="selectBtn(3)" style="cursor:pointer">
          <rect x="392" y="255" width="40" height="22" rx="5" fill="#0a0e16" stroke="#253040" stroke-width="1.5"/>
          <text x="412" y="269" text-anchor="middle" fill="#4a9eff" font-size="9">RTN</text>
        </g>
        <!-- PAGE -->
        <g id="btn_4" data-btn="4" onclick="selectBtn(4)" style="cursor:pointer">
          <rect x="440" y="255" width="40" height="22" rx="5" fill="#0a0e16" stroke="#1e2535" stroke-width="1.5"/>
          <text x="460" y="269" text-anchor="middle" fill="#4a6080" font-size="9">PAGE</text>
        </g>
        <!-- PWR/MDL2 -->
        <g id="btn_5" data-btn="5" onclick="selectBtn(5)" style="cursor:pointer">
          <rect x="488" y="255" width="40" height="22" rx="5" fill="#0a0e16" stroke="#1e2535" stroke-width="1.5"/>
          <text x="508" y="269" text-anchor="middle" fill="#4a6080" font-size="9">PWR</text>
        </g>

        <!-- ── SCROLL WHEEL (between gimbals, top area) ───────────────────── -->
        <g id="axis_4" data-axis="4" onclick="selectAxis(4)" style="cursor:pointer">
          <ellipse cx="295" cy="100" rx="12" ry="20" fill="#0a0e16" stroke="#1e2535" stroke-width="1.5"/>
          <line x1="287" y1="88" x2="303" y2="88" stroke="#1e2535" stroke-width="2"/>
          <line x1="287" y1="93" x2="303" y2="93" stroke="#1e2535" stroke-width="2"/>
          <line x1="287" y1="98" x2="303" y2="98" stroke="#1e2535" stroke-width="2"/>
          <line x1="287" y1="103" x2="303" y2="103" stroke="#1e2535" stroke-width="2"/>
          <line x1="287" y1="108" x2="303" y2="108" stroke="#1e2535" stroke-width="2"/>
          <text x="295" y="132" text-anchor="middle" fill="#2a3a50" font-size="8">WHEEL L</text>
          <text id="lbl_axis_4" x="295" y="141" text-anchor="middle" fill="#4a9eff" font-size="8"></text>
        </g>
        <g id="axis_5" data-axis="5" onclick="selectAxis(5)" style="cursor:pointer">
          <ellipse cx="345" cy="100" rx="12" ry="20" fill="#0a0e16" stroke="#1e2535" stroke-width="1.5"/>
          <line x1="337" y1="88" x2="353" y2="88" stroke="#1e2535" stroke-width="2"/>
          <line x1="337" y1="93" x2="353" y2="93" stroke="#1e2535" stroke-width="2"/>
          <line x1="337" y1="98" x2="353" y2="98" stroke="#1e2535" stroke-width="2"/>
          <line x1="337" y1="103" x2="353" y2="103" stroke="#1e2535" stroke-width="2"/>
          <line x1="337" y1="108" x2="353" y2="108" stroke="#1e2535" stroke-width="2"/>
          <text x="345" y="132" text-anchor="middle" fill="#2a3a50" font-size="8">WHEEL R</text>
          <text id="lbl_axis_5" x="345" y="141" text-anchor="middle" fill="#4a9eff" font-size="8"></text>
        </g>

        <!-- USB-C port indicator -->
        <rect x="310" y="276" width="20" height="8" rx="3" fill="#0a0e16" stroke="#1e2535" stroke-width="1"/>
        <text x="320" y="295" text-anchor="middle" fill="#1a2535" font-size="8">USB-C</text>

        <!-- ── Active input highlight ring (JS-driven) ───────────────────── -->
        <circle id="active_ring" cx="0" cy="0" r="0" fill="none" stroke="#4a9eff" stroke-width="2" opacity=".6" style="pointer-events:none"/>
      </svg>

      <!-- Additional axes (6+) as horizontal bars -->
      <div id="extra_axes" style="padding:0 8px"></div>
    </div>

    <!-- Button table -->
    <div class="gp-wrap" style="margin-top:10px">
      <div class="gp-title">All Buttons</div>
      <table class="btable">
        <thead><tr><th>Button</th><th>Live</th><th>Binding</th><th>Label</th></tr></thead>
        <tbody id="btn_table_all"></tbody>
      </table>
    </div>

    <!-- Keyboard -->
    <div class="gp-wrap" style="margin-top:10px">
      <div class="gp-title">Keyboard Map</div>
      <table class="btable">
        <thead><tr><th>Key</th><th>Action</th></tr></thead>
        <tbody id="key_table"></tbody>
      </table>
    </div>
  </div>

  <!-- RIGHT: Config panel -->
  <div>
    <div class="config-panel">
      <div class="cp-title" id="cp-title">Select an input</div>
      <div id="cp-content" style="color:#4a6080;font-size:13px">
        Click any button, stick, or trigger on the controller diagram to configure it.
      </div>
    </div>
  </div>

</div>

<script>
const AXIS_ACTIONS=[
  {v:'none',l:'— None —'},
  {v:'x_vel',l:'Forward / Back'},
  {v:'y_vel',l:'Strafe Left / Right'},
  {v:'theta_vel',l:'Rotate Left / Right'},
  {v:'lift',l:'Lift Up / Down'},
  {v:'arm_left',l:'Arm Left (selected joint)'},
  {v:'arm_right',l:'Arm Right (selected joint)'},
];
const BTN_ACTIONS=[
  {v:'none',l:'— None —'},
  {v:'joint_next',l:'Next Joint'},
  {v:'joint_prev',l:'Prev Joint'},
  {v:'speed_up',l:'Speed Up'},
  {v:'speed_down',l:'Speed Down'},
];

let bindings={};
let liveAxes={},liveButtons={};
let selected={type:null,id:null};

async function load(){
  bindings=await(await fetch('/bindings')).json();
  renderTables();
  updateLabels();
}

// ── Render bottom tables ───────────────────────────────────────────────────────
function renderTables(){
  // Buttons
  const bt=document.getElementById('btn_table_all');
  bt.innerHTML=Object.entries(bindings.buttons||{}).map(([i,c])=>`
    <tr onclick="selectBtn(${i})" style="cursor:pointer" id="brow_${i}">
      <td>${c.label||'Btn '+i}</td>
      <td><span class="live-dot" id="ldot_${i}"></span></td>
      <td><span class="badge" id="bbadge_${i}">${c.action||'none'}</span></td>
      <td><input id="blabel_${i}" value="${c.label||''}" style="width:80px;background:#0a0d14;border:1px solid #1e2030;color:#8090b0;border-radius:4px;padding:2px 6px;font-size:11px" onclick="event.stopPropagation()"></td>
    </tr>`).join('');

  // Keys
  const kt=document.getElementById('key_table');
  kt.innerHTML=Object.entries(bindings.key_map||{}).map(([k,a])=>`
    <tr>
      <td><kbd>${k}</kbd></td>
      <td><input value="${a}" id="km_${k}" style="width:160px;background:#0a0d14;border:1px solid #1e2030;color:#c8d0e0;border-radius:4px;padding:3px 8px;font-size:12px"></td>
    </tr>`).join('');
}

function updateLabels(){
  // Left stick label
  const la0=bindings.axes?.['0']?.action||'';
  const la1=bindings.axes?.['1']?.action||'';
  document.getElementById('lbl_stick_left').textContent=la0&&la1?la0+'/'+la1:la0||la1;
  const la2=bindings.axes?.['2']?.action||'';
  const la3=bindings.axes?.['3']?.action||'';
  document.getElementById('lbl_stick_right').textContent=la2&&la3?la2+'/'+la3:la2||la3;
  document.getElementById('lbl_axis_4').textContent=bindings.axes?.['4']?.action||'';
  document.getElementById('lbl_axis_5').textContent=bindings.axes?.['5']?.action||'';
}

// ── Config panel ───────────────────────────────────────────────────────────────
function actionSelect(options,curVal,id){
  return `<select id="${id}">${options.map(o=>`<option value="${o.v}"${o.v===curVal?' selected':''}>${o.l}</option>`).join('')}</select>`;
}

function showAxisPanel(axisId){
  const c=bindings.axes?.[String(axisId)]||{action:'none',scale:1,deadzone:0.1,invert:false,label:'Axis '+axisId};
  selected={type:'axis',id:String(axisId)};
  document.getElementById('cp-title').textContent='Axis '+axisId+' — '+(c.label||'');
  document.getElementById('cp-content').innerHTML=`
    <div class="cp-row">
      <div class="cp-label">Action</div>
      ${actionSelect(AXIS_ACTIONS,c.action,'cp_action')}
    </div>
    <div class="cp-row">
      <div class="cp-label">Label / Name</div>
      <input type="text" id="cp_label" value="${c.label||'Axis '+axisId}">
    </div>
    <div class="cp-row">
      <div class="cp-label">Scale <span class="range-val" id="cp_scale_v">${(c.scale||1).toFixed(2)}</span></div>
      <div class="range-row">
        <input type="range" min="0.05" max="3" step="0.05" value="${c.scale||1}" id="cp_scale"
          oninput="document.getElementById('cp_scale_v').textContent=parseFloat(this.value).toFixed(2)">
      </div>
    </div>
    <div class="cp-row">
      <div class="cp-label">Dead Zone <span class="range-val" id="cp_dz_v">${(c.deadzone||0).toFixed(2)}</span></div>
      <div class="range-row">
        <input type="range" min="0" max="0.6" step="0.01" value="${c.deadzone||0}" id="cp_dz"
          oninput="document.getElementById('cp_dz_v').textContent=parseFloat(this.value).toFixed(2)">
      </div>
    </div>
    <div class="cp-row">
      <div class="toggle-row">
        <span class="cp-label" style="margin:0">Invert</span>
        <label class="toggle"><input type="checkbox" id="cp_invert" ${c.invert?'checked':''}><span class="toggle-slider"></span></label>
      </div>
    </div>
    <canvas id="axis-preview" width="320" height="80"></canvas>
    <div class="cp-row" style="margin-top:8px">
      <div class="cp-label">Live Value</div>
      <div style="font-size:24px;font-weight:700;color:#4a9eff;text-align:center" id="cp_live_val">0.000</div>
    </div>
  `;
}

function showBtnPanel(btnId){
  const c=bindings.buttons?.[String(btnId)]||{action:'none',label:'Btn '+btnId};
  selected={type:'button',id:String(btnId)};
  document.getElementById('cp-title').textContent='Button '+btnId+' — '+(c.label||'');
  document.getElementById('cp-content').innerHTML=`
    <div class="cp-row">
      <div class="cp-label">Action</div>
      ${actionSelect(BTN_ACTIONS,c.action,'cp_action')}
    </div>
    <div class="cp-row">
      <div class="cp-label">Label / Name</div>
      <input type="text" id="cp_label" value="${c.label||'Btn '+btnId}">
    </div>
    <div style="margin-top:24px;text-align:center">
      <div class="live-dot" id="cp_btn_dot" style="width:48px;height:48px;margin:0 auto;border-radius:50%"></div>
      <div style="margin-top:8px;font-size:12px;color:#4a6080">Press button to test</div>
    </div>
  `;
}

function selectAxis(id){highlightEl('axis_'+id,'#0a3060');showAxisPanel(id);}
function selectBtn(id){highlightEl('btn_'+id,'#0a3060');showBtnPanel(id);}
function selectStick(side){
  const axes=side==='left'?[0,1]:[2,3];
  highlightEl('stick_'+side,'#0a3060');
  showAxisPanel(axes[0]); // show first axis, user can switch
}
function selectDpad(){highlightEl('dpad','#0a3060');}

function highlightEl(id,col){
  document.querySelectorAll('.gp-selected').forEach(e=>{
    e.style.filter='';e.classList.remove('gp-selected');
  });
  const el=document.getElementById(id);
  if(el){el.style.filter='drop-shadow(0 0 8px #4a9eff)';el.classList.add('gp-selected');}
}

// ── Collect & save ─────────────────────────────────────────────────────────────
function collectCurrent(){
  if(!selected.id)return;
  if(selected.type==='axis'){
    const i=selected.id;
    if(!bindings.axes[i])bindings.axes[i]={};
    const b=bindings.axes[i];
    const act=document.getElementById('cp_action');if(act)b.action=act.value;
    const lbl=document.getElementById('cp_label');if(lbl)b.label=lbl.value;
    const sc=document.getElementById('cp_scale');if(sc)b.scale=parseFloat(sc.value);
    const dz=document.getElementById('cp_dz');if(dz)b.deadzone=parseFloat(dz.value);
    const inv=document.getElementById('cp_invert');if(inv)b.invert=inv.checked;
  } else if(selected.type==='button'){
    const i=selected.id;
    if(!bindings.buttons[i])bindings.buttons[i]={};
    const b=bindings.buttons[i];
    const act=document.getElementById('cp_action');if(act)b.action=act.value;
    const lbl=document.getElementById('cp_label');if(lbl)b.label=lbl.value;
  }
}

async function saveAll(){
  collectCurrent();
  // Collect key map
  for(const k of Object.keys(bindings.key_map||{})){
    const el=document.getElementById('km_'+k);if(el)bindings.key_map[k]=el.value;
  }
  // Collect button labels from table
  for(const [i] of Object.entries(bindings.buttons||{})){
    const el=document.getElementById('blabel_'+i);if(el)bindings.buttons[i].label=el.value;
  }
  await fetch('/bindings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(bindings)});
  updateLabels();renderTables();
  document.querySelector('.btn.primary').textContent='✓ Saved';
  setTimeout(()=>document.querySelector('.btn.primary').textContent='💾 Save',1500);
}

async function resetAll(){
  if(!confirm('Reset all bindings to defaults?'))return;
  bindings=await(await fetch('/bindings/reset',{method:'POST'})).json();
  renderTables();updateLabels();selected={type:null,id:null};
  document.getElementById('cp-title').textContent='Select an input';
  document.getElementById('cp-content').innerHTML='<span style="color:#4a6080">Click any input on the controller.</span>';
}

// ── Axis preview canvas ────────────────────────────────────────────────────────
function drawAxisPreview(rawVal,deadzone,invert,scale){
  const c=document.getElementById('axis-preview');if(!c)return;
  const ctx=c.getContext('2d');const W=c.width,H=c.height;
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle='#0a0d14';ctx.fillRect(0,0,W,H);
  // center line
  ctx.strokeStyle='#1e2030';ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(W/2,0);ctx.lineTo(W/2,H);ctx.stroke();
  // deadzone region
  ctx.fillStyle='rgba(255,60,60,0.1)';
  ctx.fillRect(W/2-deadzone*W/2,0,deadzone*W,H);
  // processed value
  let v=rawVal;
  if(Math.abs(v)<deadzone)v=0;else v=(v-Math.sign(v)*deadzone)/(1-deadzone);
  if(invert)v=-v;v*=scale;v=Math.max(-1,Math.min(1,v));
  ctx.fillStyle='#4a9eff';
  const bw=Math.abs(v)*W/2;
  ctx.fillRect(v>=0?W/2:W/2-bw,8,bw,H-16);
  // raw bar (dim)
  ctx.fillStyle='rgba(74,144,255,0.2)';
  const rw=Math.abs(rawVal)*W/2;
  ctx.fillRect(rawVal>=0?W/2:W/2-rw,2,rw,4);
  // labels
  ctx.fillStyle='#4a6080';ctx.font='10px monospace';
  ctx.fillText('raw',4,H-4);ctx.fillText('processed',W/2+4,H-4);
  ctx.fillStyle='#4a9eff';ctx.font='bold 14px monospace';
  ctx.textAlign='center';ctx.fillText(v.toFixed(3),W/2,H/2+5);ctx.textAlign='left';
}

// ── Live update ───────────────────────────────────────────────────────────────
setInterval(async()=>{
  try{
    const d=await(await fetch('/status')).json();
    liveAxes=d.gamepad_axes||{};liveButtons=d.gamepad_buttons||{};
    const gpEl=document.getElementById('gp_name');
    const gpNew=d.gamepad!=='none'?'🎮 '+d.gamepad:'⚠ No gamepad — connect and it will appear automatically';
    if(gpEl.textContent!==gpNew){gpEl.textContent=gpNew;gpEl.style.color=d.gamepad!=='none'?'#4a9eff':'#fa0';}

    // Animate gimbals (RadioMaster Pocket cx=148/cy=162, cx=492/cy=162)
    const ax0=parseFloat(liveAxes['0']||0),ax1=parseFloat(liveAxes['1']||0);
    const ax2=parseFloat(liveAxes['2']||0),ax3=parseFloat(liveAxes['3']||0);
    const ldot=document.getElementById('stick_left_dot');
    const ltop=document.getElementById('stick_left_top');
    const rdot=document.getElementById('stick_right_dot');
    const rtop=document.getElementById('stick_right_top');
    if(ldot){ldot.setAttribute('cx',148+ax0*28);ldot.setAttribute('cy',162+ax1*28);}
    if(ltop){ltop.setAttribute('cx',148+ax0*28);ltop.setAttribute('cy',162+ax1*28);}
    if(rdot){rdot.setAttribute('cx',492+ax2*28);rdot.setAttribute('cy',162+ax3*28);}
    if(rtop){rtop.setAttribute('cx',492+ax2*28);rtop.setAttribute('cy',162+ax3*28);}

    // Scroll wheels (axis 4/5) — tilt the ellipse lines
    const a4=parseFloat(liveAxes['4']||0);
    const a5=parseFloat(liveAxes['5']||0);
    // highlight wheels when active
    const w4=document.getElementById('axis_4');if(w4&&!w4.classList.contains('gp-selected'))
      w4.style.filter=Math.abs(a4)>0.05?'drop-shadow(0 0 4px rgba(74,144,255,.8))':'';
    const w5=document.getElementById('axis_5');if(w5&&!w5.classList.contains('gp-selected'))
      w5.style.filter=Math.abs(a5)>0.05?'drop-shadow(0 0 4px rgba(74,144,255,.8))':'';

    // Animate switches when active
    for(let b=6;b<=11;b++){
      const sw=document.getElementById('sw_S'+['A','B','C','D','E','F'][b-6]);
      if(sw){const v=liveButtons[String(b)]||false;
        sw.style.fill=v?'#2a4060':'#1a2535';
      }
    }

    // Highlight active inputs on SVG
    for(const [i,v] of Object.entries(liveAxes)){
      const el=document.getElementById('axis_'+i);
      if(el&&!el.classList.contains('gp-selected'))
        el.style.filter=Math.abs(v)>0.1?'drop-shadow(0 0 4px rgba(74,144,255,0.6))':'';
    }
    for(const [i,v] of Object.entries(liveButtons)){
      const el=document.getElementById('btn_'+i);
      if(el&&!el.classList.contains('gp-selected'))
        el.style.filter=v?'drop-shadow(0 0 6px #4a9eff)':'';
      const dot=document.getElementById('ldot_'+i);
      if(dot)dot.className='live-dot'+(v?' on':'');
    }

    // Extra axes (6+)
    const extra=Object.entries(liveAxes).filter(([i])=>parseInt(i)>=6);
    if(extra.length){
      document.getElementById('extra_axes').innerHTML=extra.map(([i,v])=>`
        <div style="display:flex;align-items:center;gap:8px;margin:3px 0;font-size:11px">
          <span style="min-width:50px;color:#4a6080">Axis ${i}</span>
          <div style="flex:1;height:10px;background:#0a0d14;border-radius:5px;overflow:hidden;position:relative">
            <div style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:#1e2030;transform:translateX(-50%)"></div>
            ${v>=0?`<div style="position:absolute;left:50%;top:0;bottom:0;width:${(v*50).toFixed(1)}%;background:#4a9eff;border-radius:0 5px 5px 0"></div>`
                  :`<div style="position:absolute;right:50%;top:0;bottom:0;width:${(-v*50).toFixed(1)}%;background:#ff6060;border-radius:5px 0 0 5px"></div>`}
          </div>
          <span style="min-width:50px;text-align:right;color:#4a9eff">${v.toFixed(3)}</span>
          <button onclick="selectAxis(${i})" style="padding:2px 8px;background:#0a1a2a;border:1px solid #253040;border-radius:4px;color:#4a9eff;cursor:pointer;font-size:10px">Config</button>
        </div>`).join('');
    }

    // Config panel live update
    if(selected.type==='axis'){
      const rawVal=parseFloat(liveAxes[selected.id]||0);
      const c=bindings.axes?.[selected.id]||{};
      const dz=parseFloat(document.getElementById('cp_dz')?.value||c.deadzone||0);
      const sc=parseFloat(document.getElementById('cp_scale')?.value||c.scale||1);
      const inv=document.getElementById('cp_invert')?.checked||c.invert||false;
      const lv=document.getElementById('cp_live_val');if(lv)lv.textContent=rawVal.toFixed(3);
      drawAxisPreview(rawVal,dz,inv,sc);
    } else if(selected.type==='button'){
      const v=liveButtons[selected.id]||false;
      const dot=document.getElementById('cp_btn_dot');
      if(dot){dot.style.background=v?'#4a9eff':' #1e2030';dot.style.boxShadow=v?'0 0 20px #4a9eff':'';}
    }
  }catch(e){}
},80);

load();
</script>
</body>
</html>"""

if __name__ == '__main__':
    print(f"Open: http://localhost:{WEB_PORT}")
    print(f"Settings: http://localhost:{WEB_PORT}/settings")
    app.run(host='0.0.0.0', port=WEB_PORT, threaded=True)
