"""
ONVIF PTZ (Pan / Tilt / Zoom) Controller for 360-Degree IP Cameras.
Supports ContinuousMove, RelativeMove, Stop, Position Status, and
Camera Movement State tracking to prevent false computer vision alarms
during camera rotation.
"""

import os
import time
import math
import threading
from typing import Dict, Any, Optional, Tuple


class PTZController:
    """Manages Pan/Tilt/Zoom operations for ONVIF 360-degree cameras."""

    def __init__(self):
        self._cam = None
        self._ptz_service = None
        self._media_service = None
        self._profile_token = None
        self._lock = threading.RLock()
        self._is_connected = False
        self._is_moving = False
        self._last_move_time = 0.0
        self._movement_cooldown_sec = 1.8  # Wait for camera stabilization after move
        self._last_error = ""
        self._current_position: Dict[str, float] = {"pan": 0.0, "tilt": 0.0}

    def connect(self, ip: str, port: int = 80, username: str = "", password: str = "") -> bool:
        """Connect to camera ONVIF PTZ service."""
        with self._lock:
            try:
                import onvif
                from onvif import ONVIFCamera

                pkg_dir = os.path.dirname(onvif.__file__)
                wsdl_dir = os.path.join(os.path.dirname(pkg_dir), "wsdl")
                if not os.path.exists(wsdl_dir):
                    wsdl_dir = os.path.join(pkg_dir, "wsdl")
                wsdl_path = wsdl_dir if os.path.exists(wsdl_dir) else None

                self._cam = ONVIFCamera(ip, port, username, password, wsdl_dir=wsdl_path)
                self._ptz_service = self._cam.create_ptz_service()
                self._media_service = self._cam.create_media_service()

                profiles = self._media_service.GetProfiles()
                if profiles:
                    self._profile_token = profiles[0].token
                else:
                    self._last_error = "No media profiles found for PTZ"
                    return False

                self._is_connected = True
                self._last_error = ""
                self._refresh_position()
                print(f"[PTZ] Connected to 360° PTZ camera at {ip}:{port} (Profile: {self._profile_token})")
                return True
            except Exception as e:
                self._is_connected = False
                self._last_error = str(e)
                print(f"[PTZ] Connection failed: {e}")
                return False

    def is_camera_moving(self) -> bool:
        """
        Returns True if the camera is actively moving or within the stabilization
        cooldown period. Used by safety modules to suppress false alarms during rotation.
        """
        if self._is_moving:
            return True
        if (time.time() - self._last_move_time) < self._movement_cooldown_sec:
            return True
        return False

    def move(self, direction: str, speed: float = 0.4, duration: float = 0.4) -> Dict[str, Any]:
        """
        Execute pan/tilt movement.
        direction: 'left', 'right', 'up', 'down', 'upleft', 'upright', 'downleft', 'downright', 'stop'
        """
        with self._lock:
            if not self._is_connected or self._ptz_service is None or not self._profile_token:
                return {"success": False, "error": self._last_error or "PTZ service not connected"}

            direction = direction.lower().strip()
            if direction == "stop":
                return self.stop()

            # Velocity vector mapping (-1.0 to +1.0)
            vx, vy = 0.0, 0.0
            if "left" in direction:
                vx = -abs(speed)
            elif "right" in direction:
                vx = abs(speed)

            if "up" in direction:
                vy = abs(speed)
            elif "down" in direction:
                vy = -abs(speed)

            try:
                req = self._ptz_service.create_type("ContinuousMove")
                req.ProfileToken = self._profile_token
                req.Velocity = {
                    "PanTilt": {"x": vx, "y": vy}
                }

                self._is_moving = True
                self._last_move_time = time.time()
                self._ptz_service.ContinuousMove(req)

                # Stop automatically after duration in a background worker
                if duration > 0:
                    threading.Thread(target=self._auto_stop_after, args=(duration,), daemon=True).start()

                return {
                    "success": True,
                    "direction": direction,
                    "vx": vx,
                    "vy": vy,
                    "duration": duration,
                    "is_moving": True
                }
            except Exception as e:
                self._last_error = str(e)
                self._is_moving = False
                return {"success": False, "error": str(e)}

    def step(self, direction: str, step_size: float = 0.1) -> Dict[str, Any]:
        """Execute a discrete relative pan/tilt step."""
        with self._lock:
            if not self._is_connected or self._ptz_service is None or not self._profile_token:
                return {"success": False, "error": self._last_error or "PTZ service not connected"}

            direction = direction.lower().strip()
            dx, dy = 0.0, 0.0
            if "left" in direction:
                dx = -abs(step_size)
            elif "right" in direction:
                dx = abs(step_size)

            if "up" in direction:
                dy = abs(step_size)
            elif "down" in direction:
                dy = -abs(step_size)

            try:
                req = self._ptz_service.create_type("RelativeMove")
                req.ProfileToken = self._profile_token
                req.Translation = {
                    "PanTilt": {"x": dx, "y": dy}
                }

                self._is_moving = True
                self._last_move_time = time.time()
                self._ptz_service.RelativeMove(req)

                # Flag moving state for stabilization
                threading.Thread(target=self._mark_idle_after, args=(0.6,), daemon=True).start()

                return {
                    "success": True,
                    "direction": direction,
                    "dx": dx,
                    "dy": dy
                }
            except Exception as e:
                # If RelativeMove fails, fallback to short continuous move
                return self.move(direction, speed=0.3, duration=0.25)

    def stop(self) -> Dict[str, Any]:
        """Immediately stop all pan/tilt motion."""
        with self._lock:
            if not self._is_connected or self._ptz_service is None or not self._profile_token:
                return {"success": False, "error": "PTZ service not connected"}

            try:
                req = self._ptz_service.create_type("Stop")
                req.ProfileToken = self._profile_token
                req.PanTilt = True
                req.Zoom = True
                self._ptz_service.Stop(req)
                self._is_moving = False
                self._last_move_time = time.time()
                self._refresh_position()
                return {"success": True, "stopped": True}
            except Exception as e:
                self._is_moving = False
                self._last_error = str(e)
                return {"success": False, "error": str(e)}

    def _auto_stop_after(self, delay: float):
        """Internal helper to halt continuous movement after elapsed duration."""
        time.sleep(delay)
        self.stop()

    def _mark_idle_after(self, delay: float):
        """Internal helper to mark movement completed."""
        time.sleep(delay)
        with self._lock:
            self._is_moving = False
            self._refresh_position()

    def _refresh_position(self):
        """Query current PTZ coordinates from camera."""
        if not self._ptz_service or not self._profile_token:
            return
        try:
            status = self._ptz_service.GetStatus({"ProfileToken": self._profile_token})
            if status and hasattr(status, "Position") and status.Position:
                pt = status.Position.PanTilt
                if pt:
                    self._current_position = {
                        "pan": round(float(pt.x), 2),
                        "tilt": round(float(pt.y), 2)
                    }
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive PTZ status and movement flag."""
        with self._lock:
            return {
                "supported": self._is_connected,
                "is_moving": self.is_camera_moving(),
                "position": self._current_position,
                "profile_token": self._profile_token,
                "last_error": self._last_error
            }


# Singleton instance
ptz_controller = PTZController()
