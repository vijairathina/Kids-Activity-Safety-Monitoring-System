"""
Unit and Integration Tests for Fall Detector.
Validates multi-signal posture detection and temporal confirmation.
"""

import time
import unittest
from app.ai.tracker import TrackedPerson
from app.safety.fall import FallDetector


class TestFallDetector(unittest.TestCase):

    def setUp(self):
        self.detector = FallDetector()
        self.frame_shape = (480, 640)

    def test_standing_person_no_fall(self):
        """A normal upright person should never trigger a fall."""
        person = TrackedPerson(track_id=1, box=[200, 100, 260, 300], confidence=0.9)
        pose_data = {
            "aspect_ratio": 0.3,
            "body_angle": 85.0
        }
        res = self.detector.analyze(person, pose_data, self.frame_shape)
        self.assertIsNone(res)

    def test_instant_horizontal_requires_sustained_dwell(self):
        """A single frame of horizontal posture should not immediately trigger without dwell."""
        person = TrackedPerson(track_id=2, box=[200, 350, 380, 420], confidence=0.9)
        pose_data = {
            "aspect_ratio": 2.5,  # Wide box
            "body_angle": 15.0   # Horizontal
        }
        # First frame
        res1 = self.detector.analyze(person, pose_data, self.frame_shape)
        self.assertIsNone(res1, "Should not trigger on the very first frame without temporal confirmation")

    def test_sustained_fall_triggers_event(self):
        """Sustained horizontal posture on floor confirms fall event with calibrated confidence."""
        person = TrackedPerson(track_id=3, box=[200, 360, 390, 430], confidence=0.9)
        pose_data = {
            "aspect_ratio": 2.7,
            "body_angle": 12.0
        }
        # Simulate downward drop velocity spike
        person.vy = 60.0

        # Frame 1: registers start
        self.detector.analyze(person, pose_data, self.frame_shape)

        # Fast forward state start time to simulate 2.5s on floor
        self.detector.person_states[3]["horizontal_start"] = time.time() - 2.5

        # Frame 2: should confirm fall
        res = self.detector.analyze(person, pose_data, self.frame_shape)
        self.assertIsNotNone(res)
        self.assertEqual(res["event_type"], "FALL_DETECTED")
        self.assertEqual(res["severity"], "CRITICAL")
        self.assertIn(res["confidence_level"], ["POSSIBLE", "LIKELY"])
        self.assertGreaterEqual(res["confidence"], 0.6)


if __name__ == "__main__":
    unittest.main()
