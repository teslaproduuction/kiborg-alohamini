"""
AlohaMini Controller
- Flask web UI: base/lift buttons + arm joint sliders
- RadioMaster Pocket (or any gamepad) support via pygame
- ZMQ commands to Pi host
"""

import json, threading, time, math
import zmq
import pygame
from flask import Flask, request, jsonify, render_template_string

REMOTE_IP = "192.168.31.170"
CMD_PORT   = 5555
OBS_PORT   = 5556
WEB_PORT   = 8080

# ── ZMQ ───────────────────────────────────────────────────────────────────────
ctx = zmq.Context()
cmd_sock = ctx.socket(zmq.PUSH)
cmd_sock.connect(f"tcp://{REMOTE_IP}:{CMD_PORT}")
obs_sock = ctx.socket(zmq.PULL)
obs_sock.connect(f"tcp://{REMOTE_IP}:{OBS_PORT}")
obs_sock.setsockopt(zmq.RCVTIMEO, 50)

# ── Shared state ───────────────────────────────────────────────────────────────
ARM_JOINTS = ["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"]
state = {
    "lift_height": 0.0,
    "base_speed":  0.3,
    "rot_speed":   60.0,
    "base_active": {"x":0.0,"y":0.0,"theta":0.0},
    "arm_left":    {j: 0.0 for j in ARM_JOINTS},
    "arm_right":   {j: 0.0 for j in ARM_JOINTS},
    "gamepad":     "none",
}
lock = threading.Lock()

def build_action():
    with lock:
        lh   = state["lift_height"]
        ba   = state["base_active"]
        left = dict(state["arm_left"])
        right= dict(state["arm_right"])
    action = {
        "x.vel": ba["x"], "y.vel": ba["y"], "theta.vel": ba["theta"],
        "lift_axis.height_mm": lh,
    }
    for j in ARM_JOINTS:
        action[f"arm_left_{j}.pos"]  = left[j]
        action[f"arm_right_{j}.pos"] = right[j]
    return action

# ── Observation thread ─────────────────────────────────────────────────────────
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
            initialized.set()  # first observation received — safe to start sending
        except zmq.Again:
            pass
        except Exception:
            time.sleep(0.05)

threading.Thread(target=obs_loop, daemon=True).start()

# ── Send loop ──────────────────────────────────────────────────────────────────
initialized = threading.Event()

def send_loop():
    # Wait for first observation to get current arm positions
    print("[Controller] Waiting for initial observation from robot...")
    initialized.wait(timeout=5.0)
    print("[Controller] Sending commands.")
    while True:
        cmd_sock.send_string(json.dumps(build_action()))
        time.sleep(1/30)

threading.Thread(target=send_loop, daemon=True).start()

# ── Gamepad (pygame) ───────────────────────────────────────────────────────────
# RadioMaster Pocket typical axis mapping:
#   Axis 0: Left stick X  → strafe (y.vel)
#   Axis 1: Left stick Y  → forward (x.vel, inverted)
#   Axis 2: Right stick X → rotate (theta.vel)
#   Axis 3: Right stick Y → lift (inverted)
#   Axis 4: Left dial/pot → left arm joint delta
#   Axis 5: Right dial/pot→ right arm joint delta
# Selected joint cycled with buttons 0/1

DEADZONE = 0.08
selected_joint = [0]  # index into ARM_JOINTS

def apply_deadzone(v):
    return v if abs(v) > DEADZONE else 0.0

def gamepad_loop():
    pygame.init()
    pygame.joystick.init()
    last_btn = [False]*16

    while True:
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        if count == 0:
            with lock: state["gamepad"] = "none"
            time.sleep(1)
            continue

        joy = pygame.joystick.Joystick(0)
        joy.init()
        name = joy.get_name()
        with lock: state["gamepad"] = name
        print(f"[Gamepad] {name}")

        try:
            while True:
                pygame.event.pump()

                def axis(i):
                    return apply_deadzone(joy.get_axis(i)) if joy.get_numaxes() > i else 0.0

                x_vel     =  axis(1) * -state["base_speed"]   # L stick Y (fwd)
                y_vel     =  axis(0) *  state["base_speed"]    # L stick X (strafe)
                theta_vel =  axis(2) * -state["rot_speed"]     # R stick X (rotate)
                lift_raw  =  axis(3)                           # R stick Y

                with lock:
                    state["base_active"] = {"x": x_vel, "y": y_vel, "theta": theta_vel}
                    if abs(lift_raw) > DEADZONE:
                        state["lift_height"] = max(0, state["lift_height"] - lift_raw * 3.0)

                # Button 0 = prev joint, Button 1 = next joint
                for bi, (prev, curr) in enumerate(zip(last_btn, [joy.get_button(i) if joy.get_numbuttons()>i else 0 for i in range(min(joy.get_numbuttons(),16))])):
                    if curr and not prev:
                        if bi == 0:
                            selected_joint[0] = (selected_joint[0] - 1) % len(ARM_JOINTS)
                            print(f"[Joint] selected: {ARM_JOINTS[selected_joint[0]]}")
                        elif bi == 1:
                            selected_joint[0] = (selected_joint[0] + 1) % len(ARM_JOINTS)
                            print(f"[Joint] selected: {ARM_JOINTS[selected_joint[0]]}")
                last_btn = [joy.get_button(i) if joy.get_numbuttons()>i else 0 for i in range(min(joy.get_numbuttons(),16))]

                # Axis 4/5: left/right arm joint control
                la = apply_deadzone(axis(4))
                ra = apply_deadzone(axis(5))
                if la or ra:
                    j = ARM_JOINTS[selected_joint[0]]
                    with lock:
                        state["arm_left"][j]  = max(-100, min(100, state["arm_left"][j]  + la * 2))
                        state["arm_right"][j] = max(-100, min(100, state["arm_right"][j] + ra * 2))

                time.sleep(1/60)
        except Exception as e:
            print(f"[Gamepad] error: {e}")
            time.sleep(1)

threading.Thread(target=gamepad_loop, daemon=True).start()

# ── Flask web UI ───────────────────────────────────────────────────────────────
app = Flask(__name__)

HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"><title>AlohaMini</title>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:monospace;background:#0d0d0d;color:#ddd;margin:0;padding:6px;overflow-x:hidden}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:4px 8px;
        background:#111;border-radius:8px;margin-bottom:6px;font-size:12px}
.status-dot{width:10px;height:10px;border-radius:50%;background:#f00;display:inline-block;margin-right:6px}
.status-dot.ok{background:#0f0}
.panel{background:#161616;border:1px solid #2a2a2a;border-radius:10px;padding:10px;margin-bottom:8px}
.panel-title{font-size:11px;color:#666;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}

/* Base dpad */
.dpad{display:grid;grid-template-columns:repeat(3,64px);grid-template-rows:repeat(3,64px);gap:4px;margin:0 auto;width:max-content}
.dpad-btn{background:#1e1e1e;border:1px solid #333;border-radius:8px;color:#ccc;
          font-size:20px;cursor:pointer;touch-action:none;display:flex;align-items:center;justify-content:center}
.dpad-btn:active,.dpad-btn.on{background:#0af;color:#000;border-color:#0af}
.stop-btn{background:#2a0000;border-color:#500;border-radius:8px;display:flex;
          align-items:center;justify-content:center;font-size:18px;cursor:pointer;touch-action:none}
.stop-btn:active,.stop-btn.on{background:#f00;color:#fff}

/* Lift bar */
.lift-bar{display:flex;align-items:center;gap:8px}
.lift-track{flex:1;height:24px;background:#1a1a1a;border-radius:12px;border:1px solid #333;overflow:hidden}
.lift-fill{height:100%;background:linear-gradient(90deg,#0af,#06f);border-radius:12px;transition:width 0.2s;min-width:4px}
.lift-btns{display:flex;flex-direction:column;gap:4px}
.lift-btn{width:48px;height:28px;background:#1e1e1e;border:1px solid #333;border-radius:6px;
          color:#ccc;cursor:pointer;touch-action:none;font-size:16px}
.lift-btn:active,.lift-btn.on{background:#0af;color:#000}

/* Arm SVG */
.arm-container{display:flex;gap:8px;align-items:flex-start}
.arm-svg-wrap{flex:0 0 140px;text-align:center}
.arm-svg-wrap svg{width:130px;height:280px}
.arm-controls{flex:1}
.joint-row{display:flex;align-items:center;gap:6px;margin:5px 0;cursor:pointer;padding:4px;border-radius:6px}
.joint-row:hover{background:#1e1e1e}
.joint-row.selected{background:#0a2a3a;border:1px solid #0af}
.joint-dot{width:12px;height:12px;border-radius:50%;background:#444;flex-shrink:0}
.joint-name{font-size:11px;color:#aaa;min-width:88px}
.joint-val{font-size:11px;color:#0af;min-width:36px;text-align:right}
.joint-btns{display:flex;gap:3px;margin-left:auto}
.jbtn{width:28px;height:28px;background:#222;border:1px solid #444;border-radius:5px;
      color:#ccc;cursor:pointer;font-size:14px;touch-action:none}
.jbtn:active,.jbtn.on{background:#0af;color:#000}
.arm-tabs{display:flex;gap:4px;margin-bottom:8px}
.arm-tab{flex:1;padding:7px;background:#1a1a1a;border:1px solid #333;border-radius:7px;
         cursor:pointer;text-align:center;font-size:12px;color:#aaa}
.arm-tab.active{background:#0af;color:#000;border-color:#0af}
.arm-panel{display:none}.arm-panel.active{display:block}

/* Speed */
.speed-row{display:flex;align-items:center;gap:8px}
.spd-btn{width:44px;height:32px;background:#1e1e1e;border:1px solid #333;border-radius:7px;
         color:#ccc;cursor:pointer;font-size:16px;touch-action:none}
.spd-btn:active{background:#0af;color:#000}

/* Joint colors */
.jc0{background:#f55} .jc1{background:#fa5} .jc2{background:#ff5}
.jc3{background:#5f5} .jc4{background:#5af} .jc5{background:#a5f}
</style>
</head>
<body>

<div class="topbar">
  <span><span class="status-dot" id="dot"></span><span id="status_txt">Connecting…</span></span>
  <span id="gamepad_txt" style="color:#fa0;font-size:11px">No gamepad</span>
  <span style="color:#666;font-size:11px">🤖 AlohaMini</span>
</div>

<!-- BASE -->
<div class="panel">
  <div class="panel-title">Base &nbsp; <span style="color:#0af" id="spd_val">0.30 m/s</span>
    <button class="spd-btn" id="r" style="margin-left:8px">+</button>
    <button class="spd-btn" id="f">−</button>
  </div>
  <div style="display:flex;gap:12px;align-items:center">
    <div class="dpad">
      <div></div>
      <div class="dpad-btn" id="w">▲</div>
      <div></div>
      <div class="dpad-btn" id="z">◄</div>
      <div class="stop-btn" id="stop">■</div>
      <div class="dpad-btn" id="x">►</div>
      <div class="dpad-btn" id="a">↺</div>
      <div class="dpad-btn" id="s">▼</div>
      <div class="dpad-btn" id="d">↻</div>
    </div>
    <div style="flex:1">
      <div class="panel-title">Lift &nbsp; <span id="lift_h">0.0</span> mm</div>
      <div class="lift-bar" style="margin-bottom:6px">
        <div class="lift-track"><div class="lift-fill" id="lift_fill" style="width:0%"></div></div>
      </div>
      <div style="display:flex;gap:6px">
        <button class="lift-btn" id="u" style="flex:1">▲</button>
        <button class="lift-btn" id="j" style="flex:1">▼</button>
      </div>
    </div>
  </div>
</div>

<!-- ARMS -->
<div class="panel">
  <div class="panel-title">Arms</div>
  <div class="arm-tabs">
    <div class="arm-tab active" onclick="showArm('left',this)">◄ LEFT</div>
    <div class="arm-tab" onclick="showArm('right',this)">RIGHT ►</div>
  </div>
  <div class="arm-panel active" id="panel_left"></div>
  <div class="arm-panel" id="panel_right"></div>
</div>

<script>
const JOINTS=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper'];
const JOINT_LABELS=['Shoulder Pan','Shoulder Lift','Elbow Flex','Wrist Flex','Wrist Roll','Gripper'];
const armVals={left:{},right:{}};
JOINTS.forEach(j=>{armVals.left[j]=0;armVals.right[j]=0});
let selectedJoint={left:0,right:0};

// SVG arm diagram angles (approximate visual, not real kinematics)
function drawArm(side){
  const vals=armVals[side];
  const svg=document.getElementById('svg_'+side);
  if(!svg)return;
  const pan=vals['shoulder_pan']||0;
  const lift=vals['shoulder_lift']||0;
  const elbow=vals['elbow_flex']||0;
  const wf=vals['wrist_flex']||0;
  // Simple 2D stick figure, top-down base rotation + side view joints
  const cx=65,baseY=260;
  const a0=pan*0.6*(Math.PI/180);
  const a1=(90+lift*0.6)*(Math.PI/180);
  const a2=(elbow*0.5)*(Math.PI/180);
  const a3=(wf*0.4)*(Math.PI/180);
  const L=[60,50,35,22];
  let x=cx,y=baseY,ang=Math.PI*1.5;
  const pts=[[x,y]];
  [a1,a2+a1,a2+a1+a3].forEach((a,i)=>{
    x+=Math.cos(a)*L[i];y+=Math.sin(a)*L[i];pts.push([x,y]);
  });
  const colors=['#f55','#fa5','#ff5','#5f5','#5af','#a5f'];
  let path=`M${pts[0][0]},${pts[0][1]}`;
  for(let i=1;i<pts.length;i++)path+=` L${pts[i][0]},${pts[i][1]}`;
  svg.innerHTML=`
    <circle cx="${cx}" cy="${baseY}" r="10" fill="#333" stroke="#555" stroke-width="2"/>
    <path d="${path}" stroke="#0af" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    ${pts.slice(1,-1).map((p,i)=>`<circle cx="${p[0]}" cy="${p[1]}" r="6" fill="${colors[i+1]}" stroke="#000" stroke-width="1.5"/>`).join('')}
    <circle cx="${pts[pts.length-1][0]}" cy="${pts[pts.length-1][1]}" r="5" fill="#a5f" stroke="#000" stroke-width="1.5"/>
    <text x="4" y="14" font-size="10" fill="#555">${side.toUpperCase()}</text>
  `;
}

function buildArmPanel(side){
  const p=document.getElementById('panel_'+side);
  p.innerHTML=`<div class="arm-container">
    <div class="arm-svg-wrap"><svg id="svg_${side}"></svg></div>
    <div class="arm-controls" id="ctrl_${side}"></div>
  </div>`;
  const ctrl=document.getElementById('ctrl_'+side);
  JOINTS.forEach((j,i)=>{
    const row=document.createElement('div');
    row.className='joint-row'+(i===0?' selected':'');
    row.id=`row_${side}_${j}`;
    row.onclick=()=>selectJoint(side,i);
    row.innerHTML=`<div class="joint-dot jc${i}"></div>
      <span class="joint-name">${JOINT_LABELS[i]}</span>
      <span class="joint-val" id="jv_${side}_${j}">0°</span>
      <div class="joint-btns">
        <button class="jbtn" id="jminus_${side}_${j}">−</button>
        <button class="jbtn" id="jplus_${side}_${j}">+</button>
      </div>`;
    ctrl.appendChild(row);
  });
  // Button hold for joint +/-
  JOINTS.forEach((j,i)=>{
    let iv=null;
    const pm=document.getElementById(`jminus_${side}_${j}`);
    const pp=document.getElementById(`jplus_${side}_${j}`);
    function startJoint(dir){
      stopJoint();
      selectJoint(side,i);
      adjustJoint(side,j,dir);
      iv=setInterval(()=>adjustJoint(side,j,dir),100);
    }
    function stopJoint(){clearInterval(iv);}
    pm.addEventListener('pointerdown',e=>{e.preventDefault();startJoint(-5)});
    pm.addEventListener('pointerup',e=>{e.preventDefault();stopJoint()});
    pm.addEventListener('pointerleave',stopJoint);
    pp.addEventListener('pointerdown',e=>{e.preventDefault();startJoint(5)});
    pp.addEventListener('pointerup',e=>{e.preventDefault();stopJoint()});
    pp.addEventListener('pointerleave',stopJoint);
  });
  drawArm(side);
}

function selectJoint(side,i){
  selectedJoint[side]=i;
  JOINTS.forEach((j,k)=>{
    document.getElementById(`row_${side}_${j}`)?.classList.toggle('selected',k===i);
  });
}

async function adjustJoint(side,joint,delta){
  armVals[side][joint]=Math.max(-100,Math.min(100,(armVals[side][joint]||0)+delta));
  updateJointDisplay(side,joint);
  await fetch('/arm',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({side,joint,value:armVals[side][joint]})});
}

function updateJointDisplay(side,joint){
  const el=document.getElementById(`jv_${side}_${joint}`);
  if(el)el.innerText=(armVals[side][joint]||0).toFixed(0)+'°';
  drawArm(side);
}

function showArm(side,el){
  document.querySelectorAll('.arm-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.arm-panel').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('panel_'+side).classList.add('active');
}

buildArmPanel('left');buildArmPanel('right');

// Base buttons
let activeBase=null,baseIv=null;
function startBase(cmd){
  if(activeBase===cmd)return;stopBase();
  activeBase=cmd;document.getElementById(cmd)?.classList.add('on');
  sendBase(cmd);baseIv=setInterval(()=>sendBase(cmd),80);
}
function stopBase(){
  if(activeBase)document.getElementById(activeBase)?.classList.remove('on');
  activeBase=null;clearInterval(baseIv);sendBase('stop');
}
async function sendBase(cmd){
  try{
    const r=await fetch('/base',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})});
    const d=await r.json();
    const lh=d.lift||0;
    document.getElementById('lift_h').innerText=lh.toFixed(1);
    document.getElementById('lift_fill').style.width=Math.max(0,Math.min(100,lh/6)).toFixed(1)+'%';
    document.getElementById('spd_val').innerText=(d.speed||0.3).toFixed(2)+' m/s';
    document.getElementById('dot').className='status-dot ok';
    document.getElementById('status_txt').innerText='Connected ✓';
  }catch(e){document.getElementById('status_txt').innerText='Error';}
}

['w','s','a','d','z','x','u','j','stop'].forEach(id=>{
  const el=document.getElementById(id);if(!el)return;
  el.addEventListener('pointerdown',e=>{e.preventDefault();startBase(id)});
  el.addEventListener('pointerup',e=>{e.preventDefault();stopBase()});
  el.addEventListener('pointerleave',e=>{if(activeBase===id)stopBase()});
});
['r','f'].forEach(id=>{
  const el=document.getElementById(id);if(!el)return;
  el.addEventListener('click',()=>sendBase(id));
});

document.addEventListener('keydown',e=>{
  const k=e.key.toLowerCase();
  if(['w','s','a','d','z','x','u','j','r','f'].includes(k)){e.preventDefault();startBase(k);}
});
document.addEventListener('keyup',()=>stopBase());

// Status poll
setInterval(async()=>{
  try{
    const d=await(await fetch('/status')).json();
    document.getElementById('gamepad_txt').innerText=d.gamepad!=='none'?'🎮 '+d.gamepad:'No gamepad';
    const lh=d.lift||0;
    document.getElementById('lift_h').innerText=lh.toFixed(1);
    document.getElementById('lift_fill').style.width=Math.max(0,Math.min(100,lh/6)).toFixed(1)+'%';
    if(d.arms){['left','right'].forEach(side=>{
      JOINTS.forEach(j=>{
        const v=d.arms[side]?.[j];
        if(v!==undefined&&Math.abs((armVals[side][j]||0)-v)>0.5){
          armVals[side][j]=v;updateJointDisplay(side,j);
        }
      });
    });}
  }catch(e){}
},300);
</script>
</body>
</html>"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/base', methods=['POST'])
def base_cmd():
    cmd = request.json.get('cmd','stop')
    with lock:
        sp = state["base_speed"]
        rs = state["rot_speed"]
        lh = state["lift_height"]

    lv = 0
    x = y = theta = 0.0
    if   cmd=='w': x = sp
    elif cmd=='s': x = -sp
    elif cmd=='a': theta = rs
    elif cmd=='d': theta = -rs
    elif cmd=='z': y = sp
    elif cmd=='x': y = -sp
    elif cmd=='u': lv = 1
    elif cmd=='j': lv = -1
    elif cmd=='r':
        with lock: state["base_speed"] = min(state["base_speed"]+0.05, 1.0)
    elif cmd=='f':
        with lock: state["base_speed"] = max(state["base_speed"]-0.05, 0.05)

    new_lh = lh + lv * 2.0
    with lock:
        state["base_active"] = {"x": x, "y": y, "theta": theta}
        state["lift_height"] = new_lh
        sp = state["base_speed"]

    return jsonify(lift=new_lh, speed=sp)

@app.route('/arm', methods=['POST'])
def arm_cmd():
    data = request.json
    side  = data.get('side','left')
    joint = data.get('joint','shoulder_pan')
    value = float(data.get('value', 0))
    with lock:
        if side == 'left':  state["arm_left"][joint]  = value
        else:               state["arm_right"][joint] = value
    return jsonify(ok=True)

@app.route('/status')
def status():
    with lock:
        return jsonify(
            lift=state["lift_height"],
            speed=state["base_speed"],
            gamepad=state["gamepad"],
            arms={"left": dict(state["arm_left"]), "right": dict(state["arm_right"])},
        )

if __name__ == '__main__':
    print(f"Open: http://localhost:{WEB_PORT}")
    print(f"Also on phone: check your PC IP")
    app.run(host='0.0.0.0', port=WEB_PORT, threaded=True)
