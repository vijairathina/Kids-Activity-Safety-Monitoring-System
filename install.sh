#!/usr/bin/env bash
# ==============================================================================
# Kids Activity & Safety Monitoring System - Installation Script
# Target: Raspberry Pi (Raspberry Pi OS Bookworm/Bullseye, 32-bit & 64-bit)
# ==============================================================================

set -e

echo "======================================================================"
echo "  Kids Activity & Safety Monitoring System Installation"
echo "  Optimized for Raspberry Pi 4 / 5 / Zero 2W"
echo "======================================================================"

# Ensure script is run with bash
if [ -z "$BASH_VERSION" ]; then
    echo "Error: This script must be run with bash."
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "[1/6] Installing Linux system dependencies..."
sudo apt-get update -y
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libportaudio2 \
    libasound2-dev \
    portaudio19-dev \
    sqlite3

echo "[2/6] Creating Python virtual environment (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

echo "[3/6] Upgrading pip and wheel..."
pip install --upgrade pip setuptools wheel

echo "[4/6] Installing Python dependencies from requirements.txt..."
pip install -r requirements.txt

echo "[5/6] Initializing storage directories..."
mkdir -p data/snapshots data/recordings data/events
chmod -R 755 data

echo "[6/6] Installing systemd service (kids-monitor.service)..."
SERVICE_FILE="/etc/systemd/system/kids-monitor.service"
CURRENT_USER=$(whoami)

# Generate tailored service file
cat <<EOF | sudo tee "$SERVICE_FILE" > /dev/null
[Unit]
Description=Kids Activity & Safety Monitoring System
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
Environment="PORT=5000"
Environment="HOST=0.0.0.0"
ExecStart=$PROJECT_DIR/venv/bin/python3 $PROJECT_DIR/run.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kids-monitor

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

echo "======================================================================"
echo "  ✅ INSTALLATION COMPLETED SUCCESSFULLY!"
echo "======================================================================"
echo ""
echo "To start the application right now:"
echo "    ./start.sh"
echo ""
echo "To enable and start as a system background service:"
echo "    sudo systemctl enable --now kids-monitor"
echo ""
echo "To view system service status and logs:"
echo "    sudo systemctl status kids-monitor"
echo "    sudo journalctl -u kids-monitor -f"
echo ""
echo "Web Dashboard will be available at:"
echo "    http://localhost:5000"
echo "    http://$(hostname -I | awk '{print $1}'):5000"
echo "======================================================================"
