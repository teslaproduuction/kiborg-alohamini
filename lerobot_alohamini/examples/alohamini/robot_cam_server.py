"""
AlohaMini Camera Server
Streams cameras as MJPEG over HTTP (single-frame ffmpeg grabs).

  python robot_cam_server.py          # default: video2,4,6,8 on port 8091
  CAMS=0,2,4,6,8 python robot_cam_server.py

Routes:
  /cam/<index>   MJPEG stream
  /snap/<index>  single JPEG
  /list          JSON list of active cameras
"""

import os, threading, time, subprocess
from pathlib import Path
from flask import Flask, Response, jsonify

CAM_PORT = int(os.environ.get("CAM_PORT", 8091))
FFMPEG   = os.environ.get("FFMPEG", "/home/pi/miniforge3/envs/lerobot/bin/ffmpeg")
CAMS_ENV = os.environ.get("CAMS", "2,4,6,8")
CAM_DEVS = [f"/dev/video{n.strip()}" for n in CAMS_ENV.split(",")]
FPS      = int(os.environ.get("CAM_FPS", "3"))
W, H     = 320, 240

app = Flask(__name__)
_frames: dict[str, bytes] = {}
_lock   = threading.Lock()

def grab_loop(dev: str):
    while True:
        try:
            r = subprocess.run(
                [FFMPEG, "-y", "-f", "v4l2", "-input_format", "mjpeg",
                 "-video_size", f"{W}x{H}", "-i", dev,
                 "-frames:v", "1", "-f", "image2", "-vcodec", "mjpeg", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                s = r.stdout.find(b"\xff\xd8")
                if s >= 0:
                    with _lock:
                        _frames[dev] = r.stdout[s:]
        except Exception as e:
            print(f"[CamServer] {dev}: {e}")
        time.sleep(1.0 / FPS)

active = []
for dev in CAM_DEVS:
    if Path(dev).exists():
        threading.Thread(target=grab_loop, args=(dev,), daemon=True).start()
        active.append(dev)
        print(f"[CamServer] streaming {dev}")
    else:
        print(f"[CamServer] {dev} not found, skipping")

@app.route("/cam/<int:idx>")
def mjpeg_stream(idx):
    dev = f"/dev/video{idx}"
    def gen():
        while True:
            with _lock: frame = _frames.get(dev, b"")
            if frame:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(1.0 / FPS)
    r = Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")
    r.headers["Access-Control-Allow-Origin"] = "*"
    return r

@app.route("/snap/<int:idx>")
def snapshot(idx):
    dev = f"/dev/video{idx}"
    with _lock: frame = _frames.get(dev, b"")
    if not frame: return "no frame", 404
    r = Response(frame, mimetype="image/jpeg")
    r.headers["Access-Control-Allow-Origin"] = "*"
    return r

@app.route("/list")
def cam_list():
    with _lock: alive = [d for d in active if d in _frames]
    return jsonify(cameras=alive, all=active)

if __name__ == "__main__":
    print(f"Camera server: http://0.0.0.0:{CAM_PORT}")
    print(f"Cameras: {active}")
    app.run(host="0.0.0.0", port=CAM_PORT, threaded=True)
