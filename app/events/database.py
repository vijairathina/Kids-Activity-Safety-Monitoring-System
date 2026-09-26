"""
SQLite Database manager for events, snapshots, recordings, and configuration persistence.
Thread-safe with connection pooling / per-call context managers.
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "kids_safety.db"


def get_db_connection() -> sqlite3.Connection:
    """Create a sqlite3 connection with dict-like row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables with indexes."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                confidence REAL NOT NULL,
                confidence_level TEXT NOT NULL,
                person_id INTEGER,
                location_zone TEXT,
                snapshot_path TEXT,
                video_clip_path TEXT,
                audio_clip_path TEXT,
                duration REAL DEFAULT 0.0,
                acknowledged INTEGER DEFAULT 0,
                details_json TEXT
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                component TEXT NOT NULL,
                message TEXT NOT NULL
            )
        """)
        conn.commit()


def add_event(event: Dict[str, Any]) -> int:
    """Insert a new event record and return its row ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events (
                timestamp, camera_id, event_type, severity, confidence,
                confidence_level, person_id, location_zone, snapshot_path,
                video_clip_path, audio_clip_path, duration, acknowledged, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.get("timestamp", datetime.now().isoformat()),
            event.get("camera_id", "cam_main"),
            event.get("event_type", "UNKNOWN"),
            event.get("severity", "INFO"),
            float(event.get("confidence", 0.0)),
            event.get("confidence_level", "POSSIBLE"),
            event.get("person_id"),
            event.get("location_zone", ""),
            event.get("snapshot_path", ""),
            event.get("video_clip_path", ""),
            event.get("audio_clip_path", ""),
            float(event.get("duration", 0.0)),
            1 if event.get("acknowledged") else 0,
            json.dumps(event.get("details", {}))
        ))
        conn.commit()
        return cursor.lastrowid


def get_events(
    filter_type: Optional[str] = None,
    severity: Optional[str] = None,
    time_range: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Query events with multiple filter conditions."""
    query = "SELECT * FROM events WHERE 1=1"
    params: List[Any] = []

    if filter_type and filter_type.upper() != "ALL":
        query += " AND event_type = ?"
        params.append(filter_type.upper())

    if severity and severity.upper() != "ALL":
        query += " AND severity = ?"
        params.append(severity.upper())

    if acknowledged is not None:
        query += " AND acknowledged = ?"
        params.append(1 if acknowledged else 0)

    now = datetime.now()
    if time_range == "today":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        query += " AND timestamp >= ?"
        params.append(start_of_day)
    elif time_range == "yesterday":
        yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        query += " AND timestamp >= ? AND timestamp < ?"
        params.extend([yesterday_start, today_start])
    elif time_range == "7d":
        seven_days_ago = (now - timedelta(days=7)).isoformat()
        query += " AND timestamp >= ?"
        params.append(seven_days_ago)
    elif time_range == "30d":
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        query += " AND timestamp >= ?"
        params.append(thirty_days_ago)

    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("details_json"):
                try:
                    d["details"] = json.loads(d["details_json"])
                except Exception:
                    d["details"] = {}
            result.append(d)
        return result


def acknowledge_event(event_id: int) -> bool:
    """Mark an event as acknowledged."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE events SET acknowledged = 1 WHERE id = ?", (event_id,))
        conn.commit()
        return cursor.rowcount > 0


def delete_event(event_id: int) -> bool:
    """Delete an event and its associated media files."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT snapshot_path, video_clip_path, audio_clip_path FROM events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        if row:
            for path_key in ["snapshot_path", "video_clip_path", "audio_clip_path"]:
                p = row[path_key]
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        cursor.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
        return cursor.rowcount > 0


def check_storage_status(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Check disk storage usage and threshold.
    Returns storage metrics and can_store boolean flag.
    """
    import shutil
    from app.config.settings import load_config
    cfg = load_config()
    rec_cfg = cfg.get("recording", {})
    max_used_pct = float(rec_cfg.get("max_disk_usage_percent", 70.0))

    check_path = path or str(BASE_DIR)
    try:
        total, used, free = shutil.disk_usage(check_path)
        used_pct = (used / total) * 100.0 if total > 0 else 0.0
        free_pct = (free / total) * 100.0 if total > 0 else 0.0
        return {
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "used_percent": round(used_pct, 1),
            "free_percent": round(free_pct, 1),
            "max_allowed_percent": round(max_used_pct, 1),
            "can_store": used_pct < max_used_pct
        }
    except Exception as e:
        return {
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "used_percent": 0.0,
            "free_percent": 100.0,
            "max_allowed_percent": round(max_used_pct, 1),
            "can_store": True,
            "error": str(e)
        }


def purge_old_events(
    retention_hours: Optional[float] = None,
    retention_days: Optional[float] = None
) -> int:
    """
    Purge events and media older than specified retention period.
    Defaults to recording.retention_hours (24 hours) from config.yaml.
    """
    if retention_hours is None:
        from app.config.settings import load_config
        cfg = load_config()
        rec_cfg = cfg.get("recording", {})
        if "retention_hours" in rec_cfg:
            retention_hours = float(rec_cfg.get("retention_hours", 24))
        elif retention_days is not None:
            retention_hours = float(retention_days) * 24.0
        elif "retention_days" in rec_cfg:
            retention_hours = float(rec_cfg.get("retention_days", 1)) * 24.0
        else:
            retention_hours = 24.0

    cutoff = (datetime.now() - timedelta(hours=retention_hours)).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, snapshot_path, video_clip_path, audio_clip_path FROM events WHERE timestamp < ?", (cutoff,))
        rows = cursor.fetchall()
        deleted_count = 0
        for row in rows:
            for path_key in ["snapshot_path", "video_clip_path", "audio_clip_path"]:
                p = row[path_key]
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            cursor.execute("DELETE FROM events WHERE id = ?", (row["id"],))
            deleted_count += 1
        conn.commit()
        return deleted_count


def get_event_stats() -> Dict[str, Any]:
    """Retrieve statistical summary for dashboard."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        total = cursor.fetchone()[0]

        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cursor.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ?", (start_of_day,))
        today_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM events WHERE severity = 'CRITICAL' AND acknowledged = 0")
        unack_critical = cursor.fetchone()[0]

        cursor.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type")
        by_type = dict(cursor.fetchall())

        cursor.execute("SELECT severity, COUNT(*) FROM events GROUP BY severity")
        by_severity = dict(cursor.fetchall())

        return {
            "total_events": total,
            "today_events": today_count,
            "unacknowledged_critical": unack_critical,
            "by_type": by_type,
            "by_severity": by_severity
        }


def log_system_message(level: str, component: str, message: str):
    """Log an operational message to SQLite."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO system_logs (timestamp, level, component, message)
                VALUES (?, ?, ?, ?)
            """, (datetime.now().isoformat(), level, component, message))
            conn.commit()
    except Exception:
        pass


def get_recent_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent system messages."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]
