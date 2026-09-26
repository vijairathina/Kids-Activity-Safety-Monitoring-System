"""
Telegram Alert Dispatcher.
Sends rich markdown notification and attaches snapshot image on safety events.
"""

import os
import requests
from typing import Dict, Any, Optional
from app.config.settings import load_config


def send_telegram_alert(event: Dict[str, Any], snapshot_path: Optional[str] = None):
    """Dispatch alert message to configured Telegram bot."""
    cfg = load_config()
    tg_cfg = cfg.get("alerts", {}).get("telegram", {})
    if not tg_cfg.get("enabled", False):
        return

    bot_token = tg_cfg.get("bot_token", "").strip()
    chat_id = tg_cfg.get("chat_id", "").strip()
    if not bot_token or not chat_id:
        return

    event_type = event.get("event_type", "UNKNOWN")
    severity = event.get("severity", "INFO")
    conf_level = event.get("confidence_level", "POSSIBLE")
    confidence = int(event.get("confidence", 0.0) * 100)
    zone = event.get("location_zone") or "Living Area"
    details = event.get("details", {})
    desc = details.get("description", event_type)

    icon = "🚨" if severity == "CRITICAL" else ("⚠️" if severity == "WARNING" else "ℹ️")

    text = (
        f"{icon} *Kids Safety Alert: {severity}*\n\n"
        f"*Event:* {event_type}\n"
        f"*Status:* {conf_level} ({confidence}% confidence)\n"
        f"*Zone:* {zone}\n"
        f"*Details:* {desc}\n"
        f"*Time:* {event.get('timestamp')}\n\n"
        f"_Assistive monitor — does not replace adult supervision._"
    )

    try:
        if snapshot_path and os.path.exists(snapshot_path):
            url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            with open(snapshot_path, "rb") as photo:
                requests.post(
                    url,
                    data={"chat_id": chat_id, "caption": text, "parse_mode": "Markdown"},
                    files={"photo": photo},
                    timeout=8.0
                )
        else:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            requests.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=8.0
            )
    except Exception as e:
        print(f"[Telegram] Failed to send alert: {e}")
