# CLAUDE.md — AlohaMini Robot Project

AI agents: read this before answering ANY question in this project.

## What we're building

**AlohaMini** — dual-arm mobile robot with lift. Hardware from scratch + LeRobot ML stack.

User is assembling the robot physically. As build progresses, questions will come about:
- What connects where (wiring, cables, motor IDs)
- How to flash / configure motors
- Raspberry Pi 5 setup via SSH
- Running LeRobot software

## Repo layout

```
D:\Проекты\Kiborg\
├── AlohaMini\            ← hardware: CAD/STL, docs, BOM, simulation URDF
│   ├── docs\
│   ├── hardware\         ← STEP and STL files for 3D printing
│   ├── simulation\       ← URDF, Gazebo
│   ├── software\
│   └── examples\
├── lerobot_alohamini\    ← AlohaMini-specific LeRobot fork (PRIMARY for software)
│   ├── CLAUDE.md         ← dev/contributor context
│   ├── AGENTS.md         ← architecture reference
│   ├── AGENT_GUIDE.md    ← user-facing cheat-sheet (SO-101, commands, training)
│   ├── src\lerobot\
│   ├── docs\
│   └── scripts\
└── lerobot\              ← upstream HuggingFace lerobot (reference / parent framework)
    ├── CLAUDE.md
    ├── AGENTS.md
    ├── src\lerobot\
    └── docs\
```

**Rule:** for AlohaMini-specific commands always check `lerobot_alohamini/` first, not `lerobot/`.

## Hardware snapshot

| Component | Qty | Notes |
|-----------|-----|-------|
| Raspberry Pi 5 (8GB) | 1 | Compute |
| Feetech STS3215 servo (12V) | 16 | All motors |
| Waveshare Bus Servo Controller | 3 | 1 per arm + 1 base |
| 12V lithium battery | 1 | Mobile base power |
| 12V→5V DC converter | 1 | Feeds RPi from battery |
| USB cameras | 5 | top / front / rear / 2× arm |
| 4-inch omni wheels | 3 | Mobile base |

## Motor IDs

### Mobile base (Waveshare controller #3)
| ID | Function | Cable length |
|----|----------|-------------|
| 8  | Wheel 1  | 20cm |
| 9  | Wheel 2  | 20cm |
| 10 | Wheel 3  | 20cm |
| 11 | Lift axis | 90cm → left arm controller |

Daisy-chain order: 8 → 9 → 10 → 11, then 90cm cable to left arm Waveshare.

### Follower arms
- Left arm: IDs 1–6, Waveshare controller #1, `/dev/ttyACM0`
- Right arm: IDs 1–6, Waveshare controller #2, `/dev/ttyACM1`
- SO-ARM100 / SO-101 topology (6 motors per arm, daisy-chain)

## Motor ID setup tool

**FD Debug Tool v1.9.8.3** (Windows). One motor at a time:
1. Connect single motor to Waveshare via USB
2. Select port in FD Debug Tool
3. Write target ID to EEPROM
4. Set baudrate (115200 for all motors — must match controller)
5. Repeat for each motor individually

Factory default ID = 1. New motors need IDs set before first use.

## Raspberry Pi setup (quick ref)

```bash
# System packages
sudo apt-get install -y cmake build-essential python3-dev pkg-config ffmpeg \
  libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
  libswscale-dev libswresample-dev libavfilter-dev

# Conda (ARM64)
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh
bash Miniforge3-Linux-aarch64.sh
conda create -y -n lerobot python=3.12
conda activate lerobot
conda install ffmpeg=7.1.1 -c conda-forge

# LeRobot (AlohaMini fork — always use this, not upstream)
git clone https://github.com/liyiteng/lerobot_alohamini.git
cd lerobot_alohamini
pip install -e .
pip install -e ".[feetech]"

# Port permissions
sudo chmod 666 /dev/ttyACM0 /dev/ttyACM1
sudo usermod -a -G dialout $USER
sudo usermod -a -G tty $USER

# HuggingFace
huggingface-cli login
```

## SSH

```bash
# Enable on RPi
sudo systemctl enable ssh && sudo systemctl start ssh

# From dev machine
ssh-keygen -t ed25519
ssh-copy-id pi@<rpi_ip>
ssh pi@<rpi_ip>

# Find RPi on network
nmap -sn 192.168.1.0/24 | grep Raspberry
# or on RPi: hostname -I
```

## LeRobot commands

```bash
# Motor setup (one-time)
lerobot-setup-motors --robot.type=alohamini --robot.port=/dev/ttyACM0

# Calibrate
lerobot-calibrate --robot.type=alohamini_follower_left  --robot.port=/dev/ttyACM0
lerobot-calibrate --robot.type=alohamini_follower_right --robot.port=/dev/ttyACM1

# Teleoperate
lerobot teleoperate --robot-name=alohamini --robot.port=/dev/ttyACM0

# Record dataset
lerobot record --robot-name=alohamini --output-dir=./datasets/demo --num-episodes=50

# Train
lerobot train --config-name=alohamini --dataset-path=./datasets/demo \
  --policy.type=act --output-dir=./checkpoints/v1

# Evaluate
lerobot eval --checkpoint-path=./checkpoints/v1 \
  --robot-name=alohamini --robot.port=/dev/ttyACM0
```

## Hardware profiles
- `alohamini` — full (dual-arm + mobile base + lift)
- `alohamini_2` — version 2
- `alohamini_2_pro` — hybrid metal
- `am_arm200` — single arm

## Voltage warning

**STS3215 comes in two variants: 5V/7.4V and 12V. Not interchangeable.**
AlohaMini uses 12V variant. Wrong voltage = motor error state (blinking LED).
Check motor spec label before powering up.

## LED diagnostics
- All steady red = wiring OK
- One motor dark / chain stops = wiring issue, reseat 3-pin cables
- LEDs blinking = motor error (overload or wrong voltage)

## Build status

User is actively assembling. Current stage unknown — ask if unclear before suggesting steps.
