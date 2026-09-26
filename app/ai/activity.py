"""
Activity State Machine with Multi-Signal Activity Recognition and Temporal Smoothing.
Classifies activities:
- Safety: POSSIBLE_FALL, DANGER_ZONE, POSSIBLE_CONFLICT, LYING
- Creative / Routine: WATCHING_TV, DANCING, PLAYING, READING, WRITING
- Kinematic: RUNNING, MOVING, SITTING, NORMAL
"""

import math
import time
from collections import deque
from typing import Dict, Any, List, Optional
from app.ai.tracker import TrackedPerson


class ActivityStateMachine:
    """State machine governing person activity classifications with temporal smoothing."""

    def __init__(self, smoothing_window: int = 6):
        self.smoothing_window = smoothing_window
        # {track_id: deque of recent states}
        self.state_histories: Dict[int, deque] = {}
        # {track_id: {"dance_ticks": int, "stationary_start": float, "last_arm_high": float}}
        self.kinematic_stats: Dict[int, Dict[str, Any]] = {}

    def update_state(
        self,
        person: TrackedPerson,
        pose_data: Dict[str, Any],
        nearby_objects: Optional[List[Dict[str, Any]]] = None,
        has_conflict: bool = False,
        in_danger_zone: bool = False,
        is_fall_detected: bool = False
    ) -> str:
        """
        Evaluate raw state for person based on kinematics, pose keypoints,
        surrounding objects (TV, table, book, laptop), and zone residency.
        """
        tid = person.track_id
        now = time.time()

        if tid not in self.state_histories:
            self.state_histories[tid] = deque(maxlen=self.smoothing_window)
        if tid not in self.kinematic_stats:
            self.kinematic_stats[tid] = {
                "dance_ticks": 0,
                "stationary_start": now if person.speed < 5.0 else 0.0,
                "last_pos": (person.cx, person.cy),
                "rhythmic_swings": 0
            }

        stats = self.kinematic_stats[tid]
        aspect_ratio = pose_data.get("aspect_ratio", 0.5)
        body_angle = pose_data.get("body_angle", 90.0)
        speed = person.speed
        keypoints = pose_data.get("keypoints", {})

        # Track stationary residency
        if speed < 5.0:
            if stats["stationary_start"] == 0.0:
                stats["stationary_start"] = now
            stationary_duration = now - stats["stationary_start"]
        else:
            stats["stationary_start"] = 0.0
            stationary_duration = 0.0

        # Object proximity analysis
        objects = nearby_objects or []
        closest_obj_dist = {}
        for obj in objects:
            cname = obj.get("class_name", "")
            bx = obj.get("box", [0, 0, 0, 0])
            ocx = (bx[0] + bx[2]) / 2.0
            ocy = (bx[1] + bx[3]) / 2.0
            dist = math.hypot(person.cx - ocx, person.cy - ocy)
            if cname not in closest_obj_dist or dist < closest_obj_dist[cname]:
                closest_obj_dist[cname] = dist

        has_nearby_tv = closest_obj_dist.get("tv", 9999) < 320.0
        has_nearby_table = closest_obj_dist.get("table", 9999) < 130.0 or closest_obj_dist.get("dining table", 9999) < 130.0
        has_nearby_book = closest_obj_dist.get("book", 9999) < 140.0
        has_nearby_laptop = closest_obj_dist.get("laptop", 9999) < 130.0
        has_nearby_phone = closest_obj_dist.get("cell phone", 9999) < 100.0

        # Pose landmarks
        l_sh = keypoints.get("left_shoulder")
        r_sh = keypoints.get("right_shoulder")
        l_wr = keypoints.get("left_wrist")
        r_wr = keypoints.get("right_wrist")
        nose = keypoints.get("nose")

        # Hands raised / energetic arm gestures
        arm_high = False
        if l_wr and l_sh and r_wr and r_sh:
            sh_avg_y = (l_sh[1] + r_sh[1]) / 2.0
            if l_wr[1] <= (sh_avg_y + 15) or r_wr[1] <= (sh_avg_y + 15):
                arm_high = True

        # Hands close together in lap / reading posture
        hands_in_lap = False
        if l_wr and r_wr:
            wr_dist = math.hypot(l_wr[0] - r_wr[0], l_wr[1] - r_wr[1])
            if wr_dist < 45:
                hands_in_lap = True

        # Head tilted down towards hands (reading/writing posture)
        head_tilted_down = False
        if nose and l_sh and r_sh:
            sh_avg_y = (l_sh[1] + r_sh[1]) / 2.0
            if (sh_avg_y - nose[1]) < (person.box[3] - person.box[1]) * 0.12:
                head_tilted_down = True

        # Rhythmic cadence detection for dancing
        if speed > 10.0 and speed < 45.0 and (arm_high or abs(person.vy) > 12.0):
            stats["dance_ticks"] += 1
        else:
            stats["dance_ticks"] = max(0, stats["dance_ticks"] - 1)

        # ----------------------------------------------------------------------
        # Activity State Classification Hierarchy
        # ----------------------------------------------------------------------

        # Priority 1: Critical safety conditions
        if is_fall_detected or person.activity_state == "POSSIBLE_FALL":
            raw_state = "POSSIBLE_FALL"
        elif has_conflict:
            raw_state = "POSSIBLE_CONFLICT"
        elif in_danger_zone:
            raw_state = "DANGER_ZONE"
        elif aspect_ratio >= 1.15 or body_angle <= 32.0:
            raw_state = "LYING"

        # Priority 2: Engaged / Educational / Entertainment Activities
        elif has_nearby_tv and speed < 7.0 and (aspect_ratio > 0.5 or stationary_duration > 1.5):
            # Watching TV
            raw_state = "WATCHING_TV"

        elif (has_nearby_table and speed < 4.5 and (head_tilted_down or aspect_ratio >= 0.55)):
            # Writing at a table / desk
            raw_state = "WRITING"

        elif ((has_nearby_book or has_nearby_laptop or has_nearby_phone) and speed < 5.0) or (
            speed < 3.5 and hands_in_lap and head_tilted_down and aspect_ratio >= 0.55
        ):
            # Reading a book, screen, or tablet
            raw_state = "READING"

        elif (stats["dance_ticks"] >= 3 and body_angle >= 65.0 and aspect_ratio < 0.9):
            # Dancing (rhythmic cadence, arm elevation, joyful oscillation)
            raw_state = "DANCING"

        elif (
            ("SAFE" in person.zone_id.upper() or "PLAY" in person.zone_id.upper())
            or (aspect_ratio >= 0.65 and aspect_ratio <= 1.25 and speed >= 4.0 and speed <= 28.0)
        ):
            # Playing (active on floor, play mat, toy interaction)
            raw_state = "PLAYING"

        # Priority 3: General Kinematics
        elif speed > 35.0:
            raw_state = "RUNNING"
        elif speed > 10.0:
            raw_state = "MOVING"
        elif aspect_ratio > 0.65 and body_angle < 75.0:
            raw_state = "SITTING"
        else:
            raw_state = "NORMAL"

        # ----------------------------------------------------------------------
        # Temporal Hysteresis & Smoothing
        # ----------------------------------------------------------------------
        history = self.state_histories[tid]
        history.append(raw_state)

        # Most frequent state in recent smoothing window
        state_counts: Dict[str, int] = {}
        for s in history:
            state_counts[s] = state_counts.get(s, 0) + 1

        smoothed_state = max(state_counts.items(), key=lambda x: x[1])[0]

        # Critical safety states immediately override smoothing
        if raw_state in ["POSSIBLE_FALL", "DANGER_ZONE", "POSSIBLE_CONFLICT"]:
            smoothed_state = raw_state

        person.activity_state = smoothed_state
        return smoothed_state

    def cleanup_old_tracks(self, active_track_ids: List[int]):
        """Clear state queues and statistics for dead tracks."""
        curr = set(active_track_ids)
        for tid in list(self.state_histories.keys()):
            if tid not in curr:
                del self.state_histories[tid]
        for tid in list(self.kinematic_stats.keys()):
            if tid not in curr:
                del self.kinematic_stats[tid]
