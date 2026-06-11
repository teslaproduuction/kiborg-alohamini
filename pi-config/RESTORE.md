# Pi Restore Guide — AlohaMini

Flash new SD → boot → SSH in → run steps below.

## 1. WiFi
```bash
sudo cp 50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml
sudo netplan apply
```

## 2. Boot config (fan thresholds)
```bash
sudo cp config.txt /boot/firmware/config.txt
sudo reboot
```

## 3. udev (Waveshare serial ports)
```bash
sudo cp 99-waveshare.rules /etc/udev/rules.d/99-waveshare.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## 4. Groups (serial port access)
```bash
sudo usermod -a -G dialout,tty $USER
# re-login required
```

## 5. System packages
```bash
sudo apt-get install -y cmake build-essential python3-dev pkg-config ffmpeg \
  libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
  libswscale-dev libswresample-dev libavfilter-dev libevdev-dev
```

## 6. Conda + Python env
```bash
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh
bash Miniforge3-Linux-aarch64.sh
conda create -y -n lerobot python=3.12
conda activate lerobot
conda install ffmpeg=7.1.1 -c conda-forge
conda install evdev -c conda-forge
```

## 7. LeRobot (AlohaMini fork)
```bash
git clone https://github.com/liyiteng/lerobot_alohamini.git
cd lerobot_alohamini
pip install -e ".[feetech]"
```

## 8. Apply patches
Copy files from `robot_src/` over the installed versions:
```bash
SITE=$(python -c "import lerobot; import os; print(os.path.dirname(lerobot.__file__))")
cp robot_src/lekiwi.py        $SITE/robots/alohamini/
cp robot_src/lekiwi_host.py   $SITE/robots/alohamini/
cp robot_src/config_lekiwi.py $SITE/robots/alohamini/
cp robot_src/lift_axis.py     $SITE/robots/alohamini/
cp robot_src/lekiwi_client.py $SITE/robots/alohamini/
```

## 9. Calibration
```bash
mkdir -p ~/.cache/huggingface/lerobot/calibration/robots/alohamini
cp calibration/AlohaMiniRobot.json ~/.cache/huggingface/lerobot/calibration/robots/alohamini/
```

## 10. Start robot host
```bash
conda activate lerobot
cd ~/lerobot_alohamini
python -m lerobot.robots.alohamini.lekiwi_host --robot_model alohamini1
```
