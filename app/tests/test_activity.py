"""
Unit Tests for Multi-Signal Child Activity Recognition:
- Watching TV
- Dancing
- Playing
- Reading
- Writing
"""

import time
import unittest
from app.ai.tracker import TrackedPerson
from app.ai.activity import ActivityStateMachine


class TestActivityRecognition(unittest.TestCase):

    def setUp(self):
        # Smoothing window 1 for deterministic unit assertions on state mapping
        self.sm = ActivityStateMachine(smoothing_window=1)

    def test_watching_tv_detection(self):
        person = TrackedPerson(track_id=1, box=[200, 200, 300, 350], confidence=0.92)
        person.speed = 1.2
        pose_data = {
            "aspect_ratio": 0.67,  # seated posture
            "body_angle": 80.0,
            "keypoints": {}
        }
        nearby_objects = [
            {"class_name": "tv", "box": [220, 50, 380, 150]}
        ]

        # Ensure stationary duration > 1.5s
        state = self.sm.update_state(person, pose_data, nearby_objects=nearby_objects)
        self.assertEqual(state, "WATCHING_TV")
        self.assertEqual(person.activity_state, "WATCHING_TV")

    def test_writing_detection(self):
        person = TrackedPerson(track_id=2, box=[150, 180, 250, 340], confidence=0.88)
        person.speed = 0.8
        # Person sitting at table with head tilted forward/down
        pose_data = {
            "aspect_ratio": 0.62,
            "body_angle": 75.0,
            "keypoints": {
                "nose": [200, 200],
                "left_shoulder": [180, 215],
                "right_shoulder": [220, 215],
            }
        }
        nearby_objects = [
            {"class_name": "table", "box": [140, 240, 280, 380]}
        ]

        state = self.sm.update_state(person, pose_data, nearby_objects=nearby_objects)
        self.assertEqual(state, "WRITING")

    def test_reading_detection(self):
        person = TrackedPerson(track_id=3, box=[100, 150, 190, 320], confidence=0.85)
        person.speed = 1.0
        pose_data = {
            "aspect_ratio": 0.60,
            "body_angle": 82.0,
            "keypoints": {}
        }
        nearby_objects = [
            {"class_name": "book", "box": [120, 240, 170, 280]}
        ]

        state = self.sm.update_state(person, pose_data, nearby_objects=nearby_objects)
        self.assertEqual(state, "READING")

    def test_dancing_detection(self):
        person = TrackedPerson(track_id=4, box=[250, 100, 340, 360], confidence=0.91)
        person.speed = 22.0
        # Upright posture with hands raised high above shoulders
        pose_data = {
            "aspect_ratio": 0.45,
            "body_angle": 88.0,
            "keypoints": {
                "left_shoulder": [270, 160],
                "right_shoulder": [320, 160],
                "left_wrist": [260, 140],  # higher than shoulder
                "right_wrist": [330, 135]
            }
        }

        # Dancing triggers after rhythmic cadence (dance_ticks >= 3)
        for _ in range(3):
            state = self.sm.update_state(person, pose_data)
        self.assertEqual(state, "DANCING")

    def test_playing_detection(self):
        # Scenario A: In designated Safe Play Area
        person_a = TrackedPerson(track_id=5, box=[300, 300, 420, 480], confidence=0.90)
        person_a.zone_id = "Safe Play Zone"
        person_a.speed = 6.0
        pose_data_a = {"aspect_ratio": 0.75, "body_angle": 70.0, "keypoints": {}}
        state_a = self.sm.update_state(person_a, pose_data_a)
        self.assertEqual(state_a, "PLAYING")

        # Scenario B: Floor play posture with active movement
        person_b = TrackedPerson(track_id=6, box=[100, 250, 220, 400], confidence=0.89)
        person_b.zone_id = "Living Room"
        person_b.speed = 12.0
        pose_data_b = {"aspect_ratio": 0.85, "body_angle": 60.0, "keypoints": {}}
        state_b = self.sm.update_state(person_b, pose_data_b)
        self.assertEqual(state_b, "PLAYING")

    def test_temporal_smoothing(self):
        # With window 5, brief 1-frame jitter does not flip smoothed activity
        sm = ActivityStateMachine(smoothing_window=5)
        person = TrackedPerson(track_id=7, box=[100, 100, 180, 300], confidence=0.90)
        person.speed = 1.0
        pose = {"aspect_ratio": 0.6, "body_angle": 80.0, "keypoints": {}}
        tv_objs = [{"class_name": "tv", "box": [110, 50, 200, 90]}]

        # Establish 4 frames of WATCHING_TV
        for _ in range(4):
            sm.update_state(person, pose, nearby_objects=tv_objs)

        # 1 frame with no TV should still smooth to WATCHING_TV
        jitter_state = sm.update_state(person, pose, nearby_objects=[])
        self.assertEqual(jitter_state, "WATCHING_TV")


if __name__ == "__main__":
    unittest.main()
