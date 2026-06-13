"""
AlohaMini Robot Face Display
Runs ON the Pi, shows on the 7" HDMI touchscreen.
- Animated SVG eyes + mood expressions
- Emergency stop button (sends zero cmd via ZMQ)
- System status: CPU temp, IP, uptime
"""

import json, os, subprocess, threading, time, socket
from pathlib import Path
from flask import Flask, jsonify, Response

CMD_PORT  = int(os.environ.get("CMD_PORT", 5555))
WEB_PORT  = int(os.environ.get("DISPLAY_PORT", 8090))
FACE_HTML = Path(__file__).parent / "ui_robot_face.html"

app = Flask(__name__)

# ── ZMQ E-stop ────────────────────────────────────────────────────────────────
_estop_active = threading.Event()
_zmq_ok = False

def _init_zmq():
    global _zmq_ok
    try:
        import zmq
        ctx = zmq.Context()
        sock = ctx.socket(zmq.PUSH)
        sock.setsockopt(zmq.SNDHWM, 1)
        sock.connect(f"tcp://127.0.0.1:{CMD_PORT}")
        app.zmq_sock = sock
        _zmq_ok = True
    except Exception as e:
        print(f"[Display] ZMQ unavailable: {e}")
        app.zmq_sock = None

threading.Thread(target=_init_zmq, daemon=True).start()

STOP_ACTION = {
    "x.vel": 0.0, "y.vel": 0.0, "theta.vel": 0.0,
    "__disarm_robot": True,
    "__estop": True,
}

def _estop_loop():
    _estop_active.set()
    sock = getattr(app, "zmq_sock", None)
    if not sock:
        return
    payload = json.dumps(STOP_ACTION).encode()
    t0 = time.time()
    while time.time() - t0 < 5.0:
        try: sock.send(payload, flags=1)  # NOBLOCK
        except: pass
        time.sleep(0.05)
    _estop_active.clear()

# ── System info ───────────────────────────────────────────────────────────────
def _cpu_temp():
    try:
        t = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return round(int(t) / 1000, 1)
    except: return None

def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except: return "?"

def _uptime():
    try:
        secs = float(Path("/proc/uptime").read_text().split()[0])
        h, m = int(secs // 3600), int((secs % 3600) // 60)
        return f"{h}h {m:02d}m"
    except: return "?"

def _load():
    try:
        return os.getloadavg()[0]
    except: return 0.0

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if FACE_HTML.exists():
        return FACE_HTML.read_text(encoding="utf-8")
    return "<h1>ui_robot_face.html missing</h1>"

@app.route("/estop", methods=["POST"])
def estop():
    if not _estop_active.is_set():
        threading.Thread(target=_estop_loop, daemon=True).start()
    return jsonify(ok=True, active=True)

@app.route("/estop_release", methods=["POST"])
def estop_release():
    _estop_active.clear()
    return jsonify(ok=True, active=False)

@app.route("/status")
def status():
    return jsonify(
        ip=_local_ip(),
        temp=_cpu_temp(),
        uptime=_uptime(),
        load=round(_load(), 2),
        zmq=_zmq_ok,
        estop=_estop_active.is_set(),
        hostname=socket.gethostname(),
    )

if __name__ == "__main__":
    print(f"Robot face: http://localhost:{WEB_PORT}")
    app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)
