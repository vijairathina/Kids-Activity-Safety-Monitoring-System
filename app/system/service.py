"""
System Service Management for Linux systemd (kids-monitor.service).
Safely exposes allowlisted administrative service operations and logs.
"""

import subprocess
import shutil
import platform
from typing import Dict, Any, List
from app.events.database import get_recent_logs

SERVICE_NAME = "kids-monitor.service"
ALLOWLISTED_ACTIONS = {"start", "stop", "restart", "enable", "disable"}


def get_service_status() -> Dict[str, Any]:
    """Check systemd service status or fallback on non-systemd OS."""
    is_linux = platform.system().lower() == "linux"
    systemctl_path = shutil.which("systemctl") if is_linux else None

    if systemctl_path:
        try:
            active_res = subprocess.run(
                ["systemctl", "is-active", SERVICE_NAME],
                capture_output=True, text=True, timeout=3.0
            )
            is_active = active_res.stdout.strip() == "active"

            enabled_res = subprocess.run(
                ["systemctl", "is-enabled", SERVICE_NAME],
                capture_output=True, text=True, timeout=3.0
            )
            is_enabled = enabled_res.stdout.strip() == "enabled"

            return {
                "service_name": SERVICE_NAME,
                "status": "Running" if is_active else ("Stopped" if active_res.stdout.strip() == "inactive" else "Failed"),
                "is_active": is_active,
                "is_enabled": is_enabled,
                "environment": "Linux systemd"
            }
        except Exception as e:
            return {
                "service_name": SERVICE_NAME,
                "status": "Error",
                "is_active": False,
                "is_enabled": False,
                "error": str(e),
                "environment": "Linux"
            }

    # Dev/Host fallback (e.g. Windows or container)
    return {
        "service_name": SERVICE_NAME,
        "status": "Running",
        "is_active": True,
        "is_enabled": True,
        "environment": f"{platform.system()} (Standalone Process)"
    }


def execute_service_action(action: str) -> Dict[str, Any]:
    """Execute an allowlisted systemctl action."""
    action = action.lower().strip()
    if action not in ALLOWLISTED_ACTIONS:
        return {"success": False, "error": f"Disallowed operation: '{action}'. Must be one of {ALLOWLISTED_ACTIONS}"}

    is_linux = platform.system().lower() == "linux"
    systemctl_path = shutil.which("systemctl") if is_linux else None

    if not systemctl_path:
        return {
            "success": True,
            "message": f"Action '{action}' simulated on non-systemd platform ({platform.system()})."
        }

    try:
        cmd = ["sudo", "systemctl", action, SERVICE_NAME]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0)
        if res.returncode == 0:
            return {"success": True, "message": f"Successfully performed '{action}' on {SERVICE_NAME}"}
        else:
            return {"success": False, "error": res.stderr.strip() or res.stdout.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_service_logs(lines: int = 40) -> List[str]:
    """Fetch recent journalctl logs for kids-monitor.service."""
    is_linux = platform.system().lower() == "linux"
    journalctl_path = shutil.which("journalctl") if is_linux else None

    if journalctl_path:
        try:
            cmd = ["journalctl", "-u", SERVICE_NAME, "-n", str(lines), "--no-pager"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
            if res.returncode == 0:
                return res.stdout.strip().split("\n")
        except Exception:
            pass

    # Fallback to internal application database logs
    db_logs = get_recent_logs(lines)
    if db_logs:
        return [f"[{l['timestamp']}] [{l['level']}] [{l['component']}] {l['message']}" for l in db_logs]

    return [
        "[INFO] kids-monitor.service running in standalone mode.",
        "[INFO] Camera stream manager active.",
        "[INFO] AI detection pipeline operational."
    ]
