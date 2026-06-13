#!/bin/bash
# Install AlohaMini systemd services on Raspberry Pi
# Run once: bash install_services.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[1/4] Copying service files..."
sudo cp "$SCRIPT_DIR/alohamini-host.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/alohamini-cam.service"  /etc/systemd/system/

echo "[2/4] Reloading systemd..."
sudo systemctl daemon-reload

echo "[3/4] Enabling services (auto-start on boot)..."
sudo systemctl enable alohamini-host.service
sudo systemctl enable alohamini-cam.service

echo "[4/4] Starting services now..."
sudo systemctl start alohamini-host.service
sleep 4
sudo systemctl start alohamini-cam.service

echo ""
echo "Done. Status:"
sudo systemctl status alohamini-host.service --no-pager -l | tail -10
echo ""
echo "Useful commands:"
echo "  journalctl -u alohamini-host -f    # live log"
echo "  systemctl restart alohamini-host   # restart host"
echo "  systemctl disable alohamini-host   # remove auto-start"
