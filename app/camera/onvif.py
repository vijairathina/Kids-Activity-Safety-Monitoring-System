"""
ONVIF Camera Discovery and Management module.
Uses WS-Discovery (UDP multicast probe) to discover IP cameras on the local network
and queries device services (via onvif-zeep or HTTP requests) for RTSP stream URIs.
"""

import socket
import re
import uuid
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

WS_DISCOVERY_ADDR = "239.255.255.250"
WS_DISCOVERY_PORT = 3702

WS_DISCOVERY_PROBE = """<?xml version="1.0" encoding="utf-8"?>
<Envelope xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
          xmlns="http://www.w3.org/2003/05/soap-envelope">
  <Header xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
    <wsa:MessageID>urn:uuid:{msg_id}</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
  </Header>
  <Body>
    <Probe xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">
      <Types>tds:Device</Types>
    </Probe>
  </Body>
</Envelope>"""


def discover_onvif_cameras(timeout_sec: float = 3.0) -> List[Dict[str, Any]]:
    """
    Broadcast WS-Discovery probe across local network and parse probe matches.
    Returns list of discovered devices with IP, XAddrs, and ONVIF service URLs.
    """
    devices: List[Dict[str, Any]] = []
    seen_ips = set()

    msg_id = str(uuid.uuid4())
    probe_packet = WS_DISCOVERY_PROBE.format(msg_id=msg_id).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout_sec)

    try:
        sock.sendto(probe_packet, (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                if ip in seen_ips:
                    continue

                response_text = data.decode("utf-8", errors="ignore")
                xaddrs = []
                xaddrs_match = re.search(r"<(?:\w+:)?XAddrs>([^<]+)</(?:\w+:)?XAddrs>", response_text)
                if xaddrs_match:
                    xaddrs = xaddrs_match.group(1).strip().split()

                scopes = []
                scopes_match = re.search(r"<(?:\w+:)?Scopes>([^<]+)</(?:\w+:)?Scopes>", response_text)
                if scopes_match:
                    scopes = scopes_match.group(1).strip().split()

                device_name = "ONVIF Camera"
                for s in scopes:
                    if "onvif://www.onvif.org/name/" in s:
                        device_name = s.split("/")[-1].replace("_", " ")
                    elif "onvif://www.onvif.org/hardware/" in s:
                        device_name += f" ({s.split('/')[-1]})"

                device_info = {
                    "ip": ip,
                    "name": device_name,
                    "xaddrs": xaddrs,
                    "service_url": xaddrs[0] if xaddrs else f"http://{ip}/onvif/device_service",
                    "port": 80
                }
                # Check custom port from xaddrs
                if xaddrs:
                    port_match = re.search(r":(\d+)/", xaddrs[0])
                    if port_match:
                        device_info["port"] = int(port_match.group(1))

                seen_ips.add(ip)
                devices.append(device_info)
            except socket.timeout:
                break
            except Exception:
                continue
    except Exception as e:
        print(f"[ONVIF Discovery] Network probe error: {e}")
    finally:
        sock.close()

    return devices


def get_camera_stream_uris(
    ip: str,
    port: int = 80,
    username: str = "",
    password: str = ""
) -> Dict[str, Any]:
    """
    Connect to camera using ONVIF / onvif-zeep and retrieve RTSP main/sub-stream URLs.
    """
    result = {
        "success": False,
        "main_stream": None,
        "sub_stream": None,
        "profiles": [],
        "error": None
    }

    try:
        import os
        import onvif
        from onvif import ONVIFCamera

        pkg_dir = os.path.dirname(onvif.__file__)
        wsdl_dir = os.path.join(os.path.dirname(pkg_dir), "wsdl")
        if not os.path.exists(wsdl_dir):
            wsdl_dir = os.path.join(pkg_dir, "wsdl")
        wsdl_path = wsdl_dir if os.path.exists(wsdl_dir) else None

        mycam = ONVIFCamera(ip, port, username, password, wsdl_dir=wsdl_path)
        media_service = mycam.create_media_service()
        profiles = media_service.GetProfiles()

        for p in profiles:
            p_token = p.token
            p_name = p.Name
            req = media_service.create_type("GetStreamUri")
            req.ProfileToken = p_token
            req.StreamSetup = {
                "Stream": "RTP-Unicast",
                "Transport": {"Protocol": "RTSP"}
            }
            stream_uri_obj = media_service.GetStreamUri(req)
            uri = stream_uri_obj.Uri
            # Inject credentials if needed
            if username and password and "@" not in uri:
                uri = uri.replace("rtsp://", f"rtsp://{username}:{password}@")

            profile_entry = {
                "token": p_token,
                "name": p_name,
                "uri": uri
            }
            result["profiles"].append(profile_entry)

        if result["profiles"]:
            result["main_stream"] = result["profiles"][0]["uri"]
            if len(result["profiles"]) > 1:
                result["sub_stream"] = result["profiles"][1]["uri"]
            else:
                result["sub_stream"] = result["main_stream"]
            result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        # Construct standard RTSP fallback candidates using port 554
        creds = f"{username}:{password}@" if username and password else ""
        result["main_stream"] = f"rtsp://{creds}{ip}:554/cam/realmonitor?channel=1&subtype=0&unicast=true&proto=Onvif"
        result["sub_stream"] = f"rtsp://{creds}{ip}:554/cam/realmonitor?channel=1&subtype=1&unicast=true&proto=Onvif"
        result["hint"] = "Generated standard RTSP port 554 fallback URI"

    return result
