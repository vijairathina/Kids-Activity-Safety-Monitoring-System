"""
Fighting and Physical Conflict Detector.
Evaluates interpersonal distance, rapid mutual kinematics, and audio correlation.
Strictly adheres to safety phrasing: "Possible physical conflict detected".
"""

import math
import time
from typing import List, Dict, Any, Optional
from app.config.settings import load_config
from app.ai.tracker import TrackedPerson


class ConflictDetector:
    """Detects possible physical altercation between two or more tracked individuals."""

    def __init__(self):
        # {(tid1, tid2): {"start_time": float, "last_alert": float, "motion_energy_acc": float}}
        self.pair_states: Dict[tuple, Dict[str, float]] = {}

    def analyze(
        self,
        active_persons: List[TrackedPerson],
        audio_event: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Check for close proximity + rapid chaotic movement between pairs of persons.
        """
        cfg = load_config()
        conflict_cfg = cfg.get("conflict", {})
        if not conflict_cfg.get("enabled", True):
            return []

        if len(active_persons) < 2:
            return []

        max_prox = float(conflict_cfg.get("max_proximity_px", 90.0))
        rapid_motion_thresh = float(conflict_cfg.get("rapid_motion_threshold", 25.0))
        min_sec = float(conflict_cfg.get("min_conflict_sec", 2.0))
        require_audio = conflict_cfg.get("require_audio_correlation", False)

        has_loud_audio = audio_event is not None and audio_event.get("type") in ["SCREAM_DETECTED", "LOUD_NOISE"]

        now = time.time()
        events = []

        # Iterate over all pairs
        for i in range(len(active_persons)):
            for j in range(i + 1, len(active_persons)):
                p1 = active_persons[i]
                p2 = active_persons[j]

                pair_key = (min(p1.track_id, p2.track_id), max(p1.track_id, p2.track_id))

                # Distance between centroids
                dist = math.hypot(p1.cx - p2.cx, p1.cy - p2.cy)

                # Combined speed / velocity variance
                combined_speed = p1.speed + p2.speed

                is_in_contact = dist <= max_prox
                is_rapid_motion = combined_speed >= rapid_motion_thresh

                if is_in_contact and is_rapid_motion:
                    if pair_key not in self.pair_states:
                        self.pair_states[pair_key] = {"start_time": now, "last_alert": 0.0}

                    st = self.pair_states[pair_key]
                    duration = now - st["start_time"]

                    # Check audio correlation if required
                    if require_audio and not has_loud_audio:
                        continue

                    confidence = 0.72
                    if has_loud_audio:
                        confidence += 0.16
                    if combined_speed > (rapid_motion_thresh * 1.5):
                        confidence += 0.08
                    confidence = min(0.94, round(confidence, 2))

                    confidence_level = "LIKELY" if confidence >= 0.85 else "POSSIBLE"

                    if duration >= min_sec and (now - st["last_alert"] > 15.0):
                        st["last_alert"] = now
                        p1.activity_state = "POSSIBLE_CONFLICT"
                        p2.activity_state = "POSSIBLE_CONFLICT"

                        events.append({
                            "event_type": "POSSIBLE_PHYSICAL_CONFLICT",
                            "severity": "CRITICAL" if confidence >= 0.85 else "WARNING",
                            "confidence": confidence,
                            "confidence_level": confidence_level,
                            "person_id": p1.track_id,
                            "location_zone": p1.zone_id or "Living Area",
                            "duration": round(duration, 1),
                            "details": {
                                "description": f"Possible physical conflict detected between Person #{p1.track_id} and #{p2.track_id}",
                                "paired_person_id": p2.track_id,
                                "interpersonal_distance": round(dist, 1),
                                "combined_velocity": round(combined_speed, 1),
                                "audio_correlated": has_loud_audio
                            }
                        })
                else:
                    if pair_key in self.pair_states:
                        del self.pair_states[pair_key]

        return events
