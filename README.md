# 🛡️ Kids Activity & Safety Monitoring System

A lightweight, privacy-focused edge monitoring system built for **Raspberry Pi** and low-spec edge computing devices using ONVIF/RTSP IP cameras.

Designed to run **100% locally on the device** without cloud dependencies, avoiding latency and protecting family privacy.

---

## 📑 Table of Contents

1. [Key Features](#-key-features)
2. [Architecture Overview](#-architecture-overview)
3. [Safety Rule Engine & Detection Logic](#-safety-rule-engine--detection-logic)
4. [Hardware Optimization for Raspberry Pi](#-hardware-optimization-for-raspberry-pi)
5. [Installation & Setup](#-installation--setup)
6. [Interactive Web Dashboard](#-interactive-web-dashboard)
7. [Home Assistant & MQTT Integration](#-home-assistant--mqtt-integration)
8. [Alert Channels & Privacy Controls](#-alert-channels--privacy-controls)
9. [API Reference](#-api-reference)
10. [Testing & Simulation](#-testing--simulation)

---

## 🌟 Key Features

- **Privacy-First Local Execution**: No external cloud uploads. All AI models, video streams, audio analysis, and database storage remain strictly on the local Raspberry Pi.
- **Child Activity Recognition Engine**: Multi-modal classification for:
  - **Watching TV**: Seated orientation and proximity to television screens.
  - **Dancing**: Rhythmic cadence, arm elevation, and energetic oscillation.
  - **Active Playing**: Floor interaction within designated play zones.
  - **Reading Book**: Focused posture with books, tablets, or learning materials.
  - **Writing / Homework**: Seated desk posture with forward inclination and surface engagement.
- **Dedicated Fall Detection**: Evaluates bounding-box aspect ratio ($W/H > 1.15$), body inclination angle ($< 40^\circ$), vertical drop velocity spikes, and ground plane proximity with temporal confirmation to prevent false alarms.
- **Interactive Danger Zone Editor**: Draw arbitrary polygons and rectangles over live video feed (Wall Sockets, Staircases, Balconies, Stoves, Safe Play Mats).
- **Electrical Hazard Interaction**: Combines pose keypoint estimation (wrists/hands) with power zone proximity and duration tracking.
- **Physical Conflict Detection**: Monitors multi-person distance, mutual kinematics variance, and audio correlation. Adheres strictly to calibrated phrasing: *"Possible physical conflict detected"*.
- **Acoustic Anomaly & Scream Detection**: Lightweight FFT spectral centroid analysis (1500–3500 Hz vocal screaming band), RMS volume spikes, and sudden impact bangs.
- **Event-Based Ring Buffer Recording**: Circular in-memory buffer stores the preceding 5–10 seconds. When an incident occurs, it saves pre-event + event + post-event video clips alongside high-resolution snapshots.
- **Home Assistant & MQTT Auto-Discovery**: Automatically exposes entities for safety status, activity, person count, and hazard binary sensors.
- **ONVIF & Network Discovery**: Integrated multi-tiered scanner (WS-Discovery, port scan, USB webcam probe) automatically finds IP cameras and retrieves RTSP stream profiles.
- **Systemd Service & RPi Health Monitoring**: Real-time CPU%, RAM%, disk storage, thermal temperature tracking (`vcgencmd` / sysfs), and allowlisted service controls.
- **Synthetic Demo Simulator**: Built-in simulator with animated child actors and living room hazards allows instant testing without requiring an active physical camera.

---

## 🏗️ Architecture Overview

```
app/
├── app.py                     # Flask web app, REST endpoints, SSE stream
├── config/
│   ├── config.yaml            # Main configuration parameters
│   └── settings.py            # YAML persistence & credential masking
├── camera/
│   ├── rtsp.py                # Threaded RTSP capture & demo stream generator
│   ├── onvif.py               # WS-Discovery & ONVIF device client
│   └── stream_manager.py      # Stream coordinator & MJPEG generator
├── ai/
│   ├── detector.py            # Ultralytics YOLO & OpenCV HOG fallback
│   ├── tracker.py             # Lightweight IoU & velocity multi-person tracker
│   ├── pose.py                # On-demand pose keypoint estimation
│   ├── activity.py            # Activity state machine with temporal smoothing
│   └── audio.py               # Independent audio thread & FFT spectral monitor
├── safety/
│   ├── fall.py                # Dedicated fall detector
│   ├── electrical.py          # Wrist-to-power-zone proximity analyzer
│   ├── conflict.py            # Interpersonal distance & kinematics analyzer
│   ├── zones.py               # Ray-casting point-in-polygon zone manager
│   └── anomaly.py             # Stationary state & night-mode anomaly detector
├── events/
│   ├── engine.py              # Central engine, signal correlation, SSE broadcast
│   ├── database.py            # SQLite events, logs, and retention storage
│   └── recorder.py            # Circular frame buffer & video clip recorder
├── alerts/
│   ├── telegram.py            # Telegram bot notifications with photo attachment
│   ├── mqtt.py                # MQTT state publishing & Home Assistant discovery
│   ├── homeassistant.py       # REST webhook dispatcher
│   ├── webhook.py             # Generic HTTP POST webhook
│   └── gpio.py                # Raspberry Pi hardware buzzer controller
├── system/
│   ├── monitor.py             # CPU, RAM, thermal temp, disk, uptime metrics
│   └── service.py             # systemd service status and allowlisted operations
├── templates/                 # Glassmorphism HTML templates
├── static/                    # CSS stylesheets and modular JavaScript
└── tests/                     # Automated unit and integration tests
```

---

## 🔬 Safety Rule Engine & Detection Logic

### 1. Confidence Calibration Standards
The system categorizes events into calibrated confidence tiers to prevent computer-vision false certainty:
- **DETECTED**: High-confidence zone breach or confirmed positional intrusion ($> 85\%$).
- **LIKELY**: Multi-signal alignment (e.g. downward drop + horizontal posture + ground plane for $>2.0$s) ($85\% - 95\%$).
- **POSSIBLE**: Indicative kinematics (e.g. rapid proximity between two persons, hand approaching electrical socket) ($60\% - 84\%$).
- **UNKNOWN**: Ambiguous room movement.

### 2. Multi-Signal Event Correlation Examples
1. **Fall Detection Rule**:
   $$\text{Person Detected} + \text{Vertical Velocity Drop} > 45\text{px/s} + \text{Aspect Ratio } (W/H) \ge 1.15 + \text{Dwell on Floor} \ge 2\text{s} \implies \textbf{FALL\_DETECTED}$$
2. **Electrical Hazard Rule**:
   $$\text{Person} + \text{POWER\_ZONE} + \text{Wrist Proximity} \le 50\text{px} + \text{Dwell} \ge 3.0\text{s} \implies \textbf{POSSIBLE\_ELECTRICAL\_INTERACTION}$$
3. **Physical Conflict Rule**:
   $$\ge 2\text{ Persons} + \text{Distance} \le 90\text{px} + \text{Combined Speed} \ge 25\text{px/s} \implies \textbf{POSSIBLE\_PHYSICAL\_CONFLICT}$$

---

## ⚡ Hardware Optimization for Raspberry Pi

To deliver high responsiveness on low-power ARM devices (Raspberry Pi 3, 4, 5, Zero 2W):
1. **Dual-Stream Pipeline**: Utilizes the low-resolution camera sub-stream (e.g., 320x240 or 640x480) for AI detection, reserving the main high-res RTSP stream for recording evidence.
2. **Asynchronous Non-Blocking Capture**: Camera frames are read continuously in a dedicated thread with `CAP_PROP_BUFFERSIZE = 1`, eliminating buffer latency.
3. **Frame Decoupling**: Video streaming runs at 15–25 FPS while AI detection runs at a configured 4–8 FPS.
4. **On-Demand Pose Estimation**: Heavy pose keypoint estimation is triggered only when a person approaches a defined danger zone or experiences a sudden vertical drop.
5. **Ultra-Lightweight Multi-Object Tracker**: The IoU + velocity centroid tracker executes in $< 0.4$ ms per frame.
6. **Graceful AI Fallback**: Automatic detection backend hierarchy:
   $$\text{Ultralytics YOLO (YOLOv8n / YOLO11n)} \longrightarrow \text{OpenCV DNN / HOG People Detector} \longrightarrow \text{Contour Kinematics}$$

---

## 🚀 Installation & Setup

### Automated Installation (Raspberry Pi OS)

Clone the repository and run the automated installer:

```bash
git clone https://github.com/your-username/kids-safety-monitor.git
cd kids-safety-monitor

chmod +x install.sh start.sh
./install.sh
```

The installer will:
1. Install Linux packages (`ffmpeg`, `libportaudio2`, `sqlite3`, `libgl1`).
2. Create a Python 3 virtual environment (`venv`).
3. Install dependencies from `requirements.txt`.
4. Install and configure the systemd unit `/etc/systemd/system/kids-monitor.service`.

### Windows Setup & Quick Start

```cmd
:: 1. Setup virtual environment and dependencies
setup_venv.bat

:: 2. Launch the application
run.bat
:: Or directly via venv python:
.\venv\Scripts\python.exe run.py --port 5055 --demo
```

### Starting the System (Linux / Raspberry Pi)

**Option A: Run Directly in Terminal**
```bash
./start.sh
# Or with options:
python run.py --port 5000 --demo
```

**Option B: Start via systemd (Auto-start on boot)**
```bash
sudo systemctl enable --now kids-monitor
```

Check service status and logs:
```bash
sudo systemctl status kids-monitor
sudo journalctl -u kids-monitor -f
```

Open your browser at:
```
http://localhost:5000 (or http://<raspberry-pi-ip>:5000)
```

---

## 🖥️ Interactive Web Dashboard

| Page | URL | Description |
|---|---|---|
| **Live Monitor** | `/` | Live video feed with toggleable overlays, current activity state, room audio meter, and real-time SSE safety events stream. |
| **Camera & ONVIF** | `/camera` | Configure RTSP URLs, run ONVIF WS-Discovery to find cameras on the local network, and inspect stream latency. |
| **Danger Zones** | `/zones` | Interactive HTML5 canvas editor to draw, resize, and configure danger polygons and safe play zones. |
| **Event History** | `/events` | Searchable event database with date/type/severity filters, snapshot preview, MP4 playback, and acknowledgment. |
| **System & RPi** | `/system` | CPU, RAM, disk, thermal temperature line graphs, and allowlisted systemd service management. |
| **Settings** | `/settings` | Fine-tune AI framerate, fall thresholds, electrical proximity distances, night schedules, Telegram, and MQTT. |

---

## 🏠 Home Assistant & MQTT Integration

Enable MQTT under **Settings > Alert Channels & Smart Home Integrations**:
- **Broker**: `192.168.1.50` (Home Assistant IP)
- **Port**: `1883`
- **Prefix**: `kids_monitor`

The monitor will automatically publish Home Assistant MQTT Auto-Discovery configuration payloads:
```
homeassistant/sensor/kids_monitor/activity/config
homeassistant/sensor/kids_monitor/safety_status/config
homeassistant/binary_sensor/kids_monitor/fall_detected/config
homeassistant/binary_sensor/kids_monitor/danger_zone/config
homeassistant/binary_sensor/kids_monitor/conflict_detected/config
```

Entities will immediately populate in Home Assistant without manual YAML configuration.

---

## 🔒 Privacy Controls

- **Local Storage Only**: All recordings and database records remain in `data/` on the local SD card/SSD.
- **Privacy Mode**: Toggleable from the UI to suppress disk storage of snapshots and video clips while maintaining real-time safety alerts.
- **Facial Anonymization**: Optional automatic face blurring using Gaussian filters on detected person crops.
- **Credential Masking**: RTSP passwords and API tokens are never logged and are masked as `******` across the web UI.

---

## 🧪 Testing & Simulation

The test suite validates kinematics, ray-casting point-in-polygon math, and audio FFT extraction:

```bash
python -m unittest discover -s app/tests -p "test_*.py"
```

To test the system immediately without an IP camera:
1. Start the app: `python run.py --demo`
2. Open the dashboard at `http://localhost:5000`
3. Use the **Scenario Selector** dropdown above the video feed to test:
   - `Scenario: Normal Play`
   - `Scenario: Simulated Fall` (triggers fall detector, snapshot, and recording)
   - `Scenario: Power Socket Hazard` (triggers hand proximity warning)
   - `Scenario: Physical Conflict` (triggers interpersonal conflict warning)
4. Click **Test Scream** or **Test Impact** under Room Microphone to verify acoustic alerts.

---

## ⚠️ Important Safety Notice

This application is an **assistive monitoring tool** utilizing computer vision and audio heuristics. It is designed to aid parents and caregivers, but **under no circumstances should it replace direct adult supervision**.
