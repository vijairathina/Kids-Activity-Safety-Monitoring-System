"""
Pose Estimator: Extracts key anatomical landmarks (Head, Shoulders, Wrists, Hips, Ankles),
computes body inclination angle, aspect ratio, and wrist positions for safety checks.
Designed for on-demand execution to preserve Raspberry Pi CPU.
"""

import math
import numpy as np
from typing import Dict, Any, List, Optional, Tuple


class PoseEstimator:
    """Lightweight pose estimator with conditional on-demand inference."""

    def __init__(self):
        self.backend = "heuristic"
        self._mp_pose = None
        self._init_backend()

    def _init_backend(self):
        """Attempt to load MediaPipe Pose if available, else use Heuristic."""
        try:
            import mediapipe as mp
            self._mp_pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=0,  # 0 is fastest for edge devices
                min_detection_confidence=0.45,
                min_tracking_confidence=0.45
            )
            self.backend = "mediapipe"
            print("[Pose] MediaPipe Pose initialized in low-complexity edge mode.")
        except Exception:
            self.backend = "heuristic"
            print("[Pose] MediaPipe not available. Using Edge-Heuristic Pose Estimator.")

    def estimate_person_pose(self, frame: np.ndarray, box: List[int]) -> Dict[str, Any]:
        """
        Estimate 2D keypoints and postural features for a person crop.
        box = [x1, y1, x2, y2]
        """
        x1, y1, x2, y2 = box
        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        aspect_ratio = round(bw / float(bh), 2)  # Width / Height

        h_frame, w_frame = frame.shape[:2]

        # If MediaPipe is active and person box is sufficiently large
        if self.backend == "mediapipe" and self._mp_pose is not None and bh > 40 and bw > 30:
            try:
                crop = frame[max(0, y1):min(h_frame, y2), max(0, x1):min(w_frame, x2)]
                if crop.size > 0:
                    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                    results = self._mp_pose.process(rgb)
                    if results.pose_landmarks:
                        lms = results.pose_landmarks.landmark
                        # Key landmarks (11=l_shoulder, 12=r_shoulder, 15=l_wrist, 16=r_wrist, 23=l_hip, 24=r_hip)
                        def pt(idx):
                            lm = lms[idx]
                            return [int(x1 + lm.x * bw), int(y1 + lm.y * bh), round(lm.visibility, 2)]

                        nose = pt(0)
                        l_sh, r_sh = pt(11), pt(12)
                        l_wr, r_wr = pt(15), pt(16)
                        l_hip, r_hip = pt(23), pt(24)
                        l_ank, r_ank = pt(27), pt(28)

                        # Body angle from mid-shoulder to mid-hip
                        sh_mid = [(l_sh[0] + r_sh[0]) / 2, (l_sh[1] + r_sh[1]) / 2]
                        hip_mid = [(l_hip[0] + r_hip[0]) / 2, (l_hip[1] + r_hip[1]) / 2]
                        dx = hip_mid[0] - sh_mid[0]
                        dy = hip_mid[1] - sh_mid[1]
                        angle = abs(math.degrees(math.atan2(dy, dx)))  # 90 = vertical, 0/180 = horizontal

                        return {
                            "backend": "mediapipe",
                            "aspect_ratio": aspect_ratio,
                            "body_angle": round(angle, 1),
                            "keypoints": {
                                "nose": nose[:2],
                                "left_shoulder": l_sh[:2],
                                "right_shoulder": r_sh[:2],
                                "left_wrist": l_wr[:2],
                                "right_wrist": r_wr[:2],
                                "left_hip": l_hip[:2],
                                "right_hip": r_hip[:2],
                                "left_ankle": l_ank[:2],
                                "right_ankle": r_ank[:2]
                            }
                        }
            except Exception:
                pass

        # Heuristic Keypoint Calculation:
        # Analyzes bounding box geometry, horizontal vs vertical proportion
        cx = int(x1 + bw / 2)
        cy = int(y1 + bh / 2)

        if aspect_ratio >= 1.0:
            # Horizontal posture (lying or falling)
            # Body angle is low (approaching horizontal)
            body_angle = max(5.0, round(90.0 / (aspect_ratio * 1.8), 1))
            nose = [int(x1 + bw * 0.15), int(y1 + bh * 0.5)]
            l_sh = [int(x1 + bw * 0.3), int(y1 + bh * 0.35)]
            r_sh = [int(x1 + bw * 0.3), int(y1 + bh * 0.65)]
            l_wr = [int(x1 + bw * 0.2), int(y1 + bh * 0.2)]
            r_wr = [int(x1 + bw * 0.2), int(y1 + bh * 0.8)]
            l_hip = [int(x1 + bw * 0.65), int(y1 + bh * 0.4)]
            r_hip = [int(x1 + bw * 0.65), int(y1 + bh * 0.6)]
            l_ank = [int(x1 + bw * 0.9), int(y1 + bh * 0.4)]
            r_ank = [int(x1 + bw * 0.9), int(y1 + bh * 0.6)]
        else:
            # Upright or sitting posture
            # Standing angle: 75° - 90°
            body_angle = min(90.0, round(70.0 + (1.0 - min(1.0, aspect_ratio)) * 20.0, 1))
            nose = [cx, int(y1 + bh * 0.12)]
            l_sh = [int(x1 + bw * 0.25), int(y1 + bh * 0.25)]
            r_sh = [int(x1 + bw * 0.75), int(y1 + bh * 0.25)]
            l_wr = [int(x1 + bw * 0.15), int(y1 + bh * 0.55)]
            r_wr = [int(x1 + bw * 0.85), int(y1 + bh * 0.55)]
            l_hip = [int(x1 + bw * 0.35), int(y1 + bh * 0.60)]
            r_hip = [int(x1 + bw * 0.65), int(y1 + bh * 0.60)]
            l_ank = [int(x1 + bw * 0.35), int(y1 + bh * 0.95)]
            r_ank = [int(x1 + bw * 0.65), int(y1 + bh * 0.95)]

        return {
            "backend": "heuristic",
            "aspect_ratio": aspect_ratio,
            "body_angle": body_angle,
            "keypoints": {
                "nose": nose,
                "left_shoulder": l_sh,
                "right_shoulder": r_sh,
                "left_wrist": l_wr,
                "right_wrist": r_wr,
                "left_hip": l_hip,
                "right_hip": r_hip,
                "left_ankle": l_ank,
                "right_ankle": r_ank
            }
        }
