"""
Real-time low-latency RTSP Video Stream Worker for Hikvision / HiLook cameras.
Runs in a dedicated QThread per camera channel with automatic reconnection,
FPS measurement, resolution detection, and main/sub stream switching.
"""

import os
import time
from typing import Optional
import cv2
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from PyQt6.QtGui import QImage


class RTSPStreamWorker(QThread):
    """
    Background worker thread that connects to a Hikvision/HiLook RTSP stream
    using OpenCV's FFmpeg backend and emits decoded QImages to the UI.
    """
    frame_ready = pyqtSignal(int, QImage)                 # (channel_id, QImage)
    status_changed = pyqtSignal(int, str, str)            # (channel_id, state, message)
    stats_updated = pyqtSignal(int, float, int, int, str) # (channel_id, fps, width, height, stream_type)

    def __init__(
        self,
        channel_id: int,
        rtsp_url: str,
        stream_type: str = "main",
        transport: str = "tcp",
        reconnect_interval: int = 5,
        camera_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.channel_id = channel_id
        self.rtsp_url = rtsp_url
        self.stream_type = stream_type
        self.transport = transport.lower()
        self.reconnect_interval = max(2, reconnect_interval)
        self.camera_name = camera_name or f"CAM {channel_id:02d}"

        self._running = False
        self._mutex = QMutex()
        self._latest_bgr_frame: Optional[np.ndarray] = None

    def update_stream_config(self, rtsp_url: str, stream_type: str, transport: str = "tcp"):
        """Update stream URL/type and trigger a clean reconnect."""
        with QMutexLocker(self._mutex):
            self.rtsp_url = rtsp_url
            self.stream_type = stream_type
            self.transport = transport.lower()

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Return a copy of the most recent BGR frame for high-res snapshots."""
        with QMutexLocker(self._mutex):
            if self._latest_bgr_frame is not None:
                return self._latest_bgr_frame.copy()
            return None

    def stop(self):
        """Signal the worker loop to exit cleanly."""
        self._running = False
        self.wait(2500)

    def run(self):
        self._running = True

        # Configure FFmpeg capture options for clean H.264/H.265 keyframe decoding over TCP
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            f"rtsp_transport;{self.transport}|stimeout;5000000"
        )

        while self._running:
            with QMutexLocker(self._mutex):
                current_url = self.rtsp_url
                current_stream_type = self.stream_type

            if not current_url:
                self.status_changed.emit(self.channel_id, "disconnected", "No RTSP URL configured")
                break

            self.status_changed.emit(
                self.channel_id,
                "connecting",
                f"Connecting ({current_stream_type.upper()})...",
            )

            cap = None
            try:
                cap = cv2.VideoCapture(current_url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                if not cap.isOpened():
                    self.status_changed.emit(
                        self.channel_id,
                        "error",
                        f"Connection failed. Retrying in {self.reconnect_interval}s...",
                    )
                    self._sleep_interruptible(self.reconnect_interval)
                    continue

                self.status_changed.emit(
                    self.channel_id,
                    "connected",
                    f"LIVE ({current_stream_type.upper()})",
                )

                frame_count = 0
                t_start = time.perf_counter()

                while self._running:
                    if self.rtsp_url != current_url or self.stream_type != current_stream_type:
                        break

                    ret, frame = cap.read()
                    if not ret or frame is None or frame.size == 0:
                        self.status_changed.emit(
                            self.channel_id,
                            "error",
                            f"Stream interrupted. Reconnecting in {self.reconnect_interval}s...",
                        )
                        break

                    with QMutexLocker(self._mutex):
                        self._latest_bgr_frame = frame

                    rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    h, w, ch = rgb.shape
                    bytes_per_line = ch * w
                    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
                    self.frame_ready.emit(self.channel_id, qimg)

                    frame_count += 1
                    now = time.perf_counter()
                    elapsed = now - t_start
                    if elapsed >= 1.0:
                        fps = frame_count / elapsed
                        self.stats_updated.emit(self.channel_id, fps, w, h, current_stream_type)
                        frame_count = 0
                        t_start = now

            except Exception as e:
                self.status_changed.emit(self.channel_id, "error", f"Stream error: {e}")
            finally:
                if cap is not None:
                    cap.release()

            if self._running and (self.rtsp_url == current_url and self.stream_type == current_stream_type):
                self._sleep_interruptible(self.reconnect_interval)

        self.status_changed.emit(self.channel_id, "disconnected", "Disconnected")

    def _sleep_interruptible(self, seconds: float):
        steps = int(seconds * 10)
        for _ in range(steps):
            if not self._running:
                break
            time.sleep(0.1)
