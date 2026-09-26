"""
Unified Camera Finder and Network Scanner for Kids Safety Monitoring System.
Combines:
1. ONVIF WS-Discovery (UDP multicast)
2. Subnet port scan (RTSP 554, ONVIF 80/8080/8899, Dahua 37777, Hikvision 8000)
3. Local USB Webcam enumeration (OpenCV VideoCapture)
4. RTSP stream candidate path probing
"""

import socket
import re
import time
import cv2
import concurrent.futures
from typing import List, Dict, Any, Optional
from app.camera.onvif import discover_onvif_cameras, get_camera_stream_uris

# Common camera streaming & management ports
CAMERA_PORTS = [554, 80, 8080, 8899, 37777, 8000, 34567, 5000]

# Standard RTSP path candidates across major IP camera brands
COMMON_RTSP_PATHS = [
    ("/live/ch0", "/live/ch1"),
    ("/stream1", "/stream2"),
    ("/h264Preview_01_main", "/h264Preview_01_sub"),
    ("/onvif1", "/onvif2"),
    ("/ch0_0.264", "/ch0_1.264"),
    ("/cam/realmonitor?channel=1&subtype=0", "/cam/realmonitor?channel=1&subtype=1"),
    ("/Streaming/Channels/101", "/Streaming/Channels/102"),
    ("/video1", "/video2"),
    ("", "")
]


def get_local_ip_and_subnet() -> tuple[str, str]:
    """Retrieve host local IP and its /24 base subnet (e.g., '192.168.0')."""
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # Dummy connect to determine outbound interface IP
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "127.0.0.1"

    if "." in local_ip:
        parts = local_ip.split(".")
        base_subnet = f"{parts[0]}.{parts[1]}.{parts[2]}"
    else:
        base_subnet = "192.168.1"

    return local_ip, base_subnet


def scan_port(ip: str, port: int, timeout: float = 0.25) -> bool:
    """Check if TCP port is open on IP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        res = sock.connect_ex((ip, port))
        sock.close()
        return res == 0
    except Exception:
        return False


def scan_ip_for_camera_ports(ip: str) -> Optional[Dict[str, Any]]:
    """Scan key camera ports on a single IP."""
    open_ports = []
    # Test RTSP port 554 first as it's the strongest indicator
    has_rtsp = scan_port(ip, 554, timeout=0.20)
    if has_rtsp:
        open_ports.append(554)

    # Test remaining camera ports
    for p in CAMERA_PORTS:
        if p != 554 and scan_port(ip, p, timeout=0.18):
            open_ports.append(p)

    if open_ports:
        return {
            "ip": ip,
            "open_ports": open_ports,
            "has_rtsp": 554 in open_ports,
            "has_onvif_port": any(p in open_ports for p in [80, 8080, 8899, 5000])
        }
    return None


def scan_local_subnet_cameras(base_subnet: Optional[str] = None, max_workers: int = 50) -> List[Dict[str, Any]]:
    """
    Rapidly scan the /24 subnet for active IP cameras.
    Scans all 254 IPs concurrently in under ~3 seconds.
    """
    if not base_subnet:
        _, base_subnet = get_local_ip_and_subnet()

    ips_to_scan = [f"{base_subnet}.{i}" for i in range(1, 255)]
    found_devices = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(scan_ip_for_camera_ports, ips_to_scan)
        for res in results:
            if res:
                found_devices.append(res)

    return found_devices


def scan_local_webcams(max_indices_to_test: int = 4) -> List[Dict[str, Any]]:
    """
    Check for attached USB webcams or integrated cameras using OpenCV.
    """
    webcams = []
    for idx in range(max_indices_to_test):
        try:
            # Quick open test
            cap = cv2.VideoCapture(idx)
            if cap is not None and cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = int(cap.get(cv2.CAP_PROP_FPS)) or 30
                cap.release()
                webcams.append({
                    "type": "webcam",
                    "index": idx,
                    "name": f"USB / Integrated Camera #{idx}",
                    "resolution": f"{w}x{h}",
                    "fps": fps,
                    "source": str(idx)
                })
        except Exception:
            continue
    return webcams


def test_rtsp_url(rtsp_url: str, timeout_sec: float = 3.0) -> Dict[str, Any]:
    """
    Attempt to open an RTSP URL and grab one test frame.
    """
    result = {
        "success": False,
        "url": rtsp_url,
        "resolution": None,
        "error": None
    }
    try:
        import os
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ret, frame = cap.read()
            if ret and frame is not None:
                h, w = frame.shape[:2]
                result["success"] = True
                result["resolution"] = f"{w}x{h}"
            else:
                result["error"] = "Camera stream opened but could not read frame."
            cap.release()
        else:
            result["error"] = "Failed to establish RTSP connection."
    except Exception as e:
        result["error"] = str(e)
    return result


def find_all_cameras(
    username: str = "admin",
    password: str = "",
    include_webcams: bool = True
) -> Dict[str, Any]:
    """
    Master Camera Finder:
    Runs ONVIF discovery, Subnet port scanning, USB webcams scan, and stream path inference.
    """
    local_ip, base_subnet = get_local_ip_and_subnet()
    results = {
        "host_ip": local_ip,
        "subnet": f"{base_subnet}.0/24",
        "cameras": [],
        "webcams": [],
        "total_found": 0
    }

    # 1. Enumerate USB Webcams
    if include_webcams:
        results["webcams"] = scan_local_webcams()

    # 2. ONVIF WS-Discovery (Multicast)
    onvif_devices = []
    try:
        onvif_devices = discover_onvif_cameras(timeout_sec=2.0)
    except Exception as e:
        print(f"[Finder] ONVIF probe error: {e}")

    seen_ips = set()
    for dev in onvif_devices:
        ip = dev["ip"]
        seen_ips.add(ip)
        port = dev.get("port", 80)
        # Query RTSP profile URIs
        stream_info = get_camera_stream_uris(ip, port, username, password)

        main_url = stream_info.get("main_stream") or f"rtsp://{username}:{password}@{ip}:554/live/ch0"
        sub_url = stream_info.get("sub_stream") or f"rtsp://{username}:{password}@{ip}:554/live/ch1"

        results["cameras"].append({
            "type": "onvif",
            "ip": ip,
            "name": dev.get("name", f"ONVIF Camera ({ip})"),
            "onvif_port": port,
            "main_stream": main_url,
            "sub_stream": sub_url,
            "detection_method": "ONVIF WS-Discovery",
            "open_ports": [554, port]
        })

    # 3. Subnet Port Scan for non-multicast or unannounced cameras
    scanned_ips = scan_local_subnet_cameras(base_subnet=base_subnet)
    for s in scanned_ips:
        ip = s["ip"]
        if ip in seen_ips or ip == local_ip:
            continue
        seen_ips.add(ip)

        creds = f"{username}:{password}@" if (username or password) else ""
        main_url = f"rtsp://{creds}{ip}:554/live/ch0"
        sub_url = f"rtsp://{creds}{ip}:554/live/ch1"

        results["cameras"].append({
            "type": "rtsp",
            "ip": ip,
            "name": f"IP Camera ({ip})",
            "onvif_port": s["open_ports"][0] if s["open_ports"] else 80,
            "main_stream": main_url,
            "sub_stream": sub_url,
            "detection_method": "Subnet Port Scan",
            "open_ports": s["open_ports"]
        })

    results["total_found"] = len(results["cameras"]) + len(results["webcams"])
    return results
