# AGENTS.md — AlohaMini Project: Agent Operating Guide

For AI agents (Claude, Cursor, Copilot, etc.) working in this repo.

## Context

This project builds an **AlohaMini** robot from scratch. Three repos are present:

| Repo | Purpose |
|------|---------|
| `AlohaMini/` | Hardware: CAD, STL, BOM, simulation |
| `lerobot_alohamini/` | **Primary software** — AlohaMini fork of LeRobot |
| `lerobot/` | Upstream HuggingFace LeRobot — reference only |

**Always prefer `lerobot_alohamini/` for software questions.** Check its `AGENTS.md`, `CLAUDE.md`, and `AGENT_GUIDE.md` for detailed architecture and commands.

## User context

- Building robot physically, asks wiring/firmware/SSH questions during assembly
- Target platform: **Raspberry Pi 5 (8GB)**, ARM64 Linux
- Robot: dual follower arms + mobile base + lift
- ML framework: LeRobot with Feetech STS3215 servo stack

## How to answer hardware questions

Before suggesting any command or wiring step:
1. Check which build stage user is at (ask if unclear)
2. Reference motor IDs and connections from `CLAUDE.md`
3. For motor config → FD Debug Tool steps
4. For RPi SSH → exact commands from `CLAUDE.md`
5. For LeRobot commands → use `lerobot_alohamini/AGENT_GUIDE.md` §4

## Key files to read first

| Question type | File to read |
|---------------|-------------|
| Wiring / motor IDs | `.claude/CLAUDE.md` |
| LeRobot commands | `lerobot_alohamini/AGENT_GUIDE.md` |
| LeRobot architecture | `lerobot_alohamini/AGENTS.md` |
| Dev setup / tests | `lerobot_alohamini/CLAUDE.md` |
| Hardware BOM / CAD | `AlohaMini/docs/` |
| Simulation | `AlohaMini/simulation/` |

## Coding in this project

- Package manager: **uv** (not pip, not conda) for `lerobot_alohamini/` contributions
- Python 3.12+
- Run commands via `uv run <cmd>` not raw `python`
- Pre-commit: `pre-commit run --all-files` before any commit
- Tests: `uv run pytest tests -svv --maxfail=10`

## Critical constraints

- STS3215 motors are **12V variant** — never suggest 5V/7.4V config
- Motor IDs must be set one-at-a-time via FD Debug Tool before first use
- Port permissions (`chmod 666 /dev/ttyACM*`) required after every RPi reboot
- `lerobot_alohamini` not `lerobot` — upstream is reference only
