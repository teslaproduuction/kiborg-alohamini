"""
Convert web-recorded demonstrations (recordings/<dataset>/episode_*/) into a
LeRobot dataset that `lerobot-train` can consume.

Recordings are produced by controller_v3.py Record tab — JSONL frames +
camera JPEGs, no torch needed to record. This converter DOES need the full
lerobot env (run with the same venv/conda used for training).

Usage:
    python convert_recording.py <dataset_name> [--repo_id user/name] [--fps 30] [--task "pick cube"]

Output: a LeRobotDataset at HF_LEROBOT_HOME/<repo_id>. Push/train as usual.
"""

import argparse, json, sys
from pathlib import Path

import numpy as np

try:
    from PIL import Image
except ImportError:
    print("Need Pillow:  pip install pillow"); sys.exit(1)

try:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
except ImportError:
    print("Need lerobot env (torch + lerobot). Run in the training venv/conda."); sys.exit(1)

REC_DIR = Path(__file__).parent / "recordings"

# Action vector layout (must match controller_v3 build_action order)
BASE_KEYS = ["x.vel", "y.vel", "theta.vel", "lift_axis.height_mm"]
ARM_JOINTS = ["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"]
ACTION_KEYS = BASE_KEYS + [f"arm_left_{j}.pos" for j in ARM_JOINTS] + [f"arm_right_{j}.pos" for j in ARM_JOINTS]
# State (observation) layout
STATE_KEYS = [f"left_{j}" for j in ARM_JOINTS] + [f"right_{j}" for j in ARM_JOINTS] + ["lift_mm"]


def load_episode(ep_dir: Path):
    frames = []
    with open(ep_dir / "data.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                frames.append(json.loads(line))
    return frames


def detect_cameras(frames):
    cams = set()
    for fr in frames:
        cams.update(fr["observation"].get("cameras", {}).keys())
    return sorted(cams)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="recordings/<dataset> folder name")
    ap.add_argument("--repo_id", default=None, help="output repo id (default: local/<dataset>)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--task", default="teleop demonstration")
    ap.add_argument("--img_size", type=int, nargs=2, default=None, help="resize WxH (optional)")
    args = ap.parse_args()

    ds_dir = REC_DIR / args.dataset
    if not ds_dir.exists():
        print(f"No such recording: {ds_dir}"); sys.exit(1)
    eps = sorted(ds_dir.glob("episode_*"))
    if not eps:
        print("No episodes."); sys.exit(1)

    # Peek first episode to detect cameras + image shape
    first = load_episode(eps[0])
    if not first:
        print("Empty episode."); sys.exit(1)
    cams = detect_cameras(first)
    print(f"Episodes: {len(eps)} · cameras: {cams or 'none'}")

    img_shape = None
    if cams:
        sample_rel = next((fr["observation"]["cameras"].get(cams[0]) for fr in first
                            if fr["observation"]["cameras"].get(cams[0])), None)
        if sample_rel:
            im = Image.open(eps[0] / sample_rel)
            if args.img_size: im = im.resize(tuple(args.img_size))
            img_shape = (im.height, im.width, 3)

    # Build LeRobot feature schema
    features = {
        "action": {"dtype": "float32", "shape": (len(ACTION_KEYS),), "names": ACTION_KEYS},
        "observation.state": {"dtype": "float32", "shape": (len(STATE_KEYS),), "names": STATE_KEYS},
    }
    for c in cams:
        features[f"observation.images.{c}"] = {
            "dtype": "video", "shape": img_shape or (480, 640, 3), "names": ["height", "width", "channel"]
        }

    repo_id = args.repo_id or f"local/{args.dataset}"
    dataset = LeRobotDataset.create(
        repo_id=repo_id, fps=args.fps, features=features,
        robot_type="alohamini", use_videos=True, image_writer_threads=4,
    )
    print(f"Created dataset: {repo_id}")

    for ep_dir in eps:
        frames = load_episode(ep_dir)
        for fr in frames:
            act = fr["action"]
            action_vec = np.array([float(act.get(k, 0.0)) for k in ACTION_KEYS], dtype=np.float32)
            joints = fr["observation"]["joints"]
            state_vec = np.array([float(joints.get(k, 0.0)) for k in STATE_KEYS], dtype=np.float32)
            frame = {"action": action_vec, "observation.state": state_vec}
            for c in cams:
                rel = fr["observation"]["cameras"].get(c)
                if rel and (ep_dir / rel).exists():
                    im = Image.open(ep_dir / rel).convert("RGB")
                    if args.img_size: im = im.resize(tuple(args.img_size))
                    frame[f"observation.images.{c}"] = np.asarray(im)
                else:
                    frame[f"observation.images.{c}"] = np.zeros(img_shape or (480, 640, 3), dtype=np.uint8)
            dataset.add_frame(frame, task=args.task)
        dataset.save_episode()
        print(f"  saved {ep_dir.name} ({len(frames)} frames)")

    print(f"\nDone. Train with:\n  lerobot-train --dataset.repo_id={repo_id} --policy.type=act --policy.device=cuda")


if __name__ == "__main__":
    main()
