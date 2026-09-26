"""
Home Assistant REST Webhook Integration and Generic HTTP Webhook.
"""

import requests
from typing import Dict, Any
from app.config.settings import load_config


def send_homeassistant_webhook(event: Dict[str, Any]):
    """Send event payload to Home Assistant webhook automation."""
    cfg = load_config()
    ha_cfg = cfg.get("alerts", {}).get("homeassistant", {})
    if not ha_cfg.get("enabled", False):
        return

    webhook_url = ha_cfg.get("webhook_url", "").strip()
    if not webhook_url:
        return

    try:
        payload = {
            "source": "kids_safety_monitoring_system",
            "event_type": event.get("event_type"),
            "severity": event.get("severity"),
            "confidence": event.get("confidence"),
            "confidence_level": event.get("confidence_level"),
            "person_id": event.get("person_id"),
            "location_zone": event.get("location_zone"),
            "timestamp": event.get("timestamp"),
            "details": event.get("details", {})
        }
        requests.post(webhook_url, json=payload, timeout=4.0)
    except Exception as e:
        print(f"[HomeAssistant] Webhook POST error: {e}")


def send_generic_webhook(event: Dict[str, Any]):
    """Send event payload to custom user webhook endpoint."""
    cfg = load_config()
    wh_cfg = cfg.get("alerts", {}).get("webhook", {})
    if not wh_cfg.get("enabled", False):
        return

    endpoint = wh_cfg.get("endpoint_url", "").strip()
    if not endpoint:
        return

    try:
        requests.post(endpoint, json=event, timeout=4.0)
    except Exception as e:
        print(f"[Webhook] POST error: {e}")
