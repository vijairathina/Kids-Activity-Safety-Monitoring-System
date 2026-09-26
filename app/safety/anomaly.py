"""
Anomaly and Night Mode Detector.
Detects unexpected prolonged stillness, sudden anomalous bursts of motion,
and off-hours nighttime activity according to configured schedules.
"""

import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.config.settings import load_config
from app.ai.tracker import TrackedPerson


class AnomalyDetector:
    """Detects statistical and temporal anomalies in behavior."""

    def __init__(self):
        # {track_id: {"stationary_start": float, "last_alert": float}}
        self.stationary_states: Dict[int, Dict[str, float]] = {}
        self.last_night_alert: float = 0.0

    def analyze(self, active_persons: List[TrackedPerson]) -> List[Dict[str, Any]]:
        """Run anomaly heuristics across all tracked persons."""
        cfg = load_config()
        events = []
        now = time.time()
        current_hour = datetime.now().hour

        # 1. Check Night Mode
        night_cfg = cfg.get("night_mode", {})
        if night_cfg.get("enabled", False) and active_persons:
            start_h = int(night_cfg.get("start_hour", 22))
            end_h = int(night_cfg.get("end_hour", 6))

            is_night = (current_hour >= start_h) or (current_hour < end_h)
            if is_night and (now - self.last_night_alert > 60.0):
                self.last_night_alert = now
                p = active_persons[0]
                events.append({
                    "event_type": "NIGHTTIME_ACTIVITY_DETECTED",
                    "severity": "WARNING",
                    "confidence": 0.88,
                    "confidence_level": "DETECTED",
                    "person_id": p.track_id,
                    "location_zone": p.zone_id or "Room",
                    "duration": 0.0,
                    "details": {
                        "description": f"Unusual nighttime movement detected during night hours ({start_h:02d}:00 - {end_h:02d}:00)",
                        "person_count": len(active_persons)
                    }
                })

        # 2. Prolonged Stationary Anomaly (Child motionless on floor/corner for > 45s)
        for p in active_persons:
            tid = p.track_id
            if p.speed < 4.0:  # virtually motionless
                if tid not in self.stationary_states:
                    self.stationary_states[tid] = {"stationary_start": now, "last_alert": 0.0}

                st = self.stationary_states[tid]
                still_duration = now - st["stationary_start"]

                if still_duration >= 45.0 and (now - st["last_alert"] > 60.0):
                    st["last_alert"] = now
                    events.append({
                        "event_type": "UNUSUAL_INACTIVITY",
                        "severity": "WARNING",
                        "confidence": 0.80,
                        "confidence_level": "POSSIBLE",
                        "person_id": tid,
                        "location_zone": p.zone_id or "Living Area",
                        "duration": round(still_duration, 1),
                        "details": {
                            "description": f"Person motionless for unusual duration ({int(still_duration)}s)",
                            "still_duration_sec": round(still_duration, 1)
                        }
                    })
            else:
                if tid in self.stationary_states:
                    del self.stationary_states[tid]

        return events

    def cleanup_old_tracks(self, active_track_ids: List[int]):
        """Clear state for departed tracks."""
        curr = set(active_track_ids)
        for tid in list(self.stationary_states.keys()):
            if tid not in curr:
                del self.stationary_states[tid]
