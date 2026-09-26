"""
Configuration settings manager for Kids Activity & Safety Monitoring System.
Handles YAML persistence, thread safety, environment variable overrides,
and credential masking.
"""

import os
import copy
import threading
import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "app" / "config" / "config.yaml"
ENV_PATH = BASE_DIR / ".env"

_config_lock = threading.RLock()
_cached_config = None


def load_env():
    """Load key-value pairs from .env if present."""
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def get_default_config():
    """Return default configuration dict."""
    return {
        "camera": {
            "name": "Living Room Camera",
            "source_type": "demo",
            "rtsp_url": "",
            "sub_stream_url": "",
            "username": "admin",
            "password": "",
            "ip": "192.168.1.100",
            "onvif_port": 80,
            "fps": 15,
            "width": 640,
            "height": 480,
            "reconnect_interval_sec": 5,
            "buffer_size": 1
        },
        "ai": {
            "backend": "auto",
            "model_name": "yolov8n.pt",
            "detection_fps": 6,
            "confidence_threshold": 0.45,
            "iou_threshold": 0.45,
            "target_size": [320, 320],
            "device": "cpu",
            "track_history_length": 30,
            "classes": ["person", "chair", "table", "knife", "bottle", "tv", "laptop", "book", "cell phone", "couch", "pet"]
        },
        "privacy": {
            "privacy_mode": False,
            "face_blur": False,
            "mask_credentials": True,
            "cloud_upload": False,
            "log_level": "INFO"
        },
        "fall": {
            "enabled": True,
            "aspect_ratio_threshold": 1.15,
            "angle_threshold_deg": 40.0,
            "min_confirmation_sec": 2.0,
            "velocity_drop_threshold": 45.0,
            "ground_plane_y_ratio": 0.65
        },
        "electrical": {
            "enabled": True,
            "hand_proximity_threshold_px": 50.0,
            "proximity_warning_sec": 1.0,
            "interaction_warning_sec": 3.0
        },
        "conflict": {
            "enabled": True,
            "max_proximity_px": 90.0,
            "rapid_motion_threshold": 25.0,
            "min_conflict_sec": 2.0,
            "require_audio_correlation": False
        },
        "audio": {
            "enabled": True,
            "sample_rate": 16000,
            "rms_threshold": 0.35,
            "peak_threshold": 0.70,
            "screaming_frequency_min": 1500,
            "screaming_frequency_max": 3500,
            "listen_device_index": -1
        },
        "zones": [
            {
                "id": "zone_power_1",
                "name": "Wall Power Outlet",
                "type": "POWER_ZONE",
                "points": [[50, 320], [130, 320], [130, 420], [50, 420]],
                "color": "#ff3366",
                "severity": "CRITICAL",
                "min_duration_sec": 1.5,
                "alert_action": "immediate"
            },
            {
                "id": "zone_stair_1",
                "name": "Staircase Entrance",
                "type": "STAIR_ZONE",
                "points": [[460, 180], [620, 180], [620, 470], [460, 470]],
                "color": "#ff9900",
                "severity": "WARNING",
                "min_duration_sec": 2.0,
                "alert_action": "immediate"
            },
            {
                "id": "zone_safe_play",
                "name": "Play Mat Safe Zone",
                "type": "SAFE_ZONE",
                "points": [[180, 240], [430, 240], [430, 460], [180, 460]],
                "color": "#00e676",
                "severity": "INFO",
                "min_duration_sec": 5.0,
                "alert_action": "none"
            }
        ],
        "recording": {
            "enabled": True,
            "pre_event_sec": 5,
            "post_event_sec": 5,
            "retention_days": 7,
            "max_storage_mb": 2048,
            "recordings_path": "data/recordings",
            "snapshots_path": "data/snapshots"
        },
        "night_mode": {
            "enabled": False,
            "start_hour": 22,
            "end_hour": 6,
            "heighten_severity": True
        },
        "alerts": {
            "web_chime": True,
            "telegram": {
                "enabled": False,
                "bot_token": "",
                "chat_id": ""
            },
            "mqtt": {
                "enabled": False,
                "broker": "localhost",
                "port": 1883,
                "username": "",
                "password": "",
                "topic_prefix": "kids_monitor",
                "discovery_enabled": True
            },
            "homeassistant": {
                "enabled": False,
                "webhook_url": ""
            },
            "webhook": {
                "enabled": False,
                "endpoint_url": ""
            },
            "gpio": {
                "enabled": False,
                "buzzer_pin": 18,
                "duration_sec": 0.8
            }
        },
        "server": {
            "host": "0.0.0.0",
            "port": 5055
        }
    }


def load_config():
    """Load configuration from file, falling back to defaults."""
    global _cached_config
    with _config_lock:
        load_env()
        if not CONFIG_PATH.exists():
            example_path = CONFIG_PATH.parent / "config.example.yaml"
            if example_path.exists():
                import shutil
                shutil.copy(str(example_path), str(CONFIG_PATH))
            else:
                default_cfg = get_default_config()
                save_config(default_cfg)
            _cached_config = default_cfg
            return copy.deepcopy(_cached_config)

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                # Merge defaults for any missing keys
                defaults = get_default_config()
                for k, v in defaults.items():
                    if k not in data:
                        data[k] = v
                    elif isinstance(v, dict):
                        for sub_k, sub_v in v.items():
                            data[k].setdefault(sub_k, sub_v)
                _cached_config = data
        except Exception as e:
            print(f"[Settings] Error loading config: {e}. Falling back to default.")
            _cached_config = get_default_config()

        return copy.deepcopy(_cached_config)


def save_config(new_config: dict):
    """Save configuration safely to YAML file."""
    global _cached_config
    with _config_lock:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(new_config, f, default_flow_style=False, sort_keys=False)
        _cached_config = copy.deepcopy(new_config)


def update_config_section(section: str, values: dict):
    """Update a specific config section."""
    with _config_lock:
        cfg = load_config()
        if section not in cfg:
            cfg[section] = {}
        if isinstance(cfg[section], dict) and isinstance(values, dict):
            cfg[section].update(values)
        else:
            cfg[section] = values
        save_config(cfg)
        return copy.deepcopy(cfg)


def mask_sensitive_url(url: str) -> str:
    """Mask credentials in RTSP or HTTP URLs for privacy/logs."""
    if not url or "@" not in url:
        return url
    try:
        prefix, rest = url.split("://", 1)
        creds, host = rest.split("@", 1)
        if ":" in creds:
            user, _ = creds.split(":", 1)
            return f"{prefix}://{user}:******@{host}"
        return f"{prefix}://******@{host}"
    except Exception:
        return url


def get_sanitized_config() -> dict:
    """Return a version of configuration with passwords masked for UI presentation."""
    cfg = load_config()
    if "camera" in cfg:
        if cfg["camera"].get("password"):
            cfg["camera"]["password"] = "******"
        if cfg["camera"].get("rtsp_url"):
            cfg["camera"]["rtsp_url_masked"] = mask_sensitive_url(cfg["camera"]["rtsp_url"])
    if "alerts" in cfg and "mqtt" in cfg["alerts"]:
        if cfg["alerts"]["mqtt"].get("password"):
            cfg["alerts"]["mqtt"]["password"] = "******"
    if "alerts" in cfg and "telegram" in cfg["alerts"]:
        if cfg["alerts"]["telegram"].get("bot_token"):
            token = cfg["alerts"]["telegram"]["bot_token"]
            if len(token) > 8:
                cfg["alerts"]["telegram"]["bot_token"] = token[:4] + "..." + token[-4:]
    return cfg
