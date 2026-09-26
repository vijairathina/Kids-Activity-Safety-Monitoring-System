"""
Camera Stream Manager: Coordinates RTSP streams, MJPEG generation for web UI,
snapshots, source switching, and resolution adjustments.
"""

import time
import math
import cv2
import numpy as np
from typing import Generator, Optional, Dict, Any, Tuple
from app.camera.rtsp import RTSPStream
from app.config.settings import load_config


class StreamManager:
    """Singleton-style manager overseeing camera capture and web streaming."""

    def __init__(self):
        self.stream: Optional[RTSPStream] = None
        self.ai_pipeline = None  # Injected when AI starts
        self._is_active = False

    def initialize(self):
        """Initialize stream using current configuration."""
        cfg = load_config()
        cam_cfg = cfg.get("camera", {})

        src_type = cam_cfg.get("source_type", "demo").lower()
        if src_type == "rtsp":
            # Prefer low-res sub-stream if configured, else main RTSP
            source = cam_cfg.get("sub_stream_url") or cam_cfg.get("rtsp_url") or "demo"
        elif src_type == "webcam":
            source = "0"
        else:
            source = "demo"

        width = cam_cfg.get("width", 640)
        height = cam_cfg.get("height", 480)
        fps = cam_cfg.get("fps", 15)
        reconnect_sec = cam_cfg.get("reconnect_interval_sec", 5)

        if self.stream:
            self.stream.stop()

        self.stream = RTSPStream(
            source=source,
            width=width,
            height=height,
            target_fps=fps,
            reconnect_interval=reconnect_sec
        )
        self.stream.start()
        self._is_active = True

    def set_ai_pipeline(self, pipeline):
        """Attach AI pipeline for drawing overlays on live stream."""
        self.ai_pipeline = pipeline

    def update_source(self, source_type: str, rtsp_url: str = "", sub_url: str = ""):
        """Switch video source dynamically."""
        if not self.stream:
            self.initialize()
            return

        if source_type.lower() == "demo":
            self.stream.set_source("demo")
        elif source_type.lower() == "webcam":
            self.stream.set_source("0")
        else:
            src = sub_url if sub_url else rtsp_url
            self.stream.set_source(src if src else "demo")

    def set_demo_scenario(self, scenario: str):
        """Forward simulation scenario command to demo stream."""
        if self.stream:
            self.stream.set_demo_scenario(scenario)

    def get_latest_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Get newest raw frame from camera stream."""
        if self.stream:
            return self.stream.read()
        return False, None

    def get_snapshot(self) -> Optional[np.ndarray]:
        """Capture single snapshot frame."""
        ret, frame = self.get_latest_frame()
        return frame if ret else None

    def get_status(self) -> Dict[str, Any]:
        """Query camera stream health and metrics."""
        if self.stream:
            return self.stream.get_status()
        return {"connected": False, "source": "none", "fps": 0, "last_error": "Not initialized"}

    def generate_mjpeg(self, overlay: bool = True) -> Generator[bytes, None, None]:
        """
        Yield multipart MJPEG stream for web browser <img> element.
        Applies AI visual overlay (bounding boxes, zones, pose) if requested.
        """
        offline_tick = 0
        while self._is_active:
            ret, frame = self.get_latest_frame()
            if not ret or frame is None:
                offline_tick += 1
                display_frame = self._generate_offline_slate(offline_tick)
                time.sleep(0.1)
            else:
                # Render overlay if AI pipeline attached and enabled
                if overlay and self.ai_pipeline:
                    try:
                        display_frame = self.ai_pipeline.render_overlay(frame)
                    except Exception:
                        display_frame = frame
                else:
                    display_frame = frame

            # Encode as JPEG with medium compression for low bandwidth
            ret_enc, jpeg_buf = cv2.imencode(".jpg", display_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ret_enc:
                time.sleep(0.04)
                continue

            frame_bytes = jpeg_buf.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame_bytes)).encode() + b"\r\n\r\n"
                + frame_bytes + b"\r\n"
            )
            time.sleep(0.04)  # ~25 FPS max stream output

    def _generate_offline_slate(self, tick: int) -> np.ndarray:
        """Create informative dark-themed offline slate when stream is connecting/offline."""
        h, w = 480, 640
        slate = np.zeros((h, w, 3), dtype=np.uint8)
        # Background dark slate
        slate[:] = (22, 17, 15)

        # Subtle grid lines
        for y in range(0, h, 40):
            cv2.line(slate, (0, y), (w, y), (30, 24, 20), 1)
        for x in range(0, w, 40):
            cv2.line(slate, (x, 0), (x, h), (30, 24, 20), 1)

        # Pulsing status badge
        pulse = int(180 + 75 * math.sin(tick * 0.2))
        badge_col = (0, pulse, 255)  # Amber pulse

        cv2.rectangle(slate, (120, 140), (520, 340), (35, 30, 25), -1)
        cv2.rectangle(slate, (120, 140), (520, 340), badge_col, 2)

        # Header text
        cv2.putText(slate, "CAMERA STREAM OFFLINE", (175, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(slate, "Attempting connection...", (230, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)

        # Source info
        src_text = self.stream.source if self.stream else "None"
        if len(src_text) > 42:
            src_text = src_text[:39] + "..."
        cv2.putText(slate, f"Source: {src_text}", (140, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 240, 255), 1)

        # Error reason
        err = self.stream.last_error if self.stream and self.stream.last_error else "Connecting to RTSP / ONVIF device"
        if len(err) > 46:
            err = err[:43] + "..."
        cv2.putText(slate, f"Status: {err}", (140, 285), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100, 100, 255), 1)

        cv2.putText(slate, "Tip: Verify Safety Code or switch to Demo mode in Settings", (135, 315), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)

        return slate

    def shutdown(self):
        """Stop camera stream."""
        self._is_active = False
        if self.stream:
            self.stream.stop()
