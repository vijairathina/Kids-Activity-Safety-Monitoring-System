"""
Unit Tests for 24-Hour Event Retention and 70% Storage Threshold Safeguards.
"""

import os
import time
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
import unittest

from app.events.database import (
    get_db_connection,
    init_db,
    add_event,
    purge_old_events,
    check_storage_status
)
from app.events.recorder import EventRecorder


class TestStorageRetention(unittest.TestCase):

    def setUp(self):
        init_db()

    def test_24_hour_event_purge(self):
        """Events older than 24 hours must be purged, while recent events (<24h) remain."""
        now = datetime.now()
        old_time = (now - timedelta(hours=26)).isoformat()
        recent_time = (now - timedelta(hours=2)).isoformat()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Insert 26-hour-old event
            cursor.execute("""
                INSERT INTO events (event_type, severity, confidence, confidence_level, camera_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("FALL_DETECTED", "CRITICAL", 0.95, "HIGH", "cam1", old_time))
            old_id = cursor.lastrowid

            # Insert 2-hour-old event
            cursor.execute("""
                INSERT INTO events (event_type, severity, confidence, confidence_level, camera_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("FALL_DETECTED", "CRITICAL", 0.95, "HIGH", "cam1", recent_time))
            recent_id = cursor.lastrowid
            conn.commit()

        # Purge using 24 hours retention
        deleted = purge_old_events(retention_hours=24.0)
        self.assertGreaterEqual(deleted, 1)

        # Verify old event is deleted, recent event exists
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM events WHERE id = ?", (old_id,))
            self.assertIsNone(cursor.fetchone())

            cursor.execute("SELECT id FROM events WHERE id = ?", (recent_id,))
            self.assertIsNotNone(cursor.fetchone())

            # Clean up test event
            cursor.execute("DELETE FROM events WHERE id = ?", (recent_id,))
            conn.commit()

    def test_check_storage_status(self):
        """Storage status returns required disk metrics and can_store flag."""
        status = check_storage_status()
        self.assertIn("total_gb", status)
        self.assertIn("used_percent", status)
        self.assertIn("max_allowed_percent", status)
        self.assertIn("can_store", status)
        self.assertEqual(status["max_allowed_percent"], 70.0)
        self.assertIsInstance(status["can_store"], bool)

    def test_media_retention_prune(self):
        """EventRecorder prunes files older than 24 hours and preserves newer files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            old_file = tmp_path / "old_recording.mp4"
            recent_file = tmp_path / "recent_recording.mp4"

            old_file.write_text("dummy old data")
            recent_file.write_text("dummy recent data")

            # Set old_file mtime to 25 hours ago
            past_mtime = time.time() - (25 * 3600.0)
            os.utime(str(old_file), (past_mtime, past_mtime))

            # Prune files older than 24 hours
            EventRecorder.prune_media_older_than(tmp_path, retention_hours=24.0)

            self.assertFalse(old_file.exists(), "File older than 24h should have been deleted")
            self.assertTrue(recent_file.exists(), "File newer than 24h should be retained")


if __name__ == "__main__":
    unittest.main()
