"""Web-based teleop UI for AlohaMini. Opens in browser, no keyboard capture needed."""

import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import zmq

REMOTE_IP = "172.24.93.157"
CMD_PORT = 5555
OBS_PORT = 5556
WEB_PORT = 8080

ctx = zmq.Context()
cmd_sock = ctx.socket(zmq.PUSH)
cmd_sock.connect(f"tcp://{REMOTE_IP}:{CMD_PORT}")
obs_sock = ctx.socket(zmq.PULL)
obs_sock.connect(f"tcp://{REMOTE_IP}:{OBS_PORT}")
obs_sock.setsockopt(zmq.RCVTIMEO, 50)

state = {"lift_height": 0.0, "obs": {}}
state_lock = threading.Lock()

def obs_thread():
    while True:
        try:
            raw = obs_sock.recv()
            obs = json.loads(raw.decode())
            with state_lock:
                state["obs"] = obs
                state["lift_height"] = obs.get("lift_axis.height_mm", state["lift_height"])
        except zmq.Again:
            pass
        except Exception:
            time.sleep(0.1)

threading.Thread(target=obs_thread, daemon=True).start()

HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AlohaMini Control</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: monospace; background:#111; color:#eee; text-align:center; user-select:none; }
h2 { color:#0af; }
.grid { display:inline-grid; grid-template-columns:repeat(3,80px); gap:8px; margin:16px; }
.btn {
    height:80px; font-size:18px; font-weight:bold;
    background:#222; border:2px solid #444; border-radius:10px;
    color:#eee; cursor:pointer; touch-action:none;
}
.btn:active, .btn.active { background:#0af; color:#000; border-color:#0af; }
.lift-row { margin:12px; }
.lift-row .btn { width:120px; height:60px; }
.speed { margin:12px; font-size:14px; color:#aaa; }
#status { color:#0f0; margin:8px; font-size:13px; }
</style>
</head>
<body>
<h2>AlohaMini</h2>
<div id="status">Connecting...</div>

<div class="grid">
  <div></div>
  <button class="btn" id="w" data-cmd="w">&#9650;<br>FWD</button>
  <div></div>
  <button class="btn" id="a" data-cmd="a">&#9668;<br>ROT L</button>
  <button class="btn" id="stop" data-cmd="stop" style="background:#300;border-color:#600;">&#9632;<br>STOP</button>
  <button class="btn" id="d" data-cmd="d">&#9658;<br>ROT R</button>
  <div></div>
  <button class="btn" id="s" data-cmd="s">&#9660;<br>BACK</button>
  <div></div>
</div>

<div style="margin:8px">
  <button class="btn" id="z" data-cmd="z" style="width:80px;height:60px">&#8592;<br>LEFT</button>
  &nbsp;
  <button class="btn" id="x" data-cmd="x" style="width:80px;height:60px">&#8594;<br>RIGHT</button>
</div>

<div class="lift-row">
  <button class="btn" id="u" data-cmd="u">&#9650; LIFT</button>
  &nbsp;
  <button class="btn" id="j" data-cmd="j">&#9660; LIFT</button>
</div>

<div class="lift-row">
  <button class="btn" id="r" data-cmd="r" style="width:80px;height:50px;font-size:14px">+ SPEED</button>
  &nbsp;
  <button class="btn" id="f" data-cmd="f" style="width:80px;height:50px;font-size:14px">- SPEED</button>
</div>

<div class="speed" id="speedinfo">Speed: 0.30 m/s</div>

<script>
let activeCmd = null;
let speed = 0.30;
let rotSpeed = 60;
let liftH = 0;
let interval = null;

async function sendCmd(cmd) {
  try {
    const r = await fetch('/cmd', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cmd})});
    const d = await r.json();
    if (d.lift !== undefined) liftH = d.lift;
    if (d.speed !== undefined) speed = d.speed;
    document.getElementById('speedinfo').innerText = 'Speed: ' + speed.toFixed(2) + ' m/s | Lift: ' + liftH.toFixed(1) + ' mm';
    document.getElementById('status').innerText = 'Connected ✓';
  } catch(e) { document.getElementById('status').innerText = 'Error: ' + e; }
}

function startCmd(cmd) {
  if (activeCmd === cmd) return;
  stopCmd();
  activeCmd = cmd;
  document.getElementById(cmd)?.classList.add('active');
  sendCmd(cmd);
  interval = setInterval(() => sendCmd(cmd), 100);
}

function stopCmd() {
  if (activeCmd) {
    document.getElementById(activeCmd)?.classList.remove('active');
    activeCmd = null;
  }
  clearInterval(interval);
  sendCmd('stop');
}

document.querySelectorAll('.btn[data-cmd]').forEach(btn => {
  const cmd = btn.dataset.cmd;
  btn.addEventListener('pointerdown', e => { e.preventDefault(); startCmd(cmd); });
  btn.addEventListener('pointerup', e => { e.preventDefault(); stopCmd(); });
  btn.addEventListener('pointerleave', e => { if (activeCmd === cmd) stopCmd(); });
});

// Keyboard support too
document.addEventListener('keydown', e => {
  const k = e.key.toLowerCase();
  if (['w','s','a','d','z','x','u','j','r','f'].includes(k)) startCmd(k);
});
document.addEventListener('keyup', stopCmd);

// Status poll
setInterval(async () => {
  try {
    const r = await fetch('/status');
    const d = await r.json();
    liftH = d.lift || liftH;
    document.getElementById('status').innerText = 'Connected ✓ | Lift: ' + liftH.toFixed(1) + 'mm';
  } catch(e) {}
}, 500);
</script>
</body>
</html>"""

base_speed = 0.3
rot_speed = 60.0

def make_action(cmd, lift_height):
    global base_speed, rot_speed
    x = y = theta = 0.0
    lift_vel = 0

    if cmd == 'w': x = base_speed
    elif cmd == 's': x = -base_speed
    elif cmd == 'a': theta = rot_speed
    elif cmd == 'd': theta = -rot_speed
    elif cmd == 'z': y = base_speed
    elif cmd == 'x': y = -base_speed
    elif cmd == 'u': lift_vel = 1
    elif cmd == 'j': lift_vel = -1
    elif cmd == 'r': base_speed = min(base_speed + 0.05, 1.0)
    elif cmd == 'f': base_speed = max(base_speed - 0.05, 0.05)

    new_height = lift_height + lift_vel * 2.0
    return {
        "x.vel": x, "y.vel": y, "theta.vel": theta,
        "lift_axis.height_mm": new_height, "lift_axis.vel": lift_vel,
    }, new_height


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == '/status':
            with state_lock:
                lh = state["lift_height"]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"lift": lh}).encode())

    def do_POST(self):
        if self.path == '/cmd':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            cmd = body.get('cmd', 'stop')
            with state_lock:
                lh = state["lift_height"]
            action, new_height = make_action(cmd, lh)
            with state_lock:
                state["lift_height"] = new_height
            cmd_sock.send_string(json.dumps(action))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"lift": new_height, "speed": base_speed}).encode())


if __name__ == "__main__":
    print(f"Open in browser: http://localhost:{WEB_PORT}")
    print(f"Or from phone on same WiFi: http://<your_pc_ip>:{WEB_PORT}")
    print(f"Connecting to robot at {REMOTE_IP}:{CMD_PORT}")
    HTTPServer(("", WEB_PORT), Handler).serve_forever()
