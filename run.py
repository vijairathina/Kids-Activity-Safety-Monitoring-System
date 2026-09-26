#!/usr/bin/env python3
"""
Entry point for Kids Activity & Safety Monitoring System.
Usage:
    python run.py [--host 0.0.0.0] [--port 5000] [--demo]
"""

import argparse
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import socket
from app.config.settings import load_config, update_config_section
from app.app import app, stream_manager, init_subsystems


def is_port_available(host: str, port: int) -> bool:
    """Test whether a port can be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host if host != "0.0.0.0" else "", port))
            return True
        except OSError:
            return False


def find_free_port(host: str, preferred_port: int) -> int:
    """Return preferred_port if free, else find the next open port."""
    if is_port_available(host, preferred_port):
        return preferred_port
    for p in range(preferred_port + 1, preferred_port + 50):
        if is_port_available(host, p):
            return p
    return preferred_port


def main():
    cfg = load_config()
    server_cfg = cfg.get("server", {})
    default_host = os.environ.get("HOST", server_cfg.get("host", "0.0.0.0"))
    default_port = int(os.environ.get("PORT", server_cfg.get("port", 5055)))

    parser = argparse.ArgumentParser(description="Kids Activity & Safety Monitoring System (Raspberry Pi)")
    parser.add_argument("--host", default=default_host, help=f"Host IP to bind (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port to listen on (default: {default_port})")
    parser.add_argument("--demo", action="store_true", help="Force synthetic demo stream mode")
    parser.add_argument("--rtsp", type=str, default="", help="Override RTSP camera stream URL")
    args = parser.parse_args()

    actual_port = find_free_port(args.host, args.port)
    if actual_port != args.port:
        print(f"[!] Note: Port {args.port} is already in use. Automatically switched to port {actual_port}.")

    # Initialize subsystems cleanly with flags
    init_subsystems(demo=args.demo, rtsp_override=args.rtsp)
    from app.app import event_engine

    detector_name = event_engine.detector.backend if event_engine and event_engine.detector else "ultralytics"
    cam_src = stream_manager.stream.source if stream_manager.stream else "None"

    print("\n" + "=" * 65)
    print("  *  KIDS ACTIVITY & SAFETY MONITORING SYSTEM")
    print("  Optimized for Raspberry Pi & Local Edge Privacy")
    print("=" * 65)
    print(f"  - Local Web Dashboard: http://localhost:{actual_port}")
    print(f"  - Network Web Access:  http://{args.host}:{actual_port}")
    print(f"  - Camera Source:       {cam_src}")
    print(f"  - AI Backend:          {detector_name}")
    print(f"  - Privacy Mode:        {cfg.get('privacy', {}).get('privacy_mode', False)}")
    print(f"  - Face Blurring:       {cfg.get('privacy', {}).get('face_blur', False)}")
    print("=" * 65 + "\n")

    app.run(host=args.host, port=actual_port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
