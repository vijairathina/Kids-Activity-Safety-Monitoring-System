"""
Unit Tests for Database, Config Settings, and Central Engine.
"""

import os
import unittest
from app.config.settings import load_config, mask_sensitive_url
from app.events.database import init_db, add_event, get_events, get_event_stats


class TestEngineAndDatabase(unittest.TestCase):

    def setUp(self):
        init_db()

    def test_mask_sensitive_url(self):
        url = "rtsp://admin:superSecret123@192.168.1.100:554/stream"
        masked = mask_sensitive_url(url)
        self.assertNotIn("superSecret123", masked)
        self.assertIn("admin:******@192.168.1.100", masked)

    def test_database_event_lifecycle(self):
        ev = {
            "camera_id": "cam_test",
            "event_type": "FALL_DETECTED",
            "severity": "CRITICAL",
            "confidence": 0.89,
            "confidence_level": "LIKELY",
            "person_id": 5,
            "location_zone": "Living Room",
            "duration": 2.5,
            "acknowledged": 0,
            "details": {"test": "data"}
        }
        ev_id = add_event(ev)
        self.assertGreater(ev_id, 0)

        events = get_events(filter_type="FALL_DETECTED", limit=10)
        self.assertTrue(any(e["id"] == ev_id for e in events))

        stats = get_event_stats()
        self.assertGreaterEqual(stats["total_events"], 1)


if __name__ == "__main__":
    unittest.main()
