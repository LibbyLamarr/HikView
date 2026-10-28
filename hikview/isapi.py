"""
Hikvision / HiLook / OEM ISAPI & Multi-Brand HTTP/RTSP diagnostic helper.
Provides device discovery, authentication verification, and channel name + online status lookup
for Hikvision, HiLook, Dahua/Amcrest, Reolink, and ONVIF/RTSP cameras.
"""

import socket
import urllib3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
import requests
from requests.auth import HTTPDigestAuth, HTTPBasicAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class DeviceInfoResult:
    success: bool
    message: str
    device_name: str = ""
    model: str = ""
    serial_number: str = ""
    firmware_version: str = ""
    channels_discovered: Dict[int, str] = field(default_factory=dict)
    channels_online: Dict[int, bool] = field(default_factory=dict)


def test_tcp_port(host: str, port: int, timeout: float = 3.0) -> Tuple[bool, str]:
    """Check if a TCP port (such as RTSP 554 or HTTP 80) is reachable."""
    if not host.strip():
        return False, "Host IP / hostname is empty."
    try:
        with socket.create_connection((host.strip(), int(port)), timeout=timeout):
            return True, f"TCP port {port} is open and reachable on {host}."
    except socket.timeout:
        return False, f"Connection to {host}:{port} timed out ({timeout:.0f}s)."
    except ConnectionRefusedError:
        return False, f"Connection refused by {host}:{port}. Check port forwarding or service status."
    except Exception as e:
        return False, f"Cannot reach {host}:{port} ({e})."


def _query_dahua_device_info(
    base_url: str,
    username: str,
    password: str,
    timeout: float = 4.0,
) -> Optional[DeviceInfoResult]:
    """Attempt Dahua / Amcrest / Lorex HTTP CGI device & channel name discovery."""
    auth_methods = [
        HTTPDigestAuth(username, password),
        HTTPBasicAuth(username, password),
    ]
    used_auth = None
    model = ""
    dev_name = ""

    for auth in auth_methods:
        try:
            r = requests.get(
                f"{base_url}/cgi-bin/magicBox.cgi?action=getSystemInfo",
                auth=auth,
                timeout=timeout,
                verify=False,
            )
            if r.status_code == 200 and r.text:
                used_auth = auth
                for line in r.text.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if k in ("deviceType", "hardwareVersion", "updateSerial"):
                            model = model or v
                break
            elif r.status_code == 401:
                return DeviceInfoResult(
                    success=False,
                    message="Authentication failed (HTTP 401 Unauthorized). Check username/password.",
                )
        except requests.RequestException:
            break

    if used_auth is None:
        return None

    channels: Dict[int, str] = {}
    try:
        cr = requests.get(
            f"{base_url}/cgi-bin/configManager.cgi?action=getConfig&name=ChannelTitle",
            auth=used_auth,
            timeout=timeout,
            verify=False,
        )
        if cr.status_code == 200 and cr.text:
            for line in cr.text.splitlines():
                # e.g. table.ChannelTitle[0].Name=Front Door
                if "ChannelTitle[" in line and "].Name=" in line:
                    try:
                        idx_part = line.split("ChannelTitle[", 1)[1].split("]", 1)[0]
                        cname = line.split("].Name=", 1)[1].strip()
                        ch_id = int(idx_part) + 1
                        if 1 <= ch_id <= 16 and cname:
                            channels[ch_id] = cname
                    except ValueError:
                        pass
    except Exception:
        pass

    summary = f"Connected to {model or 'Dahua / Amcrest / Lorex Device'}"
    return DeviceInfoResult(
        success=True,
        message=summary,
        device_name=dev_name,
        model=model or "Dahua / Amcrest NVR",
        channels_discovered=channels,
    )


def query_isapi_device_info(
    host: str,
    http_port: int,
    username: str,
    password: str,
    timeout: float = 4.0,
    use_https: bool = False,
    url_style: str = "isapi",
) -> DeviceInfoResult:
    """
    Query Hikvision / HiLook / OEM ISAPI endpoints (or Dahua CGI when selected) to verify credentials
    and fetch device metadata, configured camera channel names (up to 16 channels), and online status.
    """
    scheme = "https" if (use_https or int(http_port) == 443) else "http"
    base_url = f"{scheme}://{host.strip()}:{http_port}"

    if url_style == "dahua":
        dahua_res = _query_dahua_device_info(base_url, username, password, timeout=timeout)
        if dahua_res is not None:
            return dahua_res

    info_url = f"{base_url}/ISAPI/System/deviceInfo"

    auth_methods = [
        HTTPDigestAuth(username, password),
        HTTPBasicAuth(username, password),
    ]

    resp = None
    last_err = ""
    used_auth = None

    for auth in auth_methods:
        try:
            r = requests.get(info_url, auth=auth, timeout=timeout, verify=False)
            if r.status_code == 200:
                resp = r
                used_auth = auth
                break
            elif r.status_code == 401:
                last_err = "Authentication failed (HTTP 401 Unauthorized). Check username/password."
            elif r.status_code == 403:
                last_err = "Access forbidden (HTTP 403). User may lack permission."
            else:
                last_err = f"HTTP {r.status_code} returned from {info_url}"
        except requests.RequestException as e:
            last_err = f"HTTP connection error: {e}"
            break

    if resp is None:
        if url_style not in ("isapi", "legacy"):
            return DeviceInfoResult(
                success=False,
                message="Non-ISAPI device (RTSP streaming works directly over port 554; HTTP ISAPI auto-discovery is specific to Hikvision/HiLook/OEM).",
            )
        return DeviceInfoResult(success=False, message=last_err or "Failed to query ISAPI device info.")

    # Parse XML response
    dev_name = ""
    model = ""
    serial = ""
    fw = ""
    try:
        root = ET.fromstring(resp.text)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            text = (elem.text or "").strip()
            if tag == "deviceName":
                dev_name = text
            elif tag == "model":
                model = text
            elif tag == "serialNumber":
                serial = text
            elif tag == "firmwareVersion":
                fw = text
    except Exception:
        pass

    # Fetch channel names from ContentMgmt/InputProxy/channels or Video/inputs/channels
    channels: Dict[int, str] = {}
    channel_endpoints = [
        f"{base_url}/ISAPI/ContentMgmt/InputProxy/channels",
        f"{base_url}/ISAPI/System/Video/inputs/channels",
        f"{base_url}/ISAPI/Streaming/channels",
    ]

    for ep in channel_endpoints:
        try:
            cr = requests.get(ep, auth=used_auth, timeout=timeout, verify=False)
            if cr.status_code == 200 and cr.text:
                c_root = ET.fromstring(cr.text)
                for ch_elem in c_root:
                    ch_tag = ch_elem.tag.split("}")[-1]
                    if ch_tag in ("InputProxyChannel", "VideoInputChannel", "StreamingChannel"):
                        ch_id = None
                        ch_name = None
                        for sub in ch_elem:
                            stag = sub.tag.split("}")[-1]
                            if stag == "id" and sub.text:
                                try:
                                    raw_id = int(sub.text.strip())
                                    if raw_id >= 100:
                                        if raw_id % 100 == 1:
                                            ch_id = raw_id // 100
                                    else:
                                        ch_id = raw_id
                                except ValueError:
                                    pass
                            elif stag in ("name", "channelName") and sub.text:
                                ch_name = sub.text.strip()
                        if ch_id and ch_name and 1 <= ch_id <= 16 and ch_id not in channels:
                            channels[ch_id] = ch_name
                if channels:
                    break
        except Exception:
            continue

    # Also check InputProxy/channels/status to see which channels actually have an online camera connected
    channels_online: Dict[int, bool] = {}
    try:
        sr = requests.get(
            f"{base_url}/ISAPI/ContentMgmt/InputProxy/channels/status",
            auth=used_auth,
            timeout=timeout,
            verify=False,
        )
        if sr.status_code == 200 and sr.text:
            s_root = ET.fromstring(sr.text)
            for st_elem in s_root:
                if st_elem.tag.split("}")[-1] == "InputProxyChannelStatus":
                    cid = None
                    is_online = False
                    for sub in st_elem:
                        stag = sub.tag.split("}")[-1]
                        if stag == "id" and sub.text:
                            try:
                                cid = int(sub.text.strip())
                            except ValueError:
                                pass
                        elif stag == "online" and sub.text:
                            is_online = sub.text.strip().lower() == "true"
                    if cid is not None:
                        channels_online[cid] = is_online
    except Exception:
        pass

    summary = f"Connected to {model or 'Hikvision/HiLook/OEM Device'}"
    if dev_name:
        summary += f" ({dev_name})"
    if fw:
        summary += f" | FW: {fw}"

    return DeviceInfoResult(
        success=True,
        message=summary,
        device_name=dev_name,
        model=model,
        serial_number=serial,
        firmware_version=fw,
        channels_discovered=channels,
        channels_online=channels_online,
    )
