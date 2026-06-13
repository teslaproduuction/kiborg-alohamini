#!/usr/bin/env python3
"""
Convert AlohaMini custom recordings to LeRobot-compatible dataset format.

Input:  recordings/<dataset>/episode_NNN/data.jsonl  (+ frames/ images)
Output: datasets/<dataset>/
            data/episode_XXXXXXXX.parquet
            videos/observation.images.<cam>/episode_XXXXXXXX.mp4
            meta_data/info.json
            meta_data/stats.json
            meta_data/episodes.jsonl

Usage:
    python convert_recording.py demo
    python convert_recording.py demo --out-dir datasets/ --fps 30 --image-size 320 240
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    import pandas as pd
except ImportError:
    print("pip install pandas pyarrow")
    sys.exit(1)

try:
    import cv2
except ImportError:
    print("pip install opencv-python")
    sys.exit(1)


# ── Joint order (fixed — must match lerobot config) ───────────────────────────
LEFT_JOINTS  = ["left_shoulder_pan","left_shoulder_lift","left_elbow_flex",
                "left_wrist_flex","left_wrist_roll","left_gripper"]
RIGHT_JOINTS = ["right_shoulder_pan","right_shoulder_lift","right_elbow_flex",
                "right_wrist_flex","right_wrist_roll","right_gripper"]
BASE_KEYS    = ["x_vel","y_vel","theta_vel","lift_mm"]
OBS_KEYS     = LEFT_JOINTS + RIGHT_JOINTS + BASE_KEYS

ACT_KEYS = (
    [f"arm_left_{j.replace('left_','')}.pos"  for j in LEFT_JOINTS] +
    [f"arm_right_{j.replace('right_','')}.pos" for j in RIGHT_JOINTS] +
    ["x.vel", "y.vel", "theta.vel", "lift_axis.height_mm"]
)


def _obs_vec(obs_joints: dict) -> list:
    return [float(obs_joints.get(k, 0.0)) for k in OBS_KEYS]


def _act_vec(action: dict) -> list:
    return [float(action.get(k, 0.0)) for k in ACT_KEYS]


def make_video(frames_dir: Path, cam: str, out: Path, fps: int, size: tuple):
    imgs = sorted(frames_dir.glob(f"{cam}_*.jpg"))
    if not imgs:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for p in imgs:
        img = cv2.imread(str(p))
        if img is not None:
            vw.write(cv2.resize(img, (w, h)))
    vw.release()
    return True


def convert(dataset: str, rec_root: Path, out_root: Path,
            fps: int = 30, img_size: tuple = (320, 240)):
    ds_in  = rec_root / dataset
    ds_out = out_root / dataset
    if not ds_in.exists():
        sys.exit(f"Not found: {ds_in}")

    episodes = sorted(ds_in.glob("episode_*"))
    if not episodes:
        sys.exit(f"No episodes in {ds_in}")

    ds_out.mkdir(parents=True, exist_ok=True)
    (ds_out / "data").mkdir(exist_ok=True)
    (ds_out / "meta_data").mkdir(exist_ok=True)

    all_rows, ep_meta, cam_keys = [], [], set()
    total = 0

    for ep_idx, ep_dir in enumerate(episodes):
        df_file = ep_dir / "data.jsonl"
        if not df_file.exists():
            print(f"  skip {ep_dir.name}: no data.jsonl")
            continue
        frames_dir = ep_dir / "frames"

        rows = []
        with open(df_file) as f:
            for line in f:
                try: rec = json.loads(line)
                except: continue
                act = rec.get("action", {})
                if act.get("__disarm_robot") or act.get("__arm_robot"):
                    continue
                obs = rec.get("observation", {})
                rows.append({
                    "t":       rec.get("t", 0.0),
                    "obs":     _obs_vec(obs.get("joints", {})),
                    "act":     _act_vec(act),
                    "cams":    obs.get("cameras", {}),
                    "ep":      ep_idx,
                })
                cam_keys.update(obs.get("cameras", {}).keys())

        if not rows:
            print(f"  skip {ep_dir.name}: empty")
            continue
        n = len(rows)
        print(f"  ep {ep_idx:03d}  {n:4d} frames  cameras={sorted(cam_keys)}")

        # Parquet rows
        pq_rows = []
        for fi, r in enumerate(rows):
            row = {
                "episode_index": ep_idx,
                "frame_index":   fi,
                "timestamp":     r["t"],
                "next.done":     fi == n - 1,
            }
            for i, k in enumerate(OBS_KEYS):
                row[f"observation.state.{k}"] = r["obs"][i]
            for i, k in enumerate(ACT_KEYS):
                row[f"action.{k}"] = r["act"][i]
            pq_rows.append(row)
        pd.DataFrame(pq_rows).to_parquet(
            ds_out / "data" / f"episode_{ep_idx:08d}.parquet", index=False
        )
        all_rows.extend(pq_rows)

        # Videos
        for cam in cam_keys:
            ok = make_video(
                frames_dir, cam,
                ds_out / "videos" / f"observation.images.{cam}" / f"episode_{ep_idx:08d}.mp4",
                fps, img_size
            )
            if not ok:
                print(f"    warn: no frames for cam '{cam}'")

        ep_meta.append({"episode_index": ep_idx, "length": n})
        total += n

    if not all_rows:
        sys.exit("No valid data to convert.")

    # Stats
    df = pd.DataFrame(all_rows)
    stats = {}
    for col in [c for c in df.columns if c.startswith(("observation.state.", "action."))]:
        stats[col] = {"mean": float(df[col].mean()), "std": max(float(df[col].std()), 1e-4),
                      "min": float(df[col].min()), "max": float(df[col].max())}

    info = {
        "fps": fps, "robot": "alohamini",
        "observation": {"state_dim": len(OBS_KEYS), "state_keys": OBS_KEYS},
        "action":      {"action_dim": len(ACT_KEYS), "action_keys": ACT_KEYS},
        "camera_keys": sorted(cam_keys), "image_size": list(img_size),
        "num_episodes": len(ep_meta), "total_frames": total,
    }
    (ds_out / "meta_data" / "info.json").write_text(json.dumps(info, indent=2))
    (ds_out / "meta_data" / "stats.json").write_text(json.dumps(stats, indent=2))
    with open(ds_out / "meta_data" / "episodes.jsonl", "w") as f:
        for ep in ep_meta: f.write(json.dumps(ep) + "\n")

    print(f"\n✓  {len(ep_meta)} episodes  {total} frames  → {ds_out}")
    print(f"   obs_dim={len(OBS_KEYS)}  act_dim={len(ACT_KEYS)}  cams={sorted(cam_keys)}")
    print()
    print("Next:")
    print(f"  lerobot train --config-name=alohamini \\")
    print(f"    --dataset-path={ds_out} \\")
    print(f"    --policy.type=act \\")
    print(f"    --output-dir=./checkpoints/{dataset}_v1")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--rec-dir",    default=None)
    ap.add_argument("--out-dir",    default=None)
    ap.add_argument("--fps",        type=int, default=30)
    ap.add_argument("--image-size", type=int, nargs=2, default=[320, 240], metavar=("W","H"))
    a = ap.parse_args()

    here     = Path(__file__).parent
    rec_root = Path(a.rec_dir) if a.rec_dir else here / "recordings"
    out_root = Path(a.out_dir) if a.out_dir else here / "datasets"
    convert(a.dataset, rec_root, out_root, a.fps, tuple(a.image_size))
