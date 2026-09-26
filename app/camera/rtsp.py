"""
Threaded RTSP / Camera Stream reader and Synthetic Stream Generator.
Provides low-latency frame extraction, auto-reconnect, FPS calculation,
and realistic test scenario simulation.
"""

import time
import math
import threading
import cv2
import numpy as np
from typing import Optional, Tuple, Dict, Any


class RTSPStream:
    """Threaded camera stream handler for RTSP, USB webcam, or Demo feed."""

    def __init__(
        self,
        source: str = "demo",
        width: int = 640,
        height: int = 480,
        target_fps: int = 15,
        reconnect_interval: float = 5.0
    ):
        self.source = source
        self.target_width = width
        self.target_height = height
        self.target_fps = target_fps
        self.reconnect_interval = reconnect_interval

        self.cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # State & metrics
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_timestamp: float = 0.0
        self.is_connected = False
        self.actual_fps = 0.0
        self.frame_count = 0
        self.dropped_frames = 0
        self.latency_ms = 0.0
        self.resolution = (width, height)
        self.last_error = ""

        # Synthetic demo simulation state
        self._demo_tick = 0
        self._demo_simulated_scenario = "normal"  # "normal", "fall", "electrical", "conflict"

    def start(self):
        """Start background capture thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="RTSPReader")
        self._thread.start()

    def stop(self):
        """Stop background capture."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._close_source()

    def set_source(self, new_source: str):
        """Change camera stream source dynamically."""
        with self._lock:
            self.source = new_source
            self._close_source()

    def set_demo_scenario(self, scenario: str):
        """Set simulation scenario for demo mode: 'normal', 'fall', 'electrical', 'conflict'."""
        self._demo_simulated_scenario = scenario

    def _open_source(self) -> bool:
        """Initialize video capture object or setup demo generator."""
        if self.source.lower() == "demo" or not self.source.strip():
            self.is_connected = True
            self.last_error = ""
            return True

        self._close_source()
        try:
            # Handle webcam integer index
            if self.source.isdigit():
                src = int(self.source)
                self.cap = cv2.VideoCapture(src)
            else:
                # RTSP stream setup
                # Use TCP transport for RTSP to prevent packet drop artifacts
                import os
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
                self.cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)

            if self.cap and self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if w > 0 and h > 0:
                    self.resolution = (w, h)
                self.is_connected = True
                self.last_error = ""
                return True
            else:
                self.is_connected = False
                if "rtsp://" in self.source.lower():
                    self.last_error = "RTSP Connection Failed (403 Forbidden or Offline). Check camera Safety Code/Password."
                    print(f"[Camera] ⚠️ Could not open RTSP stream. Check credentials or enable ONVIF in camera app.")
                else:
                    self.last_error = "Failed to open video source"
                return False
        except Exception as e:
            self.is_connected = False
            self.last_error = str(e)
            return False

    def _close_source(self):
        """Release capture device."""
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.is_connected = False

    def _capture_loop(self):
        """Dedicated loop continuously grabbing newest frames."""
        fps_counter = 0
        fps_timer = time.time()
        desired_sleep = 1.0 / max(1, self.target_fps)

        while self._running:
            loop_start = time.time()

            if self.source.lower() == "demo" or not self.source.strip():
                # Generate synthetic demo frame
                frame = self._generate_demo_frame()
                with self._lock:
                    self.latest_frame = frame
                    self.latest_timestamp = time.time()
                    self.is_connected = True
                    self.frame_count += 1
                fps_counter += 1
            else:
                if not self.is_connected or self.cap is None or not self.cap.isOpened():
                    opened = self._open_source()
                    if not opened:
                        time.sleep(self.reconnect_interval)
                        continue

                try:
                    grab_start = time.time()
                    ret, frame = self.cap.read()
                    grab_time = (time.time() - grab_start) * 1000.0
                    self.latency_ms = round(grab_time, 1)

                    if ret and frame is not None:
                        with self._lock:
                            self.latest_frame = frame
                            self.latest_timestamp = time.time()
                            self.resolution = (frame.shape[1], frame.shape[0])
                            self.frame_count += 1
                        fps_counter += 1
                    else:
                        self.is_connected = False
                        self.dropped_frames += 1
                        self._close_source()
                        time.sleep(self.reconnect_interval)
                except Exception as e:
                    self.is_connected = False
                    self.last_error = str(e)
                    self._close_source()
                    time.sleep(self.reconnect_interval)

            # Update FPS every 1.0 second
            if time.time() - fps_timer >= 1.0:
                self.actual_fps = round(fps_counter / (time.time() - fps_timer), 1)
                fps_counter = 0
                fps_timer = time.time()

            # Rate limit for target FPS
            elapsed = time.time() - loop_start
            sleep_time = desired_sleep - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Return the latest available frame without blocking."""
        with self._lock:
            if self.latest_frame is not None:
                return True, self.latest_frame.copy()
            return False, None

    def get_status(self) -> Dict[str, Any]:
        """Return current status and metrics."""
        return {
            "connected": self.is_connected,
            "source": self.source,
            "fps": self.actual_fps,
            "latency_ms": self.latency_ms,
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
            "frame_count": self.frame_count,
            "dropped_frames": self.dropped_frames,
            "last_error": self.last_error,
            "demo_scenario": self._demo_simulated_scenario if self.source == "demo" else "live"
        }

    def _generate_demo_frame(self) -> np.ndarray:
        """
        Generate a synthetic living room frame with interactive elements
        and simulated child actor for testing detection, pose, fall, and zones.
        """
        w, h = self.target_width, self.target_height
        img = np.zeros((h, w, 3), dtype=np.uint8)

        self._demo_tick += 1
        t = self._demo_tick * 0.05
        scenario = self._demo_simulated_scenario

        # Background: Modern living room interior
        # Wall (upper half)
        img[:int(h * 0.65), :] = [45, 40, 48]
        # Floor (wooden parquet tone)
        img[int(h * 0.65):, :] = [30, 45, 65]
        # Baseboard separator
        cv2.line(img, (0, int(h * 0.65)), (w, int(h * 0.65)), (80, 90, 110), 3)

        # Background furniture
        # Sofa / Couch (Left-Center)
        cv2.rectangle(img, (140, int(h * 0.45)), (340, int(h * 0.66)), (75, 55, 45), -1)
        cv2.rectangle(img, (140, int(h * 0.45)), (340, int(h * 0.66)), (95, 75, 65), 2)
        cv2.putText(img, "Sofa", (210, int(h * 0.55)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)

        # Wall Power Outlet (X: 60-120, Y: 330-410)
        cv2.rectangle(img, (70, 340), (110, 390), (220, 220, 230), -1)
        cv2.rectangle(img, (70, 340), (110, 390), (120, 120, 130), 2)
        cv2.circle(img, (83, 365), 4, (40, 40, 40), -1)
        cv2.circle(img, (97, 365), 4, (40, 40, 40), -1)
        cv2.putText(img, "POWER", (65, 335), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 100, 255), 1)

        # Staircase zone representation (Right side)
        for i in range(5):
            sx = int(480 + i * 25)
            sy = int(180 + i * 45)
            cv2.rectangle(img, (sx, sy), (w - 20, sy + 30), (60, 60, 80), -1)
            cv2.rectangle(img, (sx, sy), (w - 20, sy + 30), (90, 90, 110), 1)
        cv2.putText(img, "STAIRS", (510, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 180, 100), 1)

        # Play mat area
        cv2.rectangle(img, (200, 280), (410, 440), (50, 80, 50), -1)
        cv2.rectangle(img, (200, 280), (410, 440), (70, 120, 70), 1)
        cv2.putText(img, "PLAY AREA", (260, 360), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 180, 100), 1)

        # TV Screen on Wall (X: 370-490, Y: 70-150)
        cv2.rectangle(img, (370, 70), (490, 150), (20, 20, 25), -1)
        cv2.rectangle(img, (370, 70), (490, 150), (80, 80, 90), 2)
        if scenario == "watching_tv":
            # Animated flickering TV broadcast
            tv_glow = int(140 + math.sin(t * 10) * 35)
            cv2.rectangle(img, (374, 74), (486, 146), (tv_glow, tv_glow - 20, 255), -1)
            cv2.putText(img, "CARTOON TV", (385, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (20, 20, 40), 1)
        else:
            cv2.putText(img, "TV", (420, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 130), 1)

        # Position of child actor
        if scenario == "fall":
            # Scenario: Child walks, trips, falls, and stays on floor
            fall_cycle = (self._demo_tick % 180) / 30.0
            if fall_cycle < 2.0:
                px = int(250 + math.sin(fall_cycle * 2) * 30)
                py = 320
                actor_state = "walking"
            elif fall_cycle < 2.8:
                progress = (fall_cycle - 2.0) / 0.8
                px = 280 + int(progress * 40)
                py = int(320 + progress * 60)
                actor_state = "falling"
            else:
                px = 320
                py = 390
                actor_state = "fallen_floor"

        elif scenario == "electrical":
            # Scenario: Child walks directly to wall socket and reaches hand
            elec_cycle = (self._demo_tick % 160) / 30.0
            if elec_cycle < 2.5:
                progress = elec_cycle / 2.5
                px = int(260 - progress * 170)
                py = int(350 + progress * 20)
                actor_state = "approaching_outlet"
            else:
                px = 90
                py = 370
                actor_state = "touching_outlet"

        elif scenario == "conflict":
            # Scenario: Two children close together with rapid movement
            px = int(280 + math.sin(t * 8) * 15)
            py = 350
            actor_state = "conflict_p1"
            p2_x = px + int(35 + math.sin(t * 12) * 12)
            p2_y = py
            self._draw_actor(img, p2_x, p2_y, state="conflict_p2", shirt_color=(220, 80, 80))

        elif scenario == "watching_tv":
            # Scenario: Seated on sofa facing TV screen
            px = 240
            py = 340
            actor_state = "watching_tv"

        elif scenario == "dancing":
            # Scenario: Energetic rhythmic dance in room center with arms raised
            px = int(310 + math.sin(t * 4) * 20)
            py = int(340 + math.cos(t * 6) * 10)
            actor_state = "dancing"
            # Draw floating musical notes
            note_x = int(px + 30 + math.sin(t * 3) * 10)
            note_y = int(py - 70 - (self._demo_tick % 40) * 0.8)
            cv2.putText(img, "~*", (note_x, note_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 120, 200), 1)

        elif scenario == "reading":
            # Scenario: Seated on floor/couch holding a book with head tilted
            px = 280
            py = 350
            actor_state = "reading"
            # Draw open book in hands
            cv2.rectangle(img, (px - 14, py - 32), (px + 14, py - 18), (240, 240, 240), -1)
            cv2.rectangle(img, (px - 14, py - 32), (px + 14, py - 18), (50, 80, 200), 1)
            cv2.line(img, (px, py - 32), (px, py - 18), (100, 100, 100), 1)

        elif scenario == "writing":
            # Scenario: Seated at small desk writing with pen
            px = 310
            py = 345
            actor_state = "writing"
            # Draw study desk
            cv2.rectangle(img, (280, 330), (370, 375), (100, 70, 50), -1)
            cv2.rectangle(img, (280, 330), (370, 375), (130, 95, 75), 2)
            cv2.putText(img, "Desk", (305, 360), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            # Paper pad
            cv2.rectangle(img, (300, 325), (330, 340), (250, 250, 250), -1)

        elif scenario == "playing":
            # Scenario: On play mat with colorful toy blocks
            px = int(270 + math.sin(t * 1.5) * 25)
            py = 370
            actor_state = "playing"
            # Toy blocks
            cv2.rectangle(img, (230, 380), (245, 395), (0, 0, 255), -1)
            cv2.rectangle(img, (250, 385), (265, 400), (0, 255, 255), -1)
            cv2.rectangle(img, (315, 380), (330, 395), (255, 0, 255), -1)

        else:
            # Default normal roaming
            cycle_phase = (self._demo_tick % 240) / 40.0
            if cycle_phase < 3.0:
                px = int(240 + math.sin(t * 1.5) * 80)
                py = int(340 + math.cos(t * 1.2) * 30)
                actor_state = "walking"
            else:
                px = 290
                py = 360
                actor_state = "sitting"

        # Draw main actor
        self._draw_actor(img, px, py, state=actor_state, shirt_color=(80, 180, 240))

        # Add live watermark and timestamp
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(img, f"DEMO SIMULATION | {now_str} | SCENARIO: {scenario.upper()}", (15, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 200), 1, cv2.LINE_AA)

        return img

    def _draw_actor(self, img: np.ndarray, x: int, y: int, state: str = "walking", shirt_color=(80, 180, 240)):
        """Draw an articulated simulated child figure."""
        skin_color = (180, 210, 240)
        pants_color = (60, 60, 180)

        if state == "fallen_floor":
            # Horizontal lying posture
            # Head (left)
            cv2.circle(img, (x - 45, y), 12, skin_color, -1)
            # Torso (horizontal)
            cv2.rectangle(img, (x - 30, y - 10), (x + 20, y + 10), shirt_color, -1)
            # Legs (horizontal)
            cv2.line(img, (x + 20, y - 5), (x + 60, y - 8), pants_color, 6)
            cv2.line(img, (x + 20, y + 5), (x + 55, y + 8), pants_color, 6)
            # Arms splayed
            cv2.line(img, (x - 20, y - 8), (x - 35, y - 22), skin_color, 4)
            cv2.line(img, (x - 10, y + 8), (x + 10, y + 20), skin_color, 4)

        elif state == "falling":
            # Angled collapsing posture
            angle = -0.7
            head_x = x - 20
            head_y = y - 30
            cv2.circle(img, (head_x, head_y), 13, skin_color, -1)
            cv2.line(img, (head_x, head_y + 10), (x + 10, y + 10), shirt_color, 16)
            cv2.line(img, (x + 10, y + 10), (x + 35, y + 25), pants_color, 6)
            # Flailing arm
            cv2.line(img, (x - 10, y - 10), (x - 30, y - 35), skin_color, 4)

        elif state in ["sitting", "watching_tv"]:
            # Sitting posture facing TV or resting
            head_y = y - 45
            cv2.circle(img, (x, head_y), 13, skin_color, -1)
            cv2.line(img, (x, head_y + 12), (x, y - 10), shirt_color, 18)
            cv2.line(img, (x, y - 10), (x + 25, y - 10), pants_color, 6)
            cv2.line(img, (x + 25, y - 10), (x + 25, y + 5), pants_color, 6)
            # Relaxed arms in lap
            cv2.line(img, (x, head_y + 16), (x + 15, y - 8), skin_color, 4)

        elif state == "dancing":
            # Upright energetic dance with arms raised high
            head_y = y - 75
            cv2.circle(img, (x, head_y), 14, skin_color, -1)
            cv2.line(img, (x, head_y + 12), (x, y - 25), shirt_color, 18)
            # Legs dancing apart
            dance_step = math.sin(self._demo_tick * 0.45) * 14
            cv2.line(img, (x - 6, y - 25), (int(x - 14 - dance_step), y + 15), pants_color, 6)
            cv2.line(img, (x + 6, y - 25), (int(x + 14 + dance_step), y + 15), pants_color, 6)
            # Arms raised high celebrating / dancing
            cv2.line(img, (x - 8, head_y + 15), (x - 22, head_y - 20), skin_color, 4)
            cv2.line(img, (x + 8, head_y + 15), (x + 22, head_y - 20), skin_color, 4)

        elif state == "reading":
            # Seated holding book in hands, head tilted
            head_y = y - 45
            cv2.circle(img, (x, head_y), 13, skin_color, -1)
            cv2.line(img, (x, head_y + 12), (x, y - 10), shirt_color, 18)
            cv2.line(img, (x, y - 10), (x + 20, y - 10), pants_color, 6)
            cv2.line(img, (x + 20, y - 10), (x + 20, y + 5), pants_color, 6)
            # Both hands holding book in front
            cv2.line(img, (x - 6, head_y + 16), (x, y - 22), skin_color, 4)
            cv2.line(img, (x + 6, head_y + 16), (x, y - 22), skin_color, 4)

        elif state == "writing":
            # Seated at table, leaning slightly forward, right hand writing
            head_y = y - 48
            cv2.circle(img, (x + 4, head_y), 13, skin_color, -1)
            cv2.line(img, (x, head_y + 12), (x, y - 10), shirt_color, 18)
            cv2.line(img, (x, y - 10), (x + 22, y - 10), pants_color, 6)
            cv2.line(img, (x + 22, y - 10), (x + 22, y + 5), pants_color, 6)
            # Right arm extended on table surface holding pen
            cv2.line(img, (x + 6, head_y + 16), (x + 18, y - 14), skin_color, 4)
            cv2.circle(img, (x + 19, y - 14), 2, (50, 50, 50), -1)

        elif state == "playing":
            # Crouched / kneeling playing on the floor
            head_y = y - 40
            cv2.circle(img, (x, head_y), 13, skin_color, -1)
            cv2.line(img, (x, head_y + 12), (x, y - 10), shirt_color, 18)
            # Kneeling legs
            cv2.line(img, (x - 6, y - 10), (x - 14, y + 8), pants_color, 6)
            cv2.line(img, (x + 6, y - 10), (x + 14, y + 8), pants_color, 6)
            # Arms reaching down to toys
            cv2.line(img, (x - 6, head_y + 16), (x - 12, y + 2), skin_color, 4)
            cv2.line(img, (x + 6, head_y + 16), (x + 12, y + 2), skin_color, 4)

        elif state == "touching_outlet":
            # Standing and extending right arm directly toward outlet
            head_y = y - 75
            cv2.circle(img, (x, head_y), 14, skin_color, -1)
            cv2.line(img, (x, head_y + 12), (x, y - 25), shirt_color, 18)
            # Left leg, right leg
            cv2.line(img, (x - 6, y - 25), (x - 8, y + 15), pants_color, 6)
            cv2.line(img, (x + 6, y - 25), (x + 8, y + 15), pants_color, 6)
            # Extended arm toward outlet at x ~ 85
            cv2.line(img, (x - 8, head_y + 20), (88, 365), skin_color, 5)
            cv2.circle(img, (88, 365), 5, (50, 150, 255), -1)

        else:
            # Normal upright walking or running
            head_y = y - 75
            cv2.circle(img, (x, head_y), 14, skin_color, -1)
            cv2.line(img, (x, head_y + 12), (x, y - 25), shirt_color, 18)
            # Stride swing
            step_phase = math.sin(self._demo_tick * 0.3) * 12
            cv2.line(img, (x - 6, y - 25), (int(x - 6 - step_phase), y + 15), pants_color, 6)
            cv2.line(img, (x + 6, y - 25), (int(x + 6 + step_phase), y + 15), pants_color, 6)
            # Arm swing
            cv2.line(img, (x - 8, head_y + 20), (int(x - 15 + step_phase), y - 10), skin_color, 4)
            cv2.line(img, (x + 8, head_y + 20), (int(x + 15 - step_phase), y - 10), skin_color, 4)
