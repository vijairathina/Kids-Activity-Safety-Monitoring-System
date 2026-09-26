"""
Electrical Hazard Interaction Detector.
Monitors hand / wrist proximity to configured POWER_ZONE, WALL_SWITCH_ZONE,
or LAMP_ZONE and tracks duration. Avoids claiming absolute electrical contact.
"""

import math
import time
from typing import Dict, Any, Optional, List, Tuple
from app.config.settings import load_config
from app.ai.tracker import TrackedPerson


def distance_point_to_polygon(pt: Tuple[float, float], poly: List[List[float]]) -> float:
    """Calculate approximate distance from point to polygon center or boundary."""
    px, py = pt
    # Polygon centroid
    cx = sum(p[0] for p in poly) / float(len(poly))
    cy = sum(p[1] for p in poly) / float(len(poly))
    return math.hypot(px - cx, py - cy)


class ElectricalSafetyDetector:
    """Detects dangerous proximity of children's hands to electrical fixtures."""

    def __init__(self):
        # {(person_id, zone_id): {"approach_start": float, "last_alert": float}}
        self.contact_states: Dict[Tuple[int, str], Dict[str, float]] = {}

    def analyze(self, person: TrackedPerson, pose_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Evaluate wrist coordinates relative to electrical danger zones."""
        cfg = load_config()
        elec_cfg = cfg.get("electrical", {})
        if not elec_cfg.get("enabled", True):
            return []

        zones = cfg.get("zones", [])
        power_zones = [z for z in zones if z.get("type") in ["POWER_ZONE", "WALL_SWITCH_ZONE", "LAMP_ZONE"]]
        if not power_zones:
            return []

        bw = person.box[2] - person.box[0]
        bh = person.box[3] - person.box[1]
        if bw < 18 or bh < 25 or (bw * bh) < 600:
            return []

        prox_thresh_px = float(elec_cfg.get("hand_proximity_threshold_px", 50.0))
        prox_warn_sec = float(elec_cfg.get("proximity_warning_sec", 1.0))
        inter_warn_sec = float(elec_cfg.get("interaction_warning_sec", 3.0))

        keypoints = pose_data.get("keypoints", {})
        left_wrist = keypoints.get("left_wrist")
        right_wrist = keypoints.get("right_wrist")

        # Hands to test
        hands = []
        if left_wrist:
            hands.append(tuple(left_wrist))
        if right_wrist:
            hands.append(tuple(right_wrist))

        # If pose didn't find hands, use bounding box lateral edges
        if not hands:
            bx1, by1, bx2, by2 = person.box
            hands = [(bx1, int(by1 + (by2 - by1) * 0.5)), (bx2, int(by1 + (by2 - by1) * 0.5))]

        events = []
        now = time.time()

        for pz in power_zones:
            zid = pz.get("id", "elec_zone")
            zname = pz.get("name", "Electrical Zone")
            pts = pz.get("points", [])
            if len(pts) < 3:
                continue

            # Find closest distance from any hand to zone
            min_dist = min([distance_point_to_polygon(h, pts) for h in hands])
            state_key = (person.track_id, zid)

            # Zone center radius approximation
            poly_radius = max([math.hypot(p[0] - pts[0][0], p[1] - pts[0][1]) for p in pts]) / 2.0
            effective_dist = max(0.0, min_dist - poly_radius)

            if effective_dist <= prox_thresh_px:
                if state_key not in self.contact_states:
                    self.contact_states[state_key] = {"approach_start": now, "last_alert": 0.0}

                st = self.contact_states[state_key]
                duration = now - st["approach_start"]

                if duration >= inter_warn_sec and (now - st["last_alert"] > 10.0):
                    st["last_alert"] = now
                    events.append({
                        "event_type": "POSSIBLE_ELECTRICAL_INTERACTION",
                        "severity": "CRITICAL",
                        "confidence": 0.86,
                        "confidence_level": "LIKELY",
                        "person_id": person.track_id,
                        "location_zone": zname,
                        "duration": round(duration, 1),
                        "details": {
                            "description": f"Sustained hand interaction near electrical source: {zname}",
                            "proximity_px": round(effective_dist, 1),
                            "duration_sec": round(duration, 1)
                        }
                    })
                elif duration >= prox_warn_sec and st["last_alert"] == 0.0:
                    st["last_alert"] = now
                    events.append({
                        "event_type": "POSSIBLE_ELECTRICAL_PROXIMITY",
                        "severity": "WARNING",
                        "confidence": 0.78,
                        "confidence_level": "POSSIBLE",
                        "person_id": person.track_id,
                        "location_zone": zname,
                        "duration": round(duration, 1),
                        "details": {
                            "description": f"Hand approaching electrical fixture: {zname}",
                            "proximity_px": round(effective_dist, 1)
                        }
                    })
            else:
                if state_key in self.contact_states:
                    del self.contact_states[state_key]

        return events

    def cleanup_old_tracks(self, active_track_ids: List[int]):
        """Clear state for departed tracks."""
        curr = set(active_track_ids)
        for (tid, zid) in list(self.contact_states.keys()):
            if tid not in curr:
                del self.contact_states[(tid, zid)]
