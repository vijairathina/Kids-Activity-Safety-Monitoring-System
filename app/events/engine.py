"""
Central Event and AI Inference Engine.
Orchestrates detection, tracking, on-demand pose estimation, safety rules,
event correlation, video/snapshot recording, and multi-channel alert dispatching.
"""

import time
import threading
import json
import cv2
import numpy as np
from datetime import datetime
from collections import deque
from typing import Dict, Any, List, Optional, Tuple

from app.config.settings import load_config
from app.events.database import add_event, log_system_message
from app.events.recorder import EventRecorder
from app.ai.detector import ObjectDetector
from app.ai.tracker import LightweightTracker, TrackedPerson
from app.ai.pose import PoseEstimator
from app.ai.activity import ActivityStateMachine
from app.ai.audio import AudioAnalyzer
from app.safety.fall import FallDetector
from app.safety.zones import ZoneManager
from app.safety.electrical import ElectricalSafetyDetector
from app.safety.conflict import ConflictDetector
from app.safety.anomaly import AnomalyDetector
from app.alerts.telegram import send_telegram_alert
from app.alerts.mqtt import MQTTManager
from app.alerts.homeassistant import send_homeassistant_webhook, send_generic_webhook
from app.alerts.gpio import GPIOBuzzer


class EventEngine:
    """Central processing pipeline running AI, safety heuristics, and alerting."""

    def __init__(self, camera_stream=None):
        self.camera_stream = camera_stream
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Core subsystems
        self.detector = ObjectDetector()
        self.tracker = LightweightTracker()
        self.pose_estimator = PoseEstimator()
        self.activity_sm = ActivityStateMachine()
        self.audio_analyzer = AudioAnalyzer()
        self.recorder = EventRecorder()

        # Safety rule modules
        self.fall_detector = FallDetector()
        self.zone_manager = ZoneManager()
        self.electrical_detector = ElectricalSafetyDetector()
        self.conflict_detector = ConflictDetector()
        self.anomaly_detector = AnomalyDetector()

        # Integrations
        self.mqtt_manager = MQTTManager()
        self.buzzer = GPIOBuzzer()

        # Runtime state
        self.active_tracks: List[TrackedPerson] = []
        self.active_detections: List[Dict[str, Any]] = []
        self.person_poses: Dict[int, Dict[str, Any]] = {}
        self.overall_safety_status = "NORMAL"  # "NORMAL", "WARNING", "CRITICAL"
        self.last_event: Optional[Dict[str, Any]] = None
        self.recent_events_cache = deque(maxlen=20)
        self.ai_fps = 0.0
        self.inference_latency_ms = 0.0

        # SSE Event Subscribers: list of queues
        self._sse_listeners: List[deque] = []

    def start(self):
        """Start AI worker thread and audio listener."""
        if self._running:
            return
        self._running = True
        self.audio_analyzer.start()
        self.mqtt_manager.start()
        self._thread = threading.Thread(target=self._engine_loop, daemon=True, name="AIEngineWorker")
        self._thread.start()
        print("[Engine] Event and AI Engine started successfully.")

    def stop(self):
        """Stop engine and clean up."""
        self._running = False
        self.audio_analyzer.stop()
        self.mqtt_manager.stop()
        self.buzzer.cleanup()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def subscribe_sse(self) -> deque:
        """Register a client queue for Server-Sent Events."""
        with self._lock:
            q = deque(maxlen=50)
            self._sse_listeners.append(q)
            return q

    def unsubscribe_sse(self, q: deque):
        """Unregister a client SSE queue."""
        with self._lock:
            if q in self._sse_listeners:
                self._sse_listeners.remove(q)

    def _broadcast_sse(self, event_data: Dict[str, Any]):
        """Push new event to all active SSE browser connections."""
        with self._lock:
            dead_listeners = []
            for q in self._sse_listeners:
                try:
                    q.append(event_data)
                except Exception:
                    dead_listeners.append(q)
            for d in dead_listeners:
                if d in self._sse_listeners:
                    self._sse_listeners.remove(d)

    def _engine_loop(self):
        """Main processing loop executing detection, safety rules, and alerts."""
        cfg = load_config()
        ai_cfg = cfg.get("ai", {})
        det_fps = max(1, int(ai_cfg.get("detection_fps", 6)))
        frame_interval = 1.0 / det_fps

        fps_counter = 0
        fps_timer = time.time()

        while self._running:
            loop_start = time.time()

            if not self.camera_stream:
                time.sleep(0.1)
                continue

            ret, frame = self.camera_stream.read()
            if not ret or frame is None:
                time.sleep(0.05)
                continue

            # Push raw frame to video recorder ring buffer
            self.recorder.push_frame(frame)

            # 1. Object Detection
            inf_start = time.time()
            all_dets = self.detector.detect(frame)
            self.inference_latency_ms = round((time.time() - inf_start) * 1000.0, 1)

            # Filter person detections for tracking and non-person objects for context
            person_dets = [d for d in all_dets if d["class_name"] == "person"]
            object_dets = [d for d in all_dets if d["class_name"] != "person"]

            # 2. Tracking
            tracks = self.tracker.update(person_dets)
            active_ids = [t.track_id for t in tracks]

            # 3. Audio Analysis Polling
            audio_ev = self.audio_analyzer.pop_event()

            # 4. Safety Heuristics Evaluation
            current_frame_events: List[Dict[str, Any]] = []
            poses_dict: Dict[int, Dict[str, Any]] = {}
            has_any_conflict = False

            # Evaluate multi-person physical conflict
            conflict_events = self.conflict_detector.analyze(tracks, audio_event=audio_ev)
            if conflict_events:
                has_any_conflict = True
                current_frame_events.extend(conflict_events)

            from app.camera.ptz import ptz_controller
            camera_is_moving = ptz_controller.is_camera_moving()

            # Evaluate per-person safety conditions
            for person in tracks:
                # On-demand pose estimation (preserves Raspberry Pi CPU)
                pose_data = self.pose_estimator.estimate_person_pose(frame, person.box)
                person.pose_data = pose_data
                poses_dict[person.track_id] = pose_data

                fall_ev = None
                # If 360-degree PTZ camera is rotating, suppress position-based false alarms
                if not camera_is_moving:
                    # Fall Detection
                    fall_ev = self.fall_detector.analyze(person, pose_data, frame.shape)
                    if fall_ev:
                        current_frame_events.append(fall_ev)

                    # Zone Intrusion / Safe Zone checks
                    zone_events = self.zone_manager.analyze(person)
                    current_frame_events.extend(zone_events)

                    # Electrical Hazard Proximity
                    elec_events = self.electrical_detector.analyze(person, pose_data)
                    current_frame_events.extend(elec_events)

                # Activity State Machine (Safety, Watching TV, Dancing, Playing, Reading, Writing)
                in_danger = bool(person.zone_id and "SAFE" not in person.zone_id.upper())
                is_fall = (fall_ev is not None)
                self.activity_sm.update_state(
                    person,
                    pose_data,
                    nearby_objects=object_dets,
                    has_conflict=has_any_conflict,
                    in_danger_zone=in_danger,
                    is_fall_detected=is_fall
                )

            # Anomaly and Night Mode detection (suppressed when camera rotating)
            if not camera_is_moving:
                anomaly_events = self.anomaly_detector.analyze(tracks)
                current_frame_events.extend(anomaly_events)

            # Standalone audio events (e.g. scream without visible person)
            if audio_ev and not any(e.get("event_type") == audio_ev.get("type") for e in current_frame_events):
                current_frame_events.append({
                    "event_type": audio_ev.get("type"),
                    "severity": audio_ev.get("severity", "WARNING"),
                    "confidence": audio_ev.get("confidence", 0.8),
                    "confidence_level": "LIKELY",
                    "person_id": None,
                    "location_zone": "Audio Monitor",
                    "duration": 0.0,
                    "details": {
                        "description": f"Audio anomaly detected: {audio_ev.get('type')}",
                        "rms": audio_ev.get("rms"),
                        "frequency": audio_ev.get("freq")
                    }
                })

            # Cleanup state for departed tracks
            self.fall_detector.cleanup_old_tracks(active_ids)
            self.zone_manager.cleanup_old_tracks(active_ids)
            self.electrical_detector.cleanup_old_tracks(active_ids)
            self.anomaly_detector.cleanup_old_tracks(active_ids)
            self.activity_sm.cleanup_old_tracks(active_ids)

            # 5. Process and Dispatch Confirmed Safety Events
            with self._lock:
                self.active_tracks = tracks
                self.active_detections = all_dets
                self.person_poses = poses_dict

                # Compute overall system safety status
                if any(e.get("severity") == "CRITICAL" for e in current_frame_events):
                    self.overall_safety_status = "CRITICAL"
                elif any(e.get("severity") == "WARNING" for e in current_frame_events):
                    self.overall_safety_status = "WARNING"
                elif not current_frame_events:
                    # Decay to normal if no critical/warning states
                    if self.overall_safety_status != "NORMAL":
                        self.overall_safety_status = "NORMAL"

            # Handle event triggers
            for event in current_frame_events:
                self._dispatch_event(event, frame)

            # Update MQTT state telemetry
            primary_activity = tracks[0].activity_state if tracks else "NORMAL"
            self.mqtt_manager.publish_state({
                "safety_status": self.overall_safety_status,
                "activity": primary_activity,
                "last_event": self.last_event.get("event_type") if self.last_event else "None",
                "person_count": len(tracks),
                "fall_detected": any(e.get("event_type") == "FALL_DETECTED" for e in current_frame_events),
                "danger_zone": any("DANGER" in e.get("event_type", "") for e in current_frame_events),
                "conflict_detected": any("CONFLICT" in e.get("event_type", "") for e in current_frame_events)
            })

            # Calculate AI inference FPS
            fps_counter += 1
            if time.time() - fps_timer >= 1.0:
                self.ai_fps = round(fps_counter / (time.time() - fps_timer), 1)
                fps_counter = 0
                fps_timer = time.time()

            elapsed = time.time() - loop_start
            sleep_needed = frame_interval - elapsed
            if sleep_needed > 0:
                time.sleep(sleep_needed)

    def _dispatch_event(self, event: Dict[str, Any], frame: np.ndarray):
        """Record media, persist event to SQLite, and fire alerts."""
        event["timestamp"] = datetime.now().isoformat()
        event_type = event.get("event_type", "UNKNOWN")
        severity = event.get("severity", "INFO")

        # 1. Trigger Video/Snapshot Recording
        snap_path, vid_path = self.recorder.record_event(
            event_id=int(time.time() * 1000) % 100000,
            event_type=event_type,
            current_frame=frame
        )
        event["snapshot_path"] = snap_path
        event["video_clip_path"] = vid_path

        # 2. Persist to SQLite Database
        db_id = add_event(event)
        event["id"] = db_id

        with self._lock:
            self.last_event = event
            self.recent_events_cache.append(event)

        # 3. Fire Hardware Buzzer for Critical events
        if severity == "CRITICAL":
            self.buzzer.trigger_buzzer(duration=0.8)

        # 4. Multi-channel Alerts
        send_telegram_alert(event, snapshot_path=snap_path)
        self.mqtt_manager.publish_event(event)
        send_homeassistant_webhook(event)
        send_generic_webhook(event)

        # 5. Broadcast live SSE notification to browser dashboard
        self._broadcast_sse({
            "type": "NEW_SAFETY_EVENT",
            "event": event
        })

    def render_overlay(self, frame: np.ndarray) -> np.ndarray:
        """
        Draw visual safety overlays onto frame:
        Bounding boxes, Track IDs, Activity badges, Danger zones, and Pose skeletons.
        """
        out = frame.copy()
        h, w = out.shape[:2]

        # 1. Draw Zones
        cfg = load_config()
        zones = cfg.get("zones", [])
        for z in zones:
            pts = z.get("points", [])
            zname = z.get("name", "")
            ztype = z.get("type", "CUSTOM")
            color_hex = z.get("color", "#ff3366")

            # Hex to BGR
            c_hex = color_hex.lstrip("#")
            bgr = tuple(int(c_hex[i:i+2], 16) for i in (4, 2, 0)) if len(c_hex) == 6 else (0, 0, 255)

            if len(pts) >= 3:
                np_pts = np.array(pts, np.int32).reshape((-1, 1, 2))
                # Semi-transparent fill
                overlay = out.copy()
                cv2.fillPoly(overlay, [np_pts], bgr)
                cv2.addWeighted(overlay, 0.22, out, 0.78, 0, out)
                cv2.polylines(out, [np_pts], isClosed=True, color=bgr, thickness=2)

                # Label
                lx, ly = pts[0][0], max(15, pts[0][1] - 8)
                cv2.putText(out, f"[{ztype}] {zname}", (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.45, bgr, 1, cv2.LINE_AA)

        # 2. Draw Tracked Persons and Objects
        with self._lock:
            tracks_copy = list(self.active_tracks)
            poses_copy = dict(self.person_poses)
            dets_copy = list(self.active_detections)

        # Draw detected objects (furniture, dangerous items)
        for det in dets_copy:
            if det["class_name"] != "person":
                x1, y1, x2, y2 = det["box"]
                c_name = det["class_name"]
                conf = int(det["confidence"] * 100)
                # Orange outline for hazardous objects (knife), cyan for furniture
                obj_color = (0, 69, 255) if c_name == "knife" else (200, 150, 50)
                cv2.rectangle(out, (x1, y1), (x2, y2), obj_color, 1)
                cv2.putText(out, f"{c_name} {conf}%", (x1, max(12, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, obj_color, 1)

        # Draw tracked persons
        for p in tracks_copy:
            x1, y1, x2, y2 = p.box
            tid = p.track_id
            state = p.activity_state

            # State-dependent bounding box and label colors (BGR)
            if state in ["POSSIBLE_FALL", "LYING"]:
                box_color = (50, 50, 255)    # Red / Critical
            elif state in ["DANGER_ZONE", "POSSIBLE_CONFLICT"]:
                box_color = (0, 165, 255)    # Amber / Orange
            elif state == "WATCHING_TV":
                box_color = (255, 220, 0)    # Cyan / Sky Blue
            elif state == "DANCING":
                box_color = (200, 50, 255)   # Magenta / Pink
            elif state == "PLAYING":
                box_color = (0, 230, 118)    # Emerald Green
            elif state == "READING":
                box_color = (255, 140, 50)   # Royal Blue / Azure
            elif state == "WRITING":
                box_color = (255, 100, 180)  # Violet / Purple
            elif state in ["RUNNING", "MOVING"]:
                box_color = (0, 215, 255)    # Yellow / Gold
            else:
                box_color = (0, 230, 100)    # Soft Green / Normal

            # Bounding box with rounded look
            cv2.rectangle(out, (x1, y1), (x2, y2), box_color, 2)

            # Header badge: Person ID & State
            label = f"#{tid} {state}"
            if p.speed > 8:
                label += f" ({int(p.speed)}px/s)"

            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(out, (x1, max(0, y1 - th - 8)), (x1 + tw + 10, y1), box_color, -1)
            cv2.putText(out, label, (x1 + 5, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

            # Draw Pose Keypoints & Skeleton if available
            pose = poses_copy.get(tid)
            if pose and "keypoints" in pose:
                kps = pose["keypoints"]
                kp_color = (255, 255, 255)
                # Draw joint points
                for kp_name, (kx, ky) in kps.items():
                    cv2.circle(out, (kx, ky), 3, kp_color, -1)

                # Skeleton bones
                bones = [
                    ("nose", "left_shoulder"), ("nose", "right_shoulder"),
                    ("left_shoulder", "right_shoulder"),
                    ("left_shoulder", "left_wrist"), ("right_shoulder", "right_wrist"),
                    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
                    ("left_hip", "right_hip"),
                    ("left_hip", "left_ankle"), ("right_hip", "right_ankle")
                ]
                for b1, b2 in bones:
                    if b1 in kps and b2 in kps:
                        p1 = tuple(kps[b1])
                        p2 = tuple(kps[b2])
                        cv2.line(out, p1, p2, (100, 255, 200), 1, cv2.LINE_AA)

            # Draw trajectory path
            if len(p.history) > 2:
                pts = [np.array([h[1], h[2]], dtype=np.int32) for h in p.history]
                for i in range(1, len(pts)):
                    cv2.line(out, tuple(pts[i - 1]), tuple(pts[i]), (200, 200, 200), 1)

        # 3. Overall HUD banner at top
        status_color = (0, 220, 80) if self.overall_safety_status == "NORMAL" else (
            (0, 160, 255) if self.overall_safety_status == "WARNING" else (50, 50, 255)
        )
        cv2.rectangle(out, (w - 180, 10), (w - 10, 36), status_color, -1)
        cv2.putText(out, f"STATUS: {self.overall_safety_status}", (w - 170, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2, cv2.LINE_AA)

        return out

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Aggregate telemetry for the main web interface."""
        with self._lock:
            tracks_info = []
            for t in self.active_tracks:
                tracks_info.append({
                    "id": t.track_id,
                    "state": t.activity_state,
                    "speed": t.speed,
                    "zone": t.zone_id or "Open Area",
                    "box": t.box
                })

            last_ev = self.last_event
            recent_list = list(self.recent_events_cache)

        return {
            "safety_status": self.overall_safety_status,
            "tracked_persons_count": len(tracks_info),
            "tracked_persons": tracks_info,
            "ai_fps": self.ai_fps,
            "inference_ms": self.inference_latency_ms,
            "backend": self.detector.backend,
            "last_event": last_ev,
            "recent_events": recent_list,
            "audio_metrics": self.audio_analyzer.get_metrics()
        }
