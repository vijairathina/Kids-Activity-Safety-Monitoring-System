"""
Zone Safety Manager: Handles polygon/rectangle danger zones, safe play zones,
entry/exit tracking, residency dwell time, and zone alerts.
"""

import time
from typing import List, Dict, Any, Optional, Tuple
from app.config.settings import load_config
from app.ai.tracker import TrackedPerson


def point_in_polygon(point: Tuple[float, float], polygon: List[List[float]]) -> bool:
    """Ray-casting algorithm to test if a point (x, y) is inside a polygon."""
    x, y = point
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


class ZoneManager:
    """Monitors person interactions with defined safety and danger zones."""

    def __init__(self):
        # Per-person, per-zone state: {(person_id, zone_id): {"entry_time": float, "last_alert": float}}
        self.dwell_states: Dict[Tuple[int, str], Dict[str, float]] = {}

    def analyze(self, person: TrackedPerson) -> List[Dict[str, Any]]:
        """
        Check if tracked person intersects any configured zones.
        Uses bottom-center of bounding box (feet position) for floor residency.
        """
        zones = getattr(self, "zones", None)
        if zones is None:
            cfg = load_config()
            zones = cfg.get("zones", [])
        if not zones:
            return []

        bw = person.box[2] - person.box[0]
        bh = person.box[3] - person.box[1]
        if bw < 18 or bh < 25 or (bw * bh) < 600:
            return []

        now = time.time()
        events: List[Dict[str, Any]] = []

        # Feet position (bottom center of bounding box)
        feet_pt = (float(person.cx), float(person.box[3]))
        # Centroid position
        center_pt = (float(person.cx), float(person.cy))

        safe_zones_present = any(z.get("type") == "SAFE_ZONE" for z in zones)
        in_any_safe_zone = False

        for zone in zones:
            zid = zone.get("id", "zone")
            zname = zone.get("name", zid)
            ztype = zone.get("type", "CUSTOM")
            pts = zone.get("points", [])
            severity = zone.get("severity", "WARNING")
            min_duration = float(zone.get("min_duration_sec", 1.5))

            if len(pts) < 3:
                continue

            # Check PTZ orientation for 360-degree cameras
            from app.camera.ptz import ptz_controller
            ptz_stat = ptz_controller.get_status()
            current_pos = ptz_stat.get("position", {})
            current_pan = current_pos.get("pan")
            current_tilt = current_pos.get("tilt")
            cal_pan = zone.get("calibrated_pan")
            cal_tilt = zone.get("calibrated_tilt")

            if cal_pan is not None and current_pan is not None and cal_tilt is not None and current_tilt is not None:
                # If camera is pointed in a different direction, skip zone
                if abs(current_pan - float(cal_pan)) > 0.20 or abs(current_tilt - float(cal_tilt)) > 0.20:
                    continue

            # Check if feet or center point is inside polygon
            is_inside = point_in_polygon(feet_pt, pts) or point_in_polygon(center_pt, pts)
            state_key = (person.track_id, zid)

            if is_inside:
                person.zone_id = zname
                if ztype == "SAFE_ZONE":
                    in_any_safe_zone = True

                if state_key not in self.dwell_states:
                    self.dwell_states[state_key] = {"entry_time": now, "last_alert": 0.0}

                st = self.dwell_states[state_key]
                dwell_time = now - st["entry_time"]

                # Immediate danger zone entry alert
                if ztype in ["DANGER_ZONE", "STAIR_ZONE", "BALCONY_ZONE", "KITCHEN_ZONE", "POWER_ZONE"]:
                    if st["last_alert"] == 0.0 and dwell_time >= 0.5:
                        st["last_alert"] = now
                        person.activity_state = "DANGER_ZONE"
                        events.append({
                            "event_type": f"CHILD_ENTERED_{ztype}",
                            "severity": severity,
                            "confidence": 0.90,
                            "confidence_level": "DETECTED",
                            "person_id": person.track_id,
                            "location_zone": zname,
                            "duration": round(dwell_time, 1),
                            "details": {
                                "zone_type": ztype,
                                "zone_name": zname,
                                "description": f"Child entered restricted area: {zname}"
                            }
                        })
                    elif dwell_time >= min_duration and (now - st["last_alert"] > 12.0):
                        # Sustained residency alert
                        st["last_alert"] = now
                        events.append({
                            "event_type": "DANGER_ZONE_ACTIVITY",
                            "severity": severity,
                            "confidence": 0.92,
                            "confidence_level": "DETECTED",
                            "person_id": person.track_id,
                            "location_zone": zname,
                            "duration": round(dwell_time, 1),
                            "details": {
                                "zone_type": ztype,
                                "zone_name": zname,
                                "description": f"Prolonged activity in danger zone: {zname} ({round(dwell_time, 1)}s)"
                            }
                        })
            else:
                # Left zone
                if state_key in self.dwell_states:
                    del self.dwell_states[state_key]

        # Check if child wandered outside of safe zone
        if safe_zones_present and not in_any_safe_zone and person.age > 10:
            left_safe_key = (person.track_id, "LEFT_SAFE_ZONE")
            if left_safe_key not in self.dwell_states:
                self.dwell_states[left_safe_key] = {"entry_time": now, "last_alert": 0.0}
            lst = self.dwell_states[left_safe_key]
            if now - lst["last_alert"] > 20.0:
                lst["last_alert"] = now
                events.append({
                    "event_type": "CHILD_LEFT_SAFE_ZONE",
                    "severity": "INFO",
                    "confidence": 0.85,
                    "confidence_level": "DETECTED",
                    "person_id": person.track_id,
                    "location_zone": "Outside Safe Area",
                    "duration": round(now - lst["entry_time"], 1),
                    "details": {
                        "description": "Child moved outside designated safe play zone"
                    }
                })

        return events

    def cleanup_old_tracks(self, active_track_ids: List[int]):
        """Purge tracks that have departed."""
        curr = set(active_track_ids)
        for (tid, zid) in list(self.dwell_states.keys()):
            if tid not in curr:
                del self.dwell_states[(tid, zid)]
