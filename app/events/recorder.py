"""
Event Video and Snapshot Recorder.
Maintains an in-memory ring buffer (10-30s pre-event buffer).
Upon trigger, saves pre-event + event + post-event video clip in background.
Honors privacy mode and storage quota.
"""

import os
import time
import threading
from collections import deque
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
import cv2
import numpy as np
from app.config.settings import load_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class EventRecorder:
    """Threaded event video clip and snapshot recorder with ring buffer."""

    def __init__(self, fps: int = 15, max_buffer_seconds: int = 20):
        self.fps = fps
        self.buffer_size = fps * max_buffer_seconds
        self.ring_buffer = deque(maxlen=self.buffer_size)
        self._lock = threading.Lock()

        # Ongoing post-event recording queues: list of active recording jobs
        self.active_jobs: List[Dict[str, Any]] = []

    def push_frame(self, frame: np.ndarray):
        """Append frame to ring buffer."""
        if frame is None:
            return

        with self._lock:
            # Store timestamp and copy of frame
            self.ring_buffer.append((time.time(), frame.copy()))

            # Append to any active post-event jobs
            now = time.time()
            remaining_jobs = []
            for job in self.active_jobs:
                job["frames"].append(frame.copy())
                if now >= job["end_time"]:
                    # Post-event duration complete; finalize in background thread
                    t = threading.Thread(
                        target=self._finalize_recording,
                        args=(job["frames"], job["out_path"], self.fps),
                        daemon=True
                    )
                    t.start()
                else:
                    remaining_jobs.append(job)
            self.active_jobs = remaining_jobs

    def record_event(
        self,
        event_id: int,
        event_type: str,
        current_frame: np.ndarray
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Triggered when a safety event occurs.
        Saves snapshot immediately and schedules video clip compilation.
        Returns: (snapshot_path, video_clip_path)
        """
        cfg = load_config()
        if cfg.get("privacy", {}).get("privacy_mode", False):
            # In Privacy Mode, disable video and snapshot disk storage
            return None, None

        rec_cfg = cfg.get("recording", {})
        if not rec_cfg.get("enabled", True):
            return None, None

        snaps_dir = BASE_DIR / rec_cfg.get("snapshots_path", "data/snapshots")
        recs_dir = BASE_DIR / rec_cfg.get("recordings_path", "data/recordings")
        snaps_dir.mkdir(parents=True, exist_ok=True)
        recs_dir.mkdir(parents=True, exist_ok=True)

        self._enforce_storage_quota(recs_dir, float(rec_cfg.get("max_storage_mb", 2048)))

        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        snap_filename = f"{timestamp_str}_{event_type}_{event_id}.jpg"
        snap_path = str(snaps_dir / snap_filename)

        # 1. Save Snapshot immediately
        try:
            cv2.imwrite(snap_path, current_frame)
        except Exception as e:
            print(f"[Recorder] Snapshot write failed: {e}")
            snap_path = None

        # 2. Extract Pre-event frames from ring buffer
        pre_sec = float(rec_cfg.get("pre_event_sec", 5))
        post_sec = float(rec_cfg.get("post_event_sec", 5))
        now = time.time()
        cutoff_time = now - pre_sec

        with self._lock:
            pre_frames = [f for (t, f) in self.ring_buffer if t >= cutoff_time]
            if not pre_frames:
                pre_frames = [current_frame.copy()]

            video_filename = f"{timestamp_str}_{event_type}_{event_id}.mp4"
            video_path = str(recs_dir / video_filename)

            # Register active recording job to accumulate post-event frames
            job = {
                "out_path": video_path,
                "end_time": now + post_sec,
                "frames": list(pre_frames)
            }
            self.active_jobs.append(job)

        return snap_path, video_path

    @staticmethod
    def _finalize_recording(frames: List[np.ndarray], out_path: str, fps: int):
        """Encode buffered frames to MP4 in worker thread."""
        if not frames:
            return
        try:
            h, w = frames[0].shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(out_path, fourcc, float(fps), (w, h))
            for f in frames:
                # Resize if frame dimensions vary
                if f.shape[0] != h or f.shape[1] != w:
                    f = cv2.resize(f, (w, h))
                writer.write(f)
            writer.release()
            print(f"[Recorder] Event video saved: {out_path} ({len(frames)} frames)")
        except Exception as e:
            print(f"[Recorder] Video encoding failed for {out_path}: {e}")

    @staticmethod
    def _enforce_storage_quota(directory: Path, max_mb: float):
        """Purge oldest files if folder size exceeds storage quota."""
        try:
            files = list(directory.glob("*.*"))
            total_bytes = sum(f.stat().st_size for f in files)
            if (total_bytes / (1024 * 1024)) > max_mb:
                # Sort oldest first
                files.sort(key=lambda x: x.stat().st_mtime)
                while files and (total_bytes / (1024 * 1024)) > (max_mb * 0.85):
                    oldest = files.pop(0)
                    total_bytes -= oldest.stat().st_size
                    try:
                        oldest.unlink()
                    except OSError:
                        pass
        except Exception:
            pass
