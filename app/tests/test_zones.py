"""
Unit Tests for Zone Safety Manager and Point-in-Polygon Ray Casting.
"""

import time
import unittest
from app.ai.tracker import TrackedPerson
from app.safety.zones import ZoneManager, point_in_polygon


class TestZoneSafety(unittest.TestCase):

    def test_point_in_polygon(self):
        """Verify ray-casting algorithm for standard polygon."""
        poly = [[10, 10], [50, 10], [50, 50], [10, 50]]
        self.assertTrue(point_in_polygon((25, 25), poly))
        self.assertFalse(point_in_polygon((5, 5), poly))
        self.assertFalse(point_in_polygon((60, 25), poly))

    def test_danger_zone_entry(self):
        """Tracked person stepping into danger zone generates immediate entry warning."""
        zm = ZoneManager()
        # Explicit test zone independent of config.yaml
        zm.zones = [{
            "id": "zone_test_power",
            "name": "Test Power Outlet",
            "points": [[50, 320], [130, 320], [130, 420], [50, 420]],
            "alert_action": "immediate",
            "severity": "CRITICAL",
            "type": "POWER_ZONE"
        }]
        person = TrackedPerson(track_id=1, box=[60, 330, 100, 390], confidence=0.88)

        # Allow initial 0.5s dwell
        now = time.time()
        zm.dwell_states[(1, "zone_test_power")] = {"entry_time": now - 0.6, "last_alert": 0.0}

        events = zm.analyze(person)
        self.assertTrue(any("ENTERED" in e.get("event_type", "") for e in events))


if __name__ == "__main__":
    unittest.main()
