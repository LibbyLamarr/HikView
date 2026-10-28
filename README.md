# HikView — Lightweight Windows Viewer for NVRs & RTSP/ONVIF IP Cameras

[![Version](https://img.shields.io/badge/Version-V1.0.0-e03e3e.svg)](https://github.com/LibbyLamarr/HikView/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078d4.svg)](https://github.com/LibbyLamarr/HikView/releases)

**HikView** is a fast, lightweight Windows desktop application designed for low-latency live viewing of Network Video Recorders (NVRs) and standalone IP cameras. Built as a responsive, streamlined alternative to heavy surveillance suites like **iVMS-4200**, HikView supports up to **16 simultaneous camera channels** across multiple NVRs and standalone RTSP/ONVIF cameras.

---

## Key Features

- **Multi-Brand NVR & IP Camera Support**:
  - Built-in RTSP presets for **Hikvision**, **HiLook** (including NVR-104H-D/4P, NVR-108H/208M, DS-76xx/77xx), **Legacy Hikvision**, **Dahua / Amcrest / Lorex**, **Reolink**, **Uniview (UNV)**, **TP-Link Tapo / VIGI**, and **Generic ONVIF / Custom RTSP** streams.
  - **ISAPI & CGI Auto-Discovery**: Test your NVR connection and automatically discover device model info and configured camera channel names directly from your recorder.
  - **Multi-Source Camera Channels**: Combine channels from a **Primary NVR**, a **Secondary NVR**, and **Standalone IP Cameras** (up to 16 cameras total) in a single unified view.
  - Properly URL-encodes special characters (`@`, `:`, `#`, `/`) in NVR and camera passwords.
- **Adaptive Multi-Camera & Focus Layouts**:
  - **1×1 Single Camera View**: Maximize any single camera to the full window or screen.
  - **2×2 Quad View (4 Cameras)**, **3×3 Grid (9 Cameras)**, and **4×4 Grid (16 Cameras)**.
  - **1+3 Focus View** & **1+5 Focus View**: One large primary camera in HD with secondary cameras arranged alongside it.
  - **Drag-and-Drop Camera Swapping**: Drag any camera tile onto another tile to rearrange your layout on the fly, or right-click any tile to assign a different camera or set it to an Empty Black View.
  - **Double-Click Solo/Restore**: Double-click any camera tile to immediately maximize it to full single-camera HD view; double-click again to return to your multi-camera layout.
- **Smart Main-Stream (HD) / Sub-Stream (SD) Switching**:
  - Automatically streams low-CPU **Sub-Streams (SD)** in multi-camera grid tiles and seamlessly switches to full-HD **Main-Streams** when viewing a single camera or primary focus slot (or override per channel).
- **Real-Time Low-Latency Engine**:
  - Dedicated background decoding thread per camera using FFmpeg over TCP (`nobuffer` / `low_delay`) with automatic reconnection if a stream drops.
- **Instant PNG Snapshots & Built-in Demo Feed Simulator**:
  - Capture full-resolution PNG snapshots (`S` key or right-click → *Save Snapshot*) and test layouts offline using the **Simulate Feeds** button.

---

## Supported NVRs & IP Cameras

| Brand / Preset | RTSP Path Format | Auto-Discovery |
| :--- | :--- | :--- |
| **Hikvision / HiLook / OEM (ISAPI)** | `/Streaming/Channels/<Ch>01` (Main) & `<Ch>02` (Sub) | ISAPI HTTP Digest |
| **Hikvision / HiLook Legacy** | `/h264/ch<Ch>/main/av_stream` & `/sub/av_stream` | ISAPI / TCP |
| **Dahua / Amcrest / Lorex** | `/cam/realmonitor?channel=<Ch>&subtype=0` (Main) & `1` (Sub) | CGI HTTP Digest |
| **Reolink NVR & IP Cameras** | `/h264Preview_<Ch>_main` & `/h264Preview_<Ch>_sub` | TCP + RTSP Test |
| **Uniview (UNV) / ONVIF** | `/unicast/c<Ch>/s0/live` & `/unicast/c<Ch>/s1/live` | TCP + RTSP Test |
| **TP-Link Tapo / VIGI** | `/stream1` (HD) & `/stream2` (SD) | TCP + RTSP Test |
| **Custom RTSP / ONVIF** | Custom `rtsp://` Main and Sub Stream URLs per camera | TCP + RTSP Test |

---

## Download & Installation

Download the latest release from the [**GitHub Releases**](https://github.com/LibbyLamarr/HikView/releases) page:

### Option 1: Windows Installer (Recommended)
1. Download **`HikView-Setup-v1.0.0.exe`**.
2. Run the installer to install HikView into `C:\Program Files\HikView` and create Desktop & Start Menu shortcuts.

### Option 2: Portable ZIP (No Installation Required)
1. Download **`HikView-Portable-v1.0.0.zip`**.
2. Extract the `HikView` folder anywhere on your PC or USB drive and launch **`HikView.exe`**.

### Option 3: Run from Python Source
```powershell
pip install -r requirements.txt
python main.py
```

---

## Quick Start Guide

1. Launch **HikView** and click **Settings** in the top toolbar.
2. On the **Primary NVR / Device Connection** tab, select your **Device Brand / Type**, enter your NVR's IP address (e.g., `192.168.1.64`), RTSP Port (`554`), HTTP Port (`80`), Username (`admin`), and Password.
3. Click **Test Connection & Auto-Discover Cameras** to verify port reachability and automatically populate your camera channels.
4. *(Optional)* Switch to the **Cameras & Sources** tab to add up to 16 cameras or click **Configure** on any row to connect a Secondary NVR or Standalone IP Camera.
5. Click **Save & Apply**, then click **Connect Live**.

---

## Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| **Double-Click Tile** | Toggle between Single-Camera Full View (`1×1`) and Multi-Camera View |
| **Drag & Drop Tile** | Swap two camera positions in the current layout |
| **`F11` / `F`** | Toggle borderless Full Screen mode |
| **`Esc`** | Exit Full Screen mode |
| **`1` – `9`** | Switch directly to Camera 1–9 in Single View |
| **`G`** | Switch to 4-Camera (`2×2`) Quad Grid View |
| **`S`** | Save PNG Snapshot of the selected camera |
| **Right-Click Tile** | Open channel context menu (Assign Camera, Switch HD/SD, Snapshot, Reconnect) |

---

## Building From Source

- **Build Standalone `.exe`**: Run `build_exe.bat` (outputs to `dist\HikView\HikView.exe`).
- **Build GitHub Release Packages (`HikView-Setup-v1.0.0.exe` + `HikView-Portable-v1.0.0.zip`)**: Run `build_release.bat` (outputs to `releases\`).

---

## License & Author

- **Version**: V1.0.0
- **Developed By**: [LibbyLamarr](https://github.com/LibbyLamarr)
- **License**: Distributed under the [MIT License](LICENSE).
