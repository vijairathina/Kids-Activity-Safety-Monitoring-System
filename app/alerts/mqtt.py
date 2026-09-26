"""
MQTT and Home Assistant Auto-Discovery Integration.
Publishes real-time sensor states and Home Assistant discovery configs.
"""

import json
import threading
import time
from typing import Dict, Any, Optional
from app.config.settings import load_config


class MQTTManager:
    """MQTT client managing state telemetry and Home Assistant discovery."""

    def __init__(self):
        self.client = None
        self.is_connected = False
        self.prefix = "kids_monitor"
        self._lock = threading.Lock()

    def start(self):
        """Initialize and connect MQTT client in background."""
        cfg = load_config()
        mqtt_cfg = cfg.get("alerts", {}).get("mqtt", {})
        if not mqtt_cfg.get("enabled", False):
            return

        try:
            import paho.mqtt.client as mqtt
            self.prefix = mqtt_cfg.get("topic_prefix", "kids_monitor")
            broker = mqtt_cfg.get("broker", "localhost")
            port = int(mqtt_cfg.get("port", 1883))
            user = mqtt_cfg.get("username", "")
            password = mqtt_cfg.get("password", "")

            # Support paho-mqtt v1 and v2 API
            try:
                self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="kids_safety_monitor")
            except Exception:
                self.client = mqtt.Client(client_id="kids_safety_monitor")

            if user and password:
                self.client.username_pw_set(user, password)

            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect

            self.client.connect_async(broker, port, 60)
            self.client.loop_start()
            print(f"[MQTT] Connecting to broker at {broker}:{port}...")
        except Exception as e:
            print(f"[MQTT] Failed to start client: {e}")

    def stop(self):
        """Disconnect and stop client loop."""
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
            self.is_connected = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.is_connected = True
            print("[MQTT] Connected to broker successfully.")
            self._publish_ha_discovery()
        else:
            print(f"[MQTT] Connect failed with code {rc}")

    def _on_disconnect(self, client, userdata, flags, rc=None, properties=None):
        self.is_connected = False
        print("[MQTT] Disconnected from broker.")

    def _publish_ha_discovery(self):
        """Publish Home Assistant MQTT Auto-Discovery topics."""
        cfg = load_config()
        if not cfg.get("alerts", {}).get("mqtt", {}).get("discovery_enabled", True):
            return

        device_info = {
            "identifiers": ["kids_safety_monitoring_system"],
            "name": "Kids Safety Monitor",
            "model": "RPi Safety Edge",
            "manufacturer": "Local Edge AI",
            "sw_version": "1.0.0"
        }

        sensors = [
            ("sensor", "safety_status", "Kids Safety Status", "{{ value_json.safety_status }}", "safety"),
            ("sensor", "activity", "Kids Primary Activity", "{{ value_json.activity }}", None),
            ("sensor", "last_event", "Kids Last Event", "{{ value_json.last_event }}", None),
            ("sensor", "person_count", "Kids Person Count", "{{ value_json.person_count }}", None),
            ("binary_sensor", "fall_detected", "Kids Fall Detected", "{{ value_json.fall_detected }}", "safety"),
            ("binary_sensor", "danger_zone", "Kids Danger Zone", "{{ value_json.danger_zone }}", "motion"),
            ("binary_sensor", "conflict_detected", "Kids Conflict Detected", "{{ value_json.conflict_detected }}", "problem")
        ]

        for component, name_id, friendly_name, val_template, dev_class in sensors:
            disc_topic = f"homeassistant/{component}/{self.prefix}/{name_id}/config"
            payload = {
                "name": friendly_name,
                "state_topic": f"{self.prefix}/state",
                "value_template": val_template,
                "unique_id": f"{self.prefix}_{name_id}",
                "device": device_info
            }
            if dev_class:
                payload["device_class"] = dev_class
            self.client.publish(disc_topic, json.dumps(payload), retain=True)

    def publish_state(self, state_dict: Dict[str, Any]):
        """Publish updated state payload to state topic."""
        if not self.is_connected or not self.client:
            return
        try:
            topic = f"{self.prefix}/state"
            payload = {
                "safety_status": state_dict.get("safety_status", "NORMAL"),
                "activity": state_dict.get("activity", "NORMAL"),
                "last_event": state_dict.get("last_event", "None"),
                "person_count": state_dict.get("person_count", 0),
                "fall_detected": "ON" if state_dict.get("fall_detected") else "OFF",
                "danger_zone": "ON" if state_dict.get("danger_zone") else "OFF",
                "conflict_detected": "ON" if state_dict.get("conflict_detected") else "OFF",
                "timestamp": time.time()
            }
            self.client.publish(topic, json.dumps(payload), qos=1)
        except Exception as e:
            print(f"[MQTT] Publish state failed: {e}")

    def publish_event(self, event: Dict[str, Any]):
        """Publish event JSON to specific event topic."""
        if not self.is_connected or not self.client:
            return
        try:
            topic = f"{self.prefix}/event"
            self.client.publish(topic, json.dumps(event), qos=1)
        except Exception as e:
            print(f"[MQTT] Publish event failed: {e}")
