"""
Real-time low-latency RTSP Video Stream Worker for Hikvision / HiLook cameras.
Runs in a dedicated QThread per camera channel with automatic reconnection,
off-thread hardware-friendly frame scaling, zero-copy QImage buffer wrapping,
latest-frame mailbox delivery, FPS measurement, and main/sub stream switching.
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
    frame_ready = pyqtSignal(int, object)                 # (channel_id, QImage)
    status_changed = pyqtSignal(int, str, str)            # (channel_id, state, message)
    stats_updated = pyqtSignal(int, float, int, int, str) # (channel_id, fps, width, height, stream_type)

    _init_mutex = QMutex()

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
        self._paused = False
        self._pending_frames = 0
        self._frame_in_flight = False
        self._mutex = QMutex()
        self._latest_bgr_frame: Optional[np.ndarray] = None
        self._latest_qimg: Optional[QImage] = None

        # Target viewport hints for off-thread C++ SIMD scaling (0 = unscaled full resolution)
        self._target_width: int = 0
        self._target_height: int = 0
        self._maintain_aspect: bool = True
        self._is_zoomed: bool = False

    def set_target_render_params(
        self,
        width: int,
        height: int,
        maintain_aspect: bool = True,
        is_zoomed: bool = False,
    ):
        """
        Update target display viewport dimensions so the worker thread can scale frames
        off-thread in C++ (with the GIL released), allowing 1:1 blitting on the GUI thread.
        """
        self._target_width = max(0, int(width))
        self._target_height = max(0, int(height))
        self._maintain_aspect = bool(maintain_aspect)
        self._is_zoomed = bool(is_zoomed)

    def set_paused(self, paused: bool):
        """Pause full frame decoding and UI delivery when window is minimized."""
        self._paused = paused
        if not paused:
            with QMutexLocker(self._mutex):
                self._pending_frames = 0
                self._frame_in_flight = False
                self._latest_qimg = None

    def consume_latest_frame(self) -> Optional[QImage]:
        """
        Atomically retrieve the freshest decoded QImage from the mailbox and reset
        in-flight backpressure counters.
        """
        with QMutexLocker(self._mutex):
            qimg = self._latest_qimg
            self._latest_qimg = None
            self._pending_frames = 0
            self._frame_in_flight = False
            return qimg

    def mark_frame_consumed(self):
        """Signal that the UI has processed a pending frame."""
        with QMutexLocker(self._mutex):
            self._latest_qimg = None
            self._pending_frames = 0
            self._frame_in_flight = False

    def update_stream_config(self, rtsp_url: str, stream_type: str, transport: str = "tcp"):
        """Update stream URL/type and trigger a clean reconnect."""
        with QMutexLocker(self._mutex):
            self.rtsp_url = rtsp_url
            self.stream_type = stream_type
            self.transport = transport.lower()
            self._pending_frames = 0
            self._frame_in_flight = False
            self._latest_qimg = None

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Return a copy of the most recent full-resolution BGR frame for high-res snapshots."""
        with QMutexLocker(self._mutex):
            if self._latest_bgr_frame is not None:
                return self._latest_bgr_frame.copy()
            return None

    def request_stop(self):
        """Signal the worker loop to exit without blocking the caller."""
        self._running = False

    def stop(self, wait_ms: int = 1500):
        """Signal the worker loop to exit cleanly and wait up to wait_ms."""
        self._running = False
        if wait_ms > 0:
            self.wait(wait_ms)

    def run(self):
        self._running = True

        while self._running:
            with QMutexLocker(self._mutex):
                current_url = self.rtsp_url
                current_stream_type = self.stream_type
                current_transport = self.transport

            if not current_url:
                self.status_changed.emit(self.channel_id, "disconnected", "No RTSP URL configured")
                break

            self.status_changed.emit(
                self.channel_id,
                "connecting",
                f"Connecting ({current_stream_type.upper()})...",
            )

            # Configure FFmpeg capture options for high throughput, low latency,
            # zero RTP reorder delay, fast keyframe lock, and optimal 2-thread slice decoding.
            capture_options = (
                f"rtsp_transport;{current_transport}"
                f"|buffer_size;1048576"
                f"|max_delay;250000"
                f"|stimeout;5000000"
                f"|fflags;nobuffer+discardcorrupt"
                f"|flags;low_delay"
                f"|reorder_queue_size;0"
                f"|probesize;524288"
                f"|analyzeduration;500000"
                f"|threads;2"
            )

            cap = None
            try:
                with QMutexLocker(RTSPStreamWorker._init_mutex):
                    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = capture_options
                cap = cv2.VideoCapture(current_url, cv2.CAP_FFMPEG)
                if cap.isOpened():
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

                    # When minimized: drain network packets via cap.grab() to keep RTSP in sync
                    # with near-zero CPU and memory consumption.
                    if self._paused:
                        if not cap.grab():
                            break
                        self._sleep_interruptible(0.04)
                        continue

                    # If the UI thread is backed up by 2+ frames (e.g. during OS window drag),
                    # drain packet via cap.grab() to skip YUV->BGR sws_scale and keep latency at zero.
                    if self._pending_frames >= 2:
                        if not cap.grab():
                            break
                        continue

                    ret, frame = cap.read()
                    if not ret or frame is None or frame.size == 0:
                        self.status_changed.emit(
                            self.channel_id,
                            "error",
                            f"Stream interrupted. Reconnecting in {self.reconnect_interval}s...",
                        )
                        break

                    if len(frame.shape) != 3 or frame.shape[2] != 3:
                        continue

                    h, w, _ch = frame.shape

                    # Off-thread C++ SIMD scaling to match the target tile viewport when not digitally zoomed.
                    # This releases the Python GIL and turns GUI thread rendering into a fast 1:1 blit.
                    display_frame = frame
                    tw = self._target_width
                    th = self._target_height
                    if not self._is_zoomed and tw > 32 and th > 32:
                        if self._maintain_aspect:
                            scale = min(tw / w, th / h)
                            dst_w = max(1, int(round(w * scale)))
                            dst_h = max(1, int(round(h * scale)))
                        else:
                            dst_w, dst_h = tw, th

                        if abs(dst_w - w) > 4 or abs(dst_h - h) > 4:
                            display_frame = cv2.resize(
                                frame,
                                (dst_w, dst_h),
                                interpolation=cv2.INTER_LINEAR,
                            )

                    if not display_frame.flags["C_CONTIGUOUS"]:
                        display_frame = np.ascontiguousarray(display_frame)

                    dh, dw, _dch = display_frame.shape
                    bytes_per_line = int(display_frame.strides[0])

                    # Zero-copy QImage construction: wrap numpy buffer directly and bind its lifetime
                    # to the QImage instance via `_frame_ref` (eliminates 5-25MB memcpy per frame).
                    qimg = QImage(display_frame.data, dw, dh, bytes_per_line, QImage.Format.Format_BGR888)
                    qimg._frame_ref = display_frame

                    with QMutexLocker(self._mutex):
                        self._latest_bgr_frame = frame
                        self._latest_qimg = qimg
                        self._pending_frames += 1
                        should_emit = not self._frame_in_flight
                        if should_emit:
                            self._frame_in_flight = True

                    if should_emit:
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
                with QMutexLocker(self._mutex):
                    self._pending_frames = 0
                    self._frame_in_flight = False
                    self._latest_qimg = None
                if cap is not None:
                    cap.release()

            if self._running and (self.rtsp_url == current_url and self.stream_type == current_stream_type):
                self._sleep_interruptible(self.reconnect_interval)

        self.status_changed.emit(self.channel_id, "disconnected", "Disconnected")

    def _sleep_interruptible(self, seconds: float):
        steps = max(1, int(seconds * 10))
        for _ in range(steps):
            if not self._running:
                break
            time.sleep(0.1)
