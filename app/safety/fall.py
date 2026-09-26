"""
Dedicated Fall Detector for Kids Safety Monitoring System.
Combines Person tracking, Bounding-box aspect ratio, Body inclination angle,
Vertical downward drop velocity, Ground plane proximity, and Temporal state sequence.
Adheres to strict safety guidelines: distinguishes POSSIBLE vs LIKELY fall.
"""

import time
from typing import Dict, Any, Optional, List
from app.config.settings import load_config
from app.ai.tracker import TrackedPerson


class FallDetector:
    """Multi-signal temporal fall detector."""

    def __init__(self):
        # Per-person fall state tracking: {track_id: dict}
        self.person_states: Dict[int, Dict[str, Any]] = {}

    def analyze(
        self,
        person: TrackedPerson,
        pose_data: Dict[str, Any],
        frame_shape: tuple
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze tracked person kinematics for fall patterns.
        frame_shape = (h, w)
        Returns event dict if fall confirmed, else None.
        """
        cfg = load_config()
        fall_cfg = cfg.get("fall", {})
        if not fall_cfg.get("enabled", True):
            return None

        h, w = frame_shape[:2]
        tid = person.track_id
        now = time.time()

        # Extract features
        aspect_ratio = pose_data.get("aspect_ratio", 0.5)  # W / H
        body_angle = pose_data.get("body_angle", 90.0)      # deg from horizontal
        vy = person.vy                                      # vertical velocity (downward > 0)
        bottom_y = person.box[3]                            # lowest point of bbox
        ground_ratio = bottom_y / float(h)                  # fraction of frame height

        bw = person.box[2] - person.box[0]
        bh = person.box[3] - person.box[1]
        if bw < 18 or bh < 18 or (bw * bh) < 600:
            return None

        ar_threshold = float(fall_cfg.get("aspect_ratio_threshold", 1.15))
        angle_threshold = float(fall_cfg.get("angle_threshold_deg", 40.0))
        min_confirm_sec = float(fall_cfg.get("min_confirmation_sec", 2.0))
        velocity_drop_threshold = float(fall_cfg.get("velocity_drop_threshold", 45.0))
        ground_plane_y_ratio = float(fall_cfg.get("ground_plane_y_ratio", 0.65))

        # Check conditions
        is_horizontal = (aspect_ratio >= ar_threshold) or (body_angle <= angle_threshold)
        is_on_ground = ground_ratio >= ground_plane_y_ratio
        had_downward_spike = False

        # Retrieve or initialize person fall state history
        if tid not in self.person_states:
            self.person_states[tid] = {
                "stage": "STANDING",
                "drop_time": 0.0,
                "horizontal_start": 0.0,
                "last_fall_alert": 0.0,
                "peak_down_vy": 0.0
            }

        state = self.person_states[tid]

        # Track downward velocity spike
        if vy > velocity_drop_threshold:
            state["peak_down_vy"] = max(state["peak_down_vy"], vy)
            had_downward_spike = True

        # State Machine Transitions
        if is_horizontal and is_on_ground:
            if state["horizontal_start"] == 0.0:
                state["horizontal_start"] = now

            horizontal_duration = now - state["horizontal_start"]

            # Calculate confidence score
            confidence = 0.65
            if had_downward_spike or state["peak_down_vy"] > velocity_drop_threshold:
                confidence += 0.15
            if aspect_ratio >= 1.3:
                confidence += 0.10
            if body_angle <= 30.0:
                confidence += 0.05
            confidence = min(0.96, round(confidence, 2))

            # Temporal confirmation check (sustained on floor)
            if horizontal_duration >= min_confirm_sec:
                # Cooldown check: do not spam alert for same person within 15 seconds
                if now - state["last_fall_alert"] > 15.0:
                    state["last_fall_alert"] = now
                    confidence_level = "LIKELY" if confidence >= 0.85 else "POSSIBLE"
                    person.activity_state = "POSSIBLE_FALL"

                    return {
                        "event_type": "FALL_DETECTED",
                        "severity": "CRITICAL",
                        "confidence": confidence,
                        "confidence_level": confidence_level,
                        "person_id": tid,
                        "duration": round(horizontal_duration, 1),
                        "details": {
                            "description": f"{confidence_level.capitalize()} fall detected (confidence {int(confidence*100)}%)",
                            "aspect_ratio": aspect_ratio,
                            "body_angle": body_angle,
                            "downward_speed": state["peak_down_vy"],
                            "sustained_floor_sec": round(horizontal_duration, 1)
                        }
                    }
        else:
            # Person stood back up or is upright
            state["horizontal_start"] = 0.0
            state["peak_down_vy"] = 0.0
            if person.activity_state == "POSSIBLE_FALL":
                person.activity_state = "NORMAL"

        return None

    def cleanup_old_tracks(self, active_track_ids: List[int]):
        """Remove state for tracks that have exited the view."""
        current_ids = set(active_track_ids)
        for tid in list(self.person_states.keys()):
            if tid not in current_ids:
                del self.person_states[tid]
