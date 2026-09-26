"""
Hardware and System Performance Monitor for Raspberry Pi.
Gathers CPU%, RAM%, Disk, Temperature, Uptime, Architecture, and AI metrics.
Maintains history for real-time dashboard charts.
"""

import time
import os
import platform
import psutil
from collections import deque
from typing import Dict, Any, List

START_TIME = time.time()


class SystemMonitor:
    """Monitors Raspberry Pi system health and performance telemetry."""

    def __init__(self, history_len: int = 30):
        self.history_len = history_len
        # Telemetry history for frontend graphs
        self.cpu_history = deque(maxlen=history_len)
        self.ram_history = deque(maxlen=history_len)
        self.temp_history = deque(maxlen=history_len)
        self.fps_history = deque(maxlen=history_len)
        self.time_history = deque(maxlen=history_len)

    @staticmethod
    def get_cpu_temperature() -> float:
        """Read CPU temperature on Raspberry Pi or return simulated/host temp."""
        # 1. Linux sysfs thermal zone (standard on Raspberry Pi OS)
        thermal_path = "/sys/class/thermal/thermal_zone0/temp"
        if os.path.exists(thermal_path):
            try:
                with open(thermal_path, "r") as f:
                    return round(float(f.read().strip()) / 1000.0, 1)
            except Exception:
                pass

        # 2. psutil sensors if available
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        return round(entries[0].current, 1)
        except Exception:
            pass

        # 3. Fallback baseline estimate based on CPU load
        return round(42.0 + (psutil.cpu_percent(interval=None) * 0.18), 1)

    def get_system_metrics(self) -> Dict[str, Any]:
        """Fetch snapshot of host system metrics."""
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        from pathlib import Path
        base_dir = str(Path(__file__).resolve().parent.parent.parent)
        try:
            disk = psutil.disk_usage(base_dir)
        except Exception:
            disk = psutil.disk_usage("/")
        temp = self.get_cpu_temperature()
        uptime_sec = int(time.time() - START_TIME)

        # Format uptime as HH:MM:SS or days
        hours, remainder = divmod(uptime_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        now_str = time.strftime("%H:%M:%S")

        # Record to history
        self.cpu_history.append(cpu_pct)
        self.ram_history.append(mem.percent)
        self.temp_history.append(temp)
        self.time_history.append(now_str)

        return {
            "cpu_percent": cpu_pct,
            "cpu_temp_c": temp,
            "ram_percent": mem.percent,
            "ram_used_mb": round((mem.total - mem.available) / (1024 * 1024), 1),
            "ram_total_mb": round(mem.total / (1024 * 1024), 1),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024 * 1024 * 1024), 1),
            "disk_total_gb": round(disk.total / (1024 * 1024 * 1024), 1),
            "uptime_seconds": uptime_sec,
            "uptime_str": uptime_str,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or platform.machine(),
            "history": {
                "timestamps": list(self.time_history),
                "cpu": list(self.cpu_history),
                "ram": list(self.ram_history),
                "temp": list(self.temp_history)
            }
        }
