"""
Flask Web Application for Kids Activity & Safety Monitoring System.
Provides REST endpoints, Server-Sent Events (SSE) live updates, MJPEG stream,
and modern Glassmorphism dashboard views.
"""

import os
import json
import time
from pathlib import Path
from typing import Optional
from flask import (
    Flask, render_template, Response, request, jsonify,
    send_from_directory, send_file
)

from app.config.settings import (
    load_config, save_config, update_config_section,
    get_sanitized_config
)
from app.events.database import (
    init_db, get_events, acknowledge_event, delete_event,
    purge_old_events, get_event_stats, log_system_message,
    check_storage_status
)
from app.camera.stream_manager import StreamManager
from app.camera.onvif import discover_onvif_cameras, get_camera_stream_uris
from app.camera.scanner import find_all_cameras, test_rtsp_url
from app.events.engine import EventEngine
from app.system.monitor import SystemMonitor
from app.system.service import (
    get_service_status, execute_service_action, get_service_logs
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Create Flask app instance
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "app" / "templates"),
    static_folder=str(BASE_DIR / "app" / "static")
)
app.config["SECRET_KEY"] = "kids-safety-monitor-secret-rpi"

# Initialize subsystems lazily / cleanly
stream_manager = StreamManager()
event_engine: Optional[EventEngine] = None
system_monitor: Optional[SystemMonitor] = None
_subsystems_initialized = False


def init_subsystems(demo: bool = False, rtsp_override: str = ""):
    """Initialize camera, AI pipeline, and database with explicit progress logs."""
    global event_engine, system_monitor, _subsystems_initialized
    if _subsystems_initialized:
        return

    init_db()

    if demo:
        update_config_section("camera", {"source_type": "demo"})
    elif rtsp_override:
        update_config_section("camera", {"source_type": "rtsp", "rtsp_url": rtsp_override})

    print("[1/4] [Camera] Initializing camera stream...")
    stream_manager.initialize()

    print("[2/4] [AI Engine] Loading AI perception engine (Ultralytics / YOLO)...")
    event_engine = EventEngine(camera_stream=stream_manager.stream)
    stream_manager.set_ai_pipeline(event_engine)

    print("[3/4] [Monitor] Starting safety & activity monitor...")
    event_engine.start()

    system_monitor = SystemMonitor()
    _subsystems_initialized = True
    log_system_message("INFO", "App", "Kids Safety Monitoring System initialized.")
    print("[4/4] [Ready] Subsystems ready!")


@app.before_request
def ensure_initialized():
    """Ensure subsystems are running before handling any HTTP request."""
    if not _subsystems_initialized:
        init_subsystems()


# ==============================================================================
# Web Views
# ==============================================================================

@app.route("/")
def index():
    """Main live monitoring dashboard."""
    return render_template("index.html", page="dashboard")


@app.route("/camera")
def camera_view():
    """Camera settings, ONVIF discovery, and preview page."""
    return render_template("camera.html", page="camera")


@app.route("/zones")
def zones_view():
    """Interactive canvas danger zone editor."""
    return render_template("zones.html", page="zones")


@app.route("/events")
def events_view():
    """Historical safety events log and recording review."""
    return render_template("events.html", page="events")


@app.route("/system")
def system_view():
    """Raspberry Pi hardware monitor and systemd service control."""
    return render_template("system.html", page="system")


@app.route("/settings")
def settings_view():
    """Global configuration and integrations page."""
    return render_template("settings.html", page="settings")


# ==============================================================================
# Video Stream & Media Endpoints
# ==============================================================================

@app.route("/video_feed")
def video_feed():
    """Multipart MJPEG video stream with safety overlays."""
    overlay = request.args.get("overlay", "true").lower() == "true"
    return Response(
        stream_manager.generate_mjpeg(overlay=overlay),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/snapshot")
def get_snapshot():
    """Download single live frame."""
    frame = stream_manager.get_snapshot()
    if frame is not None:
        import cv2
        ret, buf = cv2.imencode(".jpg", frame)
        if ret:
            return Response(buf.tobytes(), mimetype="image/jpeg")
    return "Snapshot unavailable", 503


@app.route("/media/<path:filename>")
def serve_media(filename):
    """Serve event snapshots and MP4 recording files."""
    data_dir = BASE_DIR / "data"
    file_path = data_dir / filename
    if file_path.exists() and file_path.is_file():
        return send_file(str(file_path))
    return "File not found", 404


# ==============================================================================
# Live Server-Sent Events (SSE) Stream
# ==============================================================================

@app.route("/events/stream")
def sse_events_stream():
    """Real-time SSE event pipeline for browser UI."""
    q = event_engine.subscribe_sse()

    def event_stream():
        try:
            # Send initial greeting
            yield f"data: {json.dumps({'type': 'CONNECTED', 'timestamp': time.time()})}\n\n"
            while True:
                if q:
                    ev = q.popleft()
                    yield f"data: {json.dumps(ev)}\n\n"
                else:
                    # Heartbeat every 5 seconds
                    time.sleep(1.0)
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            event_engine.unsubscribe_sse(q)

    return Response(event_stream(), mimetype="text/event-stream")


# ==============================================================================
# REST API Endpoints
# ==============================================================================

@app.route("/api/status", methods=["GET"])
def api_status():
    """Combined dashboard state: camera, AI metrics, active tracks, storage, and recent events."""
    dash_summary = event_engine.get_dashboard_summary()
    cam_status = stream_manager.get_status()
    sys_metrics = system_monitor.get_system_metrics()
    storage_info = check_storage_status()
    cfg = load_config()

    return jsonify({
        "camera": cam_status,
        "ai": dash_summary,
        "storage": storage_info,
        "retention_hours": cfg.get("recording", {}).get("retention_hours", 24),
        "system": {
            "cpu_percent": sys_metrics["cpu_percent"],
            "cpu_temp_c": sys_metrics["cpu_temp_c"],
            "ram_percent": sys_metrics["ram_percent"],
            "uptime": sys_metrics["uptime_str"],
            "platform": sys_metrics["platform"]
        },
        "timestamp": time.time()
    })


@app.route("/api/events", methods=["GET"])
def api_get_events():
    """Retrieve event history with multi-filter query parameters."""
    filter_type = request.args.get("type", "ALL")
    severity = request.args.get("severity", "ALL")
    time_range = request.args.get("range", "today")
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    events = get_events(
        filter_type=filter_type,
        severity=severity,
        time_range=time_range,
        limit=limit,
        offset=offset
    )
    stats = get_event_stats()

    return jsonify({
        "events": events,
        "stats": stats,
        "count": len(events)
    })


@app.route("/api/events/<int:event_id>/acknowledge", methods=["POST"])
def api_acknowledge_event(event_id):
    """Mark an event as acknowledged by a caregiver."""
    success = acknowledge_event(event_id)
    return jsonify({"success": success, "event_id": event_id})


@app.route("/api/events/<int:event_id>", methods=["DELETE"])
def api_delete_event(event_id):
    """Delete an event and its associated media."""
    success = delete_event(event_id)
    return jsonify({"success": success})


@app.route("/api/events/purge", methods=["POST"])
def api_purge_events():
    """Purge events older than retention period (default 24h)."""
    cfg = load_config()
    rec_cfg = cfg.get("recording", {})
    retention_hours = float(rec_cfg.get("retention_hours", 24))
    count = purge_old_events(retention_hours=retention_hours)
    return jsonify({
        "success": True,
        "deleted_count": count,
        "retention_hours": retention_hours
    })


@app.route("/api/storage/status", methods=["GET"])
def api_storage_status():
    """Query disk storage usage, threshold status, and retention configuration."""
    cfg = load_config()
    rec_cfg = cfg.get("recording", {})
    status = check_storage_status()
    status["retention_hours"] = rec_cfg.get("retention_hours", 24)
    return jsonify(status)


# ==============================================================================
# Camera Management API
# ==============================================================================

@app.route("/api/camera/status", methods=["GET"])
def api_camera_status():
    """Query current camera state."""
    return jsonify(stream_manager.get_status())


@app.route("/api/camera/config", methods=["POST"])
def api_update_camera_config():
    """Update camera configuration and reconnect stream."""
    data = request.get_json(silent=True) or {}
    cfg = update_config_section("camera", data)

    src_type = data.get("source_type", "demo")
    rtsp_url = data.get("rtsp_url", "")
    sub_url = data.get("sub_stream_url", "")

    stream_manager.update_source(src_type, rtsp_url, sub_url)
    log_system_message("INFO", "Camera", f"Camera source updated to: {src_type}")
    return jsonify({"success": True, "camera": get_sanitized_config()["camera"]})


@app.route("/api/camera/discover_onvif", methods=["POST"])
def api_discover_onvif():
    """Scan local network for ONVIF IP cameras."""
    try:
        devices = discover_onvif_cameras(timeout_sec=2.5)
        return jsonify({"success": True, "devices": devices, "count": len(devices)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "devices": []})


@app.route("/api/camera/find_all", methods=["POST"])
def api_find_all_cameras():
    """
    Comprehensive Camera Finder:
    Scans local subnet for ONVIF IP cameras, open RTSP stream ports, and USB webcams.
    """
    data = request.json or {}
    user = data.get("username", "admin")
    pwd = data.get("password", "")
    include_webcams = data.get("include_webcams", True)

    try:
        results = find_all_cameras(username=user, password=pwd, include_webcams=include_webcams)
        log_system_message("INFO", "Scanner", f"Camera search completed. Discovered {results['total_found']} devices.")
        return jsonify({"success": True, "data": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "data": {"cameras": [], "webcams": [], "total_found": 0}})


@app.route("/api/camera/test_rtsp", methods=["POST"])
def api_test_rtsp():
    """Test connection and probe frame grab from a specific RTSP URL."""
    data = request.json or {}
    url = data.get("rtsp_url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "RTSP URL is required"})
    result = test_rtsp_url(url)
    return jsonify(result)


@app.route("/api/camera/select", methods=["POST"])
def api_select_camera():
    """
    Directly select and activate a discovered camera.
    Updates config.yaml and reconnects the live video capture.
    """
    data = request.json or {}
    cam_type = data.get("type", "rtsp")
    cfg = load_config()

    if cam_type == "webcam":
        cam_update = {
            "source_type": "webcam",
            "name": data.get("name", "USB Webcam")
        }
        stream_manager.update_source("webcam")
    elif cam_type == "demo":
        cam_update = {
            "source_type": "demo",
            "name": "Synthetic Demo Stream"
        }
        stream_manager.update_source("demo")
    else:
        # RTSP / ONVIF camera
        cam_update = {
            "source_type": "rtsp",
            "ip": data.get("ip", ""),
            "onvif_port": int(data.get("onvif_port", 80)),
            "rtsp_url": data.get("main_stream", ""),
            "sub_stream_url": data.get("sub_stream", data.get("main_stream", "")),
            "name": data.get("name", f"Camera ({data.get('ip', '')})")
        }
        if data.get("username"):
            cam_update["username"] = data.get("username")
        if data.get("password"):
            cam_update["password"] = data.get("password")

        stream_manager.update_source("rtsp", rtsp_url=cam_update["rtsp_url"], sub_url=cam_update["sub_stream_url"])

    update_config_section("camera", cam_update)
    log_system_message("INFO", "Camera", f"Selected camera activated: {cam_update.get('name')}")
    return jsonify({"success": True, "camera": get_sanitized_config()["camera"]})


@app.route("/api/camera/probe_uris", methods=["POST"])
def api_probe_uris():
    """Query ONVIF camera for RTSP profile URIs."""
    data = request.json or {}
    ip = data.get("ip", "")
    port = int(data.get("port", 80))
    user = data.get("username", "")
    pwd = data.get("password", "")

    res = get_camera_stream_uris(ip, port, user, pwd)
    return jsonify(res)


@app.route("/api/camera/demo_scenario", methods=["POST"])
def api_set_demo_scenario():
    """Switch scenario in demo mode: 'normal', 'watching_tv', 'dancing', 'playing', 'reading', 'writing', 'fall', 'electrical', 'conflict'."""
    data = request.get_json(silent=True) or {}
    scenario = data.get("scenario", "normal")
    stream_manager.set_demo_scenario(scenario)
    return jsonify({"success": True, "scenario": scenario})


# ==============================================================================
# 360-Degree ONVIF PTZ Camera Controls
# ==============================================================================

@app.route("/api/camera/ptz/status", methods=["GET"])
def api_ptz_status():
    """Return 360 PTZ position, support state, and movement flag."""
    from app.camera.ptz import ptz_controller
    return jsonify(ptz_controller.get_status())


@app.route("/api/camera/ptz/move", methods=["POST"])
def api_ptz_move():
    """Execute continuous or timed 360 Pan/Tilt rotation."""
    from app.camera.ptz import ptz_controller
    data = request.get_json(silent=True) or {}
    direction = data.get("direction", "stop")
    speed = float(data.get("speed", 0.4))
    duration = float(data.get("duration", 0.4))
    res = ptz_controller.move(direction, speed=speed, duration=duration)
    return jsonify(res)


@app.route("/api/camera/ptz/step", methods=["POST"])
def api_ptz_step():
    """Step 360 camera in a direction by a fixed amount."""
    from app.camera.ptz import ptz_controller
    data = request.get_json(silent=True) or {}
    direction = data.get("direction", "")
    step_size = float(data.get("step", 0.1))
    res = ptz_controller.step(direction, step_size=step_size)
    return jsonify(res)


@app.route("/api/camera/ptz/stop", methods=["POST"])
def api_ptz_stop():
    """Immediately halt 360 Pan/Tilt rotation."""
    from app.camera.ptz import ptz_controller
    return jsonify(ptz_controller.stop())



# ==============================================================================
# Zone Management API
# ==============================================================================

@app.route("/api/zones", methods=["GET"])
def api_get_zones():
    """Return all configured zones."""
    cfg = load_config()
    return jsonify({"zones": cfg.get("zones", [])})


@app.route("/api/zones", methods=["POST"])
def api_save_zones():
    """Save updated zones from interactive canvas editor."""
    data = request.json or {}
    zones_list = data.get("zones", [])
    update_config_section("zones", zones_list)
    log_system_message("INFO", "Zones", f"Saved {len(zones_list)} zones.")
    return jsonify({"success": True, "count": len(zones_list)})


# ==============================================================================
# System & Service Management API
# ==============================================================================

@app.route("/api/system/metrics", methods=["GET"])
def api_system_metrics():
    """Get real-time CPU, RAM, Disk, Temperature, and AI telemetry."""
    metrics = system_monitor.get_system_metrics()
    storage_info = check_storage_status()
    cfg = load_config()
    rec_cfg = cfg.get("recording", {})
    metrics["storage"] = storage_info
    metrics["retention_hours"] = rec_cfg.get("retention_hours", 24)
    return jsonify(metrics)


@app.route("/api/system/service/status", methods=["GET"])
def api_service_status():
    """Check kids-monitor.service systemd status."""
    return jsonify(get_service_status())


@app.route("/api/system/service/<action>", methods=["POST"])
def api_service_action(action):
    """Execute allowlisted systemctl action (start, stop, restart, enable, disable)."""
    res = execute_service_action(action)
    return jsonify(res)


@app.route("/api/system/logs", methods=["GET"])
def api_service_logs():
    """Retrieve service logs."""
    logs = get_service_logs(lines=50)
    return jsonify({"logs": logs})


# ==============================================================================
# Settings & Privacy API
# ==============================================================================

@app.route("/api/config", methods=["GET"])
def api_get_config():
    """Get full sanitized configuration."""
    return jsonify(get_sanitized_config())


@app.route("/api/config", methods=["POST"])
def api_update_config():
    """Save global system settings."""
    data = request.json or {}
    current = load_config()

    # Update sections carefully preserving unexposed secrets if passed as masked
    for section, values in data.items():
        if isinstance(values, dict) and section in current:
            for k, v in values.items():
                if v != "******" and not (isinstance(v, str) and v.startswith("...") and v.endswith("...")):
                    current[section][k] = v
        else:
            current[section] = values

    save_config(current)
    log_system_message("INFO", "Settings", "Configuration updated via Web UI.")
    return jsonify({"success": True, "config": get_sanitized_config()})


# ==============================================================================
# Simulated Testing Triggers (for instant validation & demos)
# ==============================================================================

@app.route("/api/test/trigger_sound", methods=["POST"])
def api_trigger_sound():
    """Simulate audio scream or loud bang for testing."""
    data = request.json or {}
    stype = data.get("sound_type", "screaming")
    event_engine.audio_analyzer.trigger_demo_sound(stype)
    return jsonify({"success": True, "sound_type": stype})


def main():
    """Application entrypoint."""
    cfg = load_config()
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"================================================================")
    print(f"Kids Activity & Safety Monitoring System")
    print(f"Running locally on: http://{host}:{port}")
    print(f"Local Privacy Mode: {cfg.get('privacy', {}).get('privacy_mode')}")
    print(f"AI Backend: {event_engine.detector.backend}")
    print(f"================================================================")
    app.run(host=host, port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
