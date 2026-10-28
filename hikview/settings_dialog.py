"""
Settings & Connection Dialog for Hikvision, HiLook, OEM NVRs, and ONVIF/RTSP IP Cameras.
Includes Device Brand/Preset selection, live TCP port & ISAPI/CGI auto-discovery,
multi-source Camera Channels management (Primary NVR, Secondary NVR, Standalone IP Camera,
Add/Remove up to 16 cameras), and dynamic layout options.
"""

from copy import deepcopy
import os
from typing import Dict, List, Optional
from urllib.parse import urlparse
import cv2
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTabWidget,
    QWidget,
    QLineEdit,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QPushButton,
    QLabel,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
)

from .config import AppConfig, CameraChannelConfig, DEVICE_PRESETS, format_rtsp_url_by_style
from .isapi import test_tcp_port, query_isapi_device_info, DeviceInfoResult


class ConnectionTesterThread(QThread):
    """Background worker to test NVR TCP ports and query ISAPI/CGI info without freezing the dialog."""
    finished_test = pyqtSignal(bool, str, object)  # (rtsp_ok, summary_text, DeviceInfoResult)

    def __init__(
        self,
        host: str,
        rtsp_port: int,
        http_port: int,
        username: str,
        password: str,
        use_https: bool = False,
        url_style: str = "isapi",
        parent=None,
    ):
        super().__init__(parent)
        self.host = host
        self.rtsp_port = rtsp_port
        self.http_port = http_port
        self.username = username
        self.password = password
        self.use_https = use_https
        self.url_style = url_style

    def run(self):
        rtsp_ok, rtsp_msg = test_tcp_port(self.host, self.rtsp_port, timeout=3.0)
        http_ok, http_msg = test_tcp_port(self.host, self.http_port, timeout=3.0)

        lines = [f"• RTSP ({self.rtsp_port}): {rtsp_msg}", f"• HTTP/S ({self.http_port}): {http_msg}"]
        dev_res = None

        if http_ok:
            dev_res = query_isapi_device_info(
                self.host,
                self.http_port,
                self.username,
                self.password,
                timeout=4.0,
                use_https=self.use_https,
                url_style=self.url_style,
            )
            if dev_res.success:
                lines.append(f"• Device Discovery: SUCCESS — {dev_res.message}")
                if dev_res.channels_discovered:
                    ch_str = ", ".join(f"CH{k}: {v}" for k, v in sorted(dev_res.channels_discovered.items()))
                    lines.append(f"• Discovered Channels ({len(dev_res.channels_discovered)}): {ch_str}")
            else:
                lines.append(f"• Device Info: {dev_res.message}")

        self.finished_test.emit(rtsp_ok, "\n".join(lines), dev_res)


class CameraStreamTesterThread(QThread):
    """Background worker to test an individual camera's TCP port and live RTSP video stream decoding."""
    finished_test = pyqtSignal(bool, str)  # (ok, summary_text)

    def __init__(
        self,
        host: str,
        port: int,
        main_rtsp_url: str,
        sub_rtsp_url: str,
        transport: str = "tcp",
        parent=None,
    ):
        super().__init__(parent)
        self.host = host.strip()
        self.port = int(port) if port > 0 else 554
        self.main_rtsp_url = main_rtsp_url.strip()
        self.sub_rtsp_url = sub_rtsp_url.strip()
        self.transport = transport.lower()

    def run(self):
        # Extract host/port from custom RTSP URL if user entered a full rtsp:// override
        target_host = self.host
        target_port = self.port
        if self.main_rtsp_url.lower().startswith("rtsp://"):
            try:
                parsed = urlparse(self.main_rtsp_url)
                if parsed.hostname:
                    target_host = parsed.hostname
                if parsed.port:
                    target_port = parsed.port
            except Exception:
                pass

        if not target_host:
            self.finished_test.emit(False, "• Error: Camera / NVR IP address or RTSP URL is empty.")
            return

        tcp_ok, tcp_msg = test_tcp_port(target_host, target_port, timeout=3.0)
        lines = [f"• RTSP TCP ({target_host}:{target_port}): {tcp_msg}"]

        if not tcp_ok:
            self.finished_test.emit(False, "\n".join(lines))
            return

        if not self.main_rtsp_url:
            self.finished_test.emit(False, "\n".join(lines + ["• No RTSP URL generated."]))
            return

        # Test opening the RTSP stream and decoding 1 video frame via OpenCV FFmpeg
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = f"rtsp_transport;{self.transport}|stimeout;4000000"
        cap = None
        stream_ok = False
        try:
            cap = cv2.VideoCapture(self.main_rtsp_url, cv2.CAP_FFMPEG)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    h, w = frame.shape[:2]
                    stream_ok = True
                    lines.append(f"• Live Video Stream: SUCCESS — Decoded HD frame ({w}×{h}) via {self.transport.upper()}")
                else:
                    lines.append("• Live Video Stream: Connected to RTSP server, but no video frame received (check channel/path).")
            else:
                lines.append(
                    "• Live Video Stream: Failed to open RTSP stream (check username, password, or RTSP URL path)."
                )
        except Exception as e:
            lines.append(f"• Live Video Stream Error: {e}")
        finally:
            if cap is not None:
                cap.release()

        self.finished_test.emit(stream_ok, "\n".join(lines))


class CameraSourcePanel(QWidget):
    """Inline sub-page inside the Cameras & Sources tab to configure a single camera's source without opening a separate window."""
    applied = pyqtSignal(object)  # emits updated CameraChannelConfig
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ch_cfg: Optional[CameraChannelConfig] = None
        self.primary_config: Optional[AppConfig] = None
        self._stream_tester: Optional[CameraStreamTesterThread] = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        # Header bar with Back button
        hdr_row = QHBoxLayout()
        self.btn_back = QPushButton("← Back to Cameras List")
        self.btn_back.clicked.connect(self.cancelled.emit)
        hdr_row.addWidget(self.btn_back)

        self.lbl_title = QLabel("Configure Camera Source")
        self.lbl_title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: 700; padding-left: 10px;")
        hdr_row.addWidget(self.lbl_title)
        hdr_row.addStretch()

        self.btn_apply_top = QPushButton("Apply Source Settings")
        self.btn_apply_top.setObjectName("primaryBtn")
        self.btn_apply_top.clicked.connect(self._on_apply)
        hdr_row.addWidget(self.btn_apply_top)
        layout.addLayout(hdr_row)

        self.grp = QGroupBox("Camera Source Settings")
        form = QFormLayout(self.grp)
        form.setSpacing(10)

        self.edit_name = QLineEdit()
        form.addRow("Camera Name:", self.edit_name)

        self.combo_source = QComboBox()
        self.combo_source.addItem("Primary NVR / Recorder (Uses Tab 1 Connection)", "primary_nvr")
        self.combo_source.addItem("Secondary NVR / Recorder (Different NVR IP / Brand)", "secondary_nvr")
        self.combo_source.addItem("Standalone IP Camera / ONVIF / Custom RTSP URL", "standalone")
        self.combo_source.currentIndexChanged.connect(self._on_source_type_changed)
        form.addRow("Camera Source Type:", self.combo_source)

        self.spin_remote_ch = QSpinBox()
        self.spin_remote_ch.setRange(1, 64)
        self.spin_remote_ch.valueChanged.connect(self._update_preview)
        self.lbl_remote_ch = QLabel("NVR Channel Number:")
        form.addRow(self.lbl_remote_ch, self.spin_remote_ch)

        # Custom Host / Brand / Credentials container (shown for Secondary NVR or Standalone IP Camera)
        self.custom_container = QWidget()
        c_form = QFormLayout(self.custom_container)
        c_form.setContentsMargins(0, 4, 0, 0)
        c_form.setSpacing(10)

        self.combo_brand = QComboBox()
        for key, label in DEVICE_PRESETS:
            self.combo_brand.addItem(label, key)
        self.combo_brand.currentIndexChanged.connect(self._update_preview)
        c_form.addRow("Device Brand / RTSP Format:", self.combo_brand)

        host_row = QHBoxLayout()
        self.edit_custom_host = QLineEdit()
        self.edit_custom_host.setPlaceholderText("e.g. 192.168.1.105")
        self.edit_custom_host.textChanged.connect(self._update_preview)
        host_row.addWidget(self.edit_custom_host, stretch=1)

        host_row.addSpacing(10)
        host_row.addWidget(QLabel("RTSP Port:"))
        self.spin_custom_port = QSpinBox()
        self.spin_custom_port.setRange(1, 65535)
        self.spin_custom_port.setValue(554)
        self.spin_custom_port.valueChanged.connect(self._update_preview)
        host_row.addWidget(self.spin_custom_port)
        c_form.addRow("Camera / NVR IP Address:", host_row)

        cred_row = QHBoxLayout()
        self.edit_custom_user = QLineEdit()
        self.edit_custom_user.setPlaceholderText("Leave blank to use Primary NVR username")
        self.edit_custom_user.textChanged.connect(self._update_preview)
        cred_row.addWidget(self.edit_custom_user)

        self.edit_custom_pass = QLineEdit()
        self.edit_custom_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_custom_pass.setPlaceholderText("Password")
        self.edit_custom_pass.textChanged.connect(self._update_preview)
        cred_row.addWidget(self.edit_custom_pass)

        self.chk_show_pass = QCheckBox("Show")
        self.chk_show_pass.toggled.connect(
            lambda checked: self.edit_custom_pass.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        cred_row.addWidget(self.chk_show_pass)
        c_form.addRow("Username & Password:", cred_row)

        self.edit_main_url = QLineEdit()
        self.edit_main_url.setPlaceholderText("Optional: Full rtsp:// override for Main Stream (HD)")
        self.edit_main_url.textChanged.connect(self._update_preview)
        c_form.addRow("Custom Main RTSP URL:", self.edit_main_url)

        self.edit_sub_url = QLineEdit()
        self.edit_sub_url.setPlaceholderText("Optional: Full rtsp:// override for Sub Stream (SD)")
        self.edit_sub_url.textChanged.connect(self._update_preview)
        c_form.addRow("Custom Sub RTSP URL:", self.edit_sub_url)

        form.addRow(self.custom_container)
        layout.addWidget(self.grp)

        # Live URL Preview & Connection Test
        grp_prev = QGroupBox("Effective RTSP Stream Preview & Live Connection Test")
        prev_layout = QVBoxLayout(grp_prev)
        self.lbl_preview = QLabel()
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; color: #8ec5fe; "
            "background-color: #0e121a; padding: 8px; border-radius: 4px; border: 1px solid #252e3f;"
        )
        prev_layout.addWidget(self.lbl_preview)

        test_row = QHBoxLayout()
        self.btn_test_cam = QPushButton("Test Camera Stream")
        self.btn_test_cam.setToolTip("Verify TCP port reachability and decode a live test frame from this camera")
        self.btn_test_cam.clicked.connect(self._run_camera_stream_test)
        test_row.addWidget(self.btn_test_cam)

        self.lbl_cam_test_result = QLabel("Click 'Test Camera Stream' to verify this camera's RTSP feed before saving.")
        self.lbl_cam_test_result.setWordWrap(True)
        self.lbl_cam_test_result.setStyleSheet("color: #9aa4b8; font-size: 12px; padding-left: 8px;")
        test_row.addWidget(self.lbl_cam_test_result, stretch=1)
        prev_layout.addLayout(test_row)

        layout.addWidget(grp_prev)
        layout.addStretch()

    def load_camera(self, ch_cfg: CameraChannelConfig, primary_config: AppConfig):
        self.ch_cfg = deepcopy(ch_cfg)
        self.primary_config = primary_config
        self.lbl_title.setText(f"Configure Camera CH{ch_cfg.channel_id:02d} — {ch_cfg.name}")
        self.grp.setTitle(f"Camera CH{ch_cfg.channel_id:02d} Source & Stream Settings")
        self.btn_test_cam.setEnabled(True)
        self.lbl_cam_test_result.setStyleSheet("color: #9aa4b8; font-size: 12px; padding-left: 8px;")
        self.lbl_cam_test_result.setText("Click 'Test Camera Stream' to verify this camera's RTSP feed before saving.")

        self.edit_name.setText(self.ch_cfg.name)
        idx_src = self.combo_source.findData(self.ch_cfg.source_type)
        if idx_src >= 0:
            self.combo_source.setCurrentIndex(idx_src)

        self.spin_remote_ch.setValue(
            self.ch_cfg.remote_channel_id if self.ch_cfg.remote_channel_id > 0 else self.ch_cfg.channel_id
        )

        idx_brand = self.combo_brand.findData(self.ch_cfg.custom_brand)
        if idx_brand >= 0:
            self.combo_brand.setCurrentIndex(idx_brand)

        self.edit_custom_host.setText(self.ch_cfg.custom_host)
        self.spin_custom_port.setValue(self.ch_cfg.custom_port if self.ch_cfg.custom_port > 0 else 554)
        self.edit_custom_user.setText(self.ch_cfg.custom_username)
        self.edit_custom_pass.setText(self.ch_cfg.custom_password)
        self.edit_main_url.setText(self.ch_cfg.custom_rtsp_url)
        self.edit_sub_url.setText(self.ch_cfg.custom_sub_rtsp_url)

        self._on_source_type_changed()

    def _on_source_type_changed(self):
        src = self.combo_source.currentData()
        is_primary = (src == "primary_nvr")
        is_standalone = (src == "standalone")

        self.custom_container.setVisible(not is_primary)
        self.lbl_remote_ch.setVisible(not is_standalone)
        self.spin_remote_ch.setVisible(not is_standalone)
        self._update_preview()

    def _build_temp_config(self) -> CameraChannelConfig:
        cid = self.ch_cfg.channel_id if self.ch_cfg else 1
        enabled = self.ch_cfg.enabled if self.ch_cfg else True
        pref_stream = self.ch_cfg.preferred_stream if self.ch_cfg else "auto"
        src = self.combo_source.currentData()
        return CameraChannelConfig(
            channel_id=cid,
            name=self.edit_name.text().strip() or f"Camera {cid:02d}",
            enabled=enabled,
            source_type=src,
            remote_channel_id=self.spin_remote_ch.value(),
            use_custom_host=(src != "primary_nvr"),
            custom_brand=self.combo_brand.currentData(),
            custom_host=self.edit_custom_host.text().strip(),
            custom_port=self.spin_custom_port.value(),
            custom_username=self.edit_custom_user.text().strip(),
            custom_password=self.edit_custom_pass.text(),
            custom_rtsp_url=self.edit_main_url.text().strip(),
            custom_sub_rtsp_url=self.edit_sub_url.text().strip(),
            preferred_stream=pref_stream,
        )

    def _update_preview(self):
        if not self.primary_config:
            return
        tmp = self._build_temp_config()
        main_u = tmp.build_rtsp_url(
            nvr_host=self.primary_config.nvr_host or "<nvr-ip>",
            nvr_rtsp_port=self.primary_config.nvr_rtsp_port,
            nvr_username=self.primary_config.nvr_username or "admin",
            nvr_password="••••••" if self.primary_config.nvr_password else "<password>",
            stream_type="main",
            url_style=self.primary_config.url_style,
        )
        sub_u = tmp.build_rtsp_url(
            nvr_host=self.primary_config.nvr_host or "<nvr-ip>",
            nvr_rtsp_port=self.primary_config.nvr_rtsp_port,
            nvr_username=self.primary_config.nvr_username or "admin",
            nvr_password="••••••" if self.primary_config.nvr_password else "<password>",
            stream_type="sub",
            url_style=self.primary_config.url_style,
        )
        self.lbl_preview.setText(f"Main Stream (HD):  {main_u}\nSub Stream  (SD):  {sub_u}")

    def _run_camera_stream_test(self):
        if not self.primary_config:
            return
        tmp = self._build_temp_config()
        real_main_url = tmp.build_rtsp_url(
            nvr_host=self.primary_config.nvr_host,
            nvr_rtsp_port=self.primary_config.nvr_rtsp_port,
            nvr_username=self.primary_config.nvr_username,
            nvr_password=self.primary_config.nvr_password,
            stream_type="main",
            url_style=self.primary_config.url_style,
        )
        real_sub_url = tmp.build_rtsp_url(
            nvr_host=self.primary_config.nvr_host,
            nvr_rtsp_port=self.primary_config.nvr_rtsp_port,
            nvr_username=self.primary_config.nvr_username,
            nvr_password=self.primary_config.nvr_password,
            stream_type="sub",
            url_style=self.primary_config.url_style,
        )

        if tmp.source_type == "primary_nvr":
            target_host = self.primary_config.nvr_host
            target_port = self.primary_config.nvr_rtsp_port
        else:
            target_host = tmp.custom_host or self.primary_config.nvr_host
            target_port = tmp.custom_port if tmp.custom_port > 0 else self.primary_config.nvr_rtsp_port

        self.btn_test_cam.setEnabled(False)
        self.lbl_cam_test_result.setStyleSheet("color: #f0b44c; font-size: 12px; padding-left: 8px;")
        self.lbl_cam_test_result.setText("Testing TCP connection and decoding live RTSP video stream...")

        self._stream_tester = CameraStreamTesterThread(
            host=target_host,
            port=target_port,
            main_rtsp_url=real_main_url,
            sub_rtsp_url=real_sub_url,
            transport=self.primary_config.rtsp_transport,
            parent=self,
        )
        self._stream_tester.finished_test.connect(self._on_camera_stream_test_finished)
        self._stream_tester.start()

    def _on_camera_stream_test_finished(self, ok: bool, summary: str):
        self.btn_test_cam.setEnabled(True)
        color = "#2ecc71" if ok else "#f06565"
        self.lbl_cam_test_result.setStyleSheet(f"color: {color}; font-size: 12px; padding-left: 8px;")
        self.lbl_cam_test_result.setText(summary)

    def _on_apply(self):
        updated = self._build_temp_config()
        self.applied.emit(updated)


class SettingsDialog(QDialog):
    """Modal configuration dialog for NVR connection, multi-source Camera channels, and Viewer preferences."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HikView Settings — NVRs, ONVIF & RTSP Cameras")
        self.setMinimumSize(860, 600)
        self.config = deepcopy(config)
        self._tester_thread = None

        self._apply_dialog_theme()
        self._build_ui()
        self._load_from_config()
        self._update_url_preview()

    def _apply_dialog_theme(self):
        self.setStyleSheet(
            """
            QDialog {
                background-color: #141820;
                color: #e4e8f0;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QTabWidget::pane {
                border: 1px solid #283040;
                background-color: #181d27;
                border-radius: 6px;
            }
            QTabBar::tab {
                background-color: #1d2330;
                color: #9aa4b8;
                padding: 9px 18px;
                margin-right: 4px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background-color: #e03e3e;
                color: #ffffff;
            }
            QGroupBox {
                border: 1px solid #2b3344;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 14px;
                font-weight: 600;
                color: #d5dce8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #10141c;
                border: 1px solid #2f384a;
                border-radius: 4px;
                padding: 6px 8px;
                color: #edf0f7;
                selection-background-color: #e03e3e;
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 1px solid #e03e3e;
            }
            QPushButton {
                background-color: #252c3b;
                color: #e4e8f0;
                border: 1px solid #364054;
                border-radius: 4px;
                padding: 7px 15px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #30394d;
            }
            QPushButton#primaryBtn {
                background-color: #e03e3e;
                border: 1px solid #e03e3e;
                color: #ffffff;
            }
            QPushButton#primaryBtn:hover {
                background-color: #c93232;
            }
            QTableWidget {
                background-color: #11151d;
                gridline-color: #262e3d;
                color: #e4e8f0;
                border: 1px solid #2a3242;
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: #1d2330;
                color: #b8c2d4;
                padding: 6px;
                border: 1px solid #2a3242;
                font-weight: 600;
            }
            QCheckBox {
                spacing: 8px;
                color: #d8dfe9;
            }
            """
        )

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        # Tab 1: NVR Connection & Device Preset
        self.tab_nvr = QWidget()
        self._build_nvr_tab(self.tab_nvr)
        self.tabs.addTab(self.tab_nvr, "Primary NVR / Device Connection")

        # Tab 2: Camera Channels & Multi-Source Setup
        self.tab_channels = QWidget()
        self._build_channels_tab(self.tab_channels)
        self.tabs.addTab(self.tab_channels, "Cameras & Sources")

        # Tab 3: Display & Streaming Options
        self.tab_prefs = QWidget()
        self._build_prefs_tab(self.tab_prefs)
        self.tabs.addTab(self.tab_prefs, "Streaming & Display")

        # Tab 4: About
        self.tab_about = QWidget()
        self._build_about_tab(self.tab_about)
        self.tabs.addTab(self.tab_about, "About")

        # Bottom Dialog Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Save & Apply")
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)

        root_layout.addLayout(btn_row)

    def _build_nvr_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        grp_conn = QGroupBox("Primary NVR / Recorder or Camera System")
        form = QFormLayout(grp_conn)
        form.setSpacing(10)

        self.combo_url_style = QComboBox()
        for key, label in DEVICE_PRESETS:
            self.combo_url_style.addItem(label, key)
        self.combo_url_style.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("Device Brand / Type:", self.combo_url_style)

        self.edit_device_model = QLineEdit()
        self.edit_device_model.setPlaceholderText("e.g. HiLook NVR-104H-D/4P, Hikvision DS-7608NI, or Home System")
        form.addRow("System / Model Label:", self.edit_device_model)

        self.edit_host = QLineEdit()
        self.edit_host.setPlaceholderText("e.g. 192.168.1.64 or nvr.local")
        self.edit_host.textChanged.connect(self._update_url_preview)
        form.addRow("Primary NVR / Host IP:", self.edit_host)

        ports_row = QHBoxLayout()
        self.spin_rtsp_port = QSpinBox()
        self.spin_rtsp_port.setRange(1, 65535)
        self.spin_rtsp_port.setValue(554)
        self.spin_rtsp_port.valueChanged.connect(self._update_url_preview)
        ports_row.addWidget(QLabel("RTSP Port:"))
        ports_row.addWidget(self.spin_rtsp_port)

        ports_row.addSpacing(18)

        self.spin_http_port = QSpinBox()
        self.spin_http_port.setRange(1, 65535)
        self.spin_http_port.setValue(80)
        ports_row.addWidget(QLabel("HTTP / Web Port:"))
        ports_row.addWidget(self.spin_http_port)

        ports_row.addSpacing(14)
        self.chk_https = QCheckBox("Use HTTPS")
        self.chk_https.toggled.connect(self._on_https_toggled)
        ports_row.addWidget(self.chk_https)
        ports_row.addStretch()
        form.addRow("Service Ports:", ports_row)

        self.edit_user = QLineEdit()
        self.edit_user.setPlaceholderText("admin")
        self.edit_user.textChanged.connect(self._update_url_preview)
        form.addRow("Username:", self.edit_user)

        pass_row = QHBoxLayout()
        self.edit_pass = QLineEdit()
        self.edit_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_pass.setPlaceholderText("Enter NVR / Camera password")
        self.edit_pass.textChanged.connect(self._update_url_preview)
        pass_row.addWidget(self.edit_pass)

        self.chk_show_pass = QCheckBox("Show")
        self.chk_show_pass.toggled.connect(
            lambda checked: self.edit_pass.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        pass_row.addWidget(self.chk_show_pass)
        form.addRow("Password:", pass_row)

        layout.addWidget(grp_conn)

        # RTSP URL Preview Box
        grp_preview = QGroupBox("Generated RTSP Stream Preview (Channel 1)")
        prev_layout = QVBoxLayout(grp_preview)
        self.lbl_url_preview = QLabel()
        self.lbl_url_preview.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; color: #8ec5fe; "
            "background-color: #0e121a; padding: 8px; border-radius: 4px; border: 1px solid #252e3f;"
        )
        self.lbl_url_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        prev_layout.addWidget(self.lbl_url_preview)
        layout.addWidget(grp_preview)

        # Diagnostics & Discovery Box
        grp_test = QGroupBox("Connection Test & Channel Auto-Discovery")
        test_layout = QVBoxLayout(grp_test)

        btn_test_row = QHBoxLayout()
        self.btn_test_conn = QPushButton("Test Connection & Auto-Discover Cameras")
        self.btn_test_conn.clicked.connect(self._run_connection_test)
        btn_test_row.addWidget(self.btn_test_conn)
        btn_test_row.addStretch()
        test_layout.addLayout(btn_test_row)

        self.lbl_test_result = QLabel(
            "Click 'Test Connection' to verify RTSP port 554 and auto-discover NVR camera channels & model info."
        )
        self.lbl_test_result.setWordWrap(True)
        self.lbl_test_result.setStyleSheet("color: #9aa4b8; font-size: 12px; padding-top: 4px;")
        test_layout.addWidget(self.lbl_test_result)

        layout.addWidget(grp_test)
        layout.addStretch()

    def _build_channels_tab(self, parent: QWidget):
        root_layout = QVBoxLayout(parent)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(0)

        self.channels_stack = QStackedWidget()
        root_layout.addWidget(self.channels_stack)

        # Page 0: Camera Channels Table View
        self.page_channels_list = QWidget()
        layout = QVBoxLayout(self.page_channels_list)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        info_lbl = QLabel(
            "Manage your NVR channels and standalone ONVIF/RTSP cameras (up to 16 cameras).\n"
            "Click 'Configure' on any row to connect that slot to a Secondary NVR or a Standalone IP Camera.\n"
            "Main screen layout options automatically adapt to the number of cameras configured here."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #9aa4b8; font-size: 12px;")
        top_row.addWidget(info_lbl, stretch=1)
        layout.addLayout(top_row)

        # Toolbar for adding/removing cameras
        toolbar_row = QHBoxLayout()
        self.btn_add_cam = QPushButton("+ Add Camera")
        self.btn_add_cam.setToolTip("Add a new NVR channel or standalone RTSP/ONVIF camera (up to 16)")
        self.btn_add_cam.clicked.connect(self._on_add_camera_clicked)
        toolbar_row.addWidget(self.btn_add_cam)

        self.btn_remove_cam = QPushButton("− Remove Selected")
        self.btn_remove_cam.setToolTip("Remove the selected camera row (minimum 1 camera)")
        self.btn_remove_cam.clicked.connect(self._on_remove_camera_clicked)
        toolbar_row.addWidget(self.btn_remove_cam)

        toolbar_row.addStretch()
        self.lbl_cam_count_summary = QLabel()
        self.lbl_cam_count_summary.setStyleSheet("color: #8ec5fe; font-size: 12px; font-weight: 600;")
        toolbar_row.addWidget(self.lbl_cam_count_summary)
        layout.addLayout(toolbar_row)

        self.table_channels = QTableWidget(0, 6)
        self.table_channels.setHorizontalHeaderLabels(
            ["Enabled", "ID", "Camera Name", "Stream Mode", "Camera Source Summary", "Source Setup"]
        )
        self.table_channels.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_channels.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table_channels.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table_channels.setColumnWidth(2, 175)
        self.table_channels.verticalHeader().setVisible(False)

        layout.addWidget(self.table_channels, stretch=1)
        self.channels_stack.addWidget(self.page_channels_list)

        # Page 1: Inline Camera Source Configuration Panel (no nested modal window!)
        self._editing_channel_row: int = -1
        self.source_panel = CameraSourcePanel(self)
        self.source_panel.applied.connect(self._on_source_panel_applied)
        self.source_panel.cancelled.connect(self._on_source_panel_cancelled)
        self.channels_stack.addWidget(self.source_panel)

    def _build_prefs_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        grp_stream = QGroupBox("RTSP Streaming & Performance")
        s_form = QFormLayout(grp_stream)
        s_form.setSpacing(10)

        self.combo_transport = QComboBox()
        self.combo_transport.addItem("TCP (Recommended — Prevents packet loss & grey artifacts)", "tcp")
        self.combo_transport.addItem("UDP (Lower latency on local wired LAN)", "udp")
        s_form.addRow("RTSP Transport Protocol:", self.combo_transport)

        self.chk_auto_substream = QCheckBox(
            "Automatically use Sub-Stream (SD) in Multi-Camera Views and Main-Stream (HD) in Single / Focus View"
        )
        s_form.addRow("", self.chk_auto_substream)

        self.spin_reconnect = QSpinBox()
        self.spin_reconnect.setRange(2, 60)
        self.spin_reconnect.setSuffix(" seconds")
        s_form.addRow("Auto-Reconnect Interval:", self.spin_reconnect)

        layout.addWidget(grp_stream)

        grp_ui = QGroupBox("Display & Startup Preferences")
        u_form = QFormLayout(grp_ui)
        u_form.setSpacing(10)

        self.combo_default_layout = QComboBox()
        u_form.addRow("Default Startup Layout:", self.combo_default_layout)

        self.chk_auto_connect = QCheckBox("Automatically connect to NVR/Cameras on application startup")
        u_form.addRow("", self.chk_auto_connect)

        self.chk_always_on_top = QCheckBox("Keep application window always on top (Always on Top)")
        u_form.addRow("", self.chk_always_on_top)

        self.chk_aspect_ratio = QCheckBox("Maintain 16:9 / 4:3 video aspect ratio inside camera tiles")
        u_form.addRow("", self.chk_aspect_ratio)

        self.chk_show_osd = QCheckBox("Show camera name, live status indicator, resolution, and FPS on hover")
        u_form.addRow("", self.chk_show_osd)

        layout.addWidget(grp_ui)

        grp_snap = QGroupBox("Snapshots")
        sn_form = QFormLayout(grp_snap)
        sn_form.setSpacing(10)

        snap_row = QHBoxLayout()
        self.edit_snap_dir = QLineEdit()
        self.edit_snap_dir.setPlaceholderText("Select folder where camera snapshots will be saved...")
        snap_row.addWidget(self.edit_snap_dir)
        btn_browse = QPushButton("Browse Folder...")
        btn_browse.clicked.connect(self._browse_snapshot_dir)
        snap_row.addWidget(btn_browse)
        sn_form.addRow("Snapshot Save Location:", snap_row)

        layout.addWidget(grp_snap)
        layout.addStretch()

    def _build_about_tab(self, parent: QWidget):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        grp_app = QGroupBox("About HikView")
        app_layout = QVBoxLayout(grp_app)
        app_layout.setSpacing(8)

        lbl_header = QLabel(
            "<span style='font-size: 16px; font-weight: 700; color: #ffffff;'>HikView</span> "
            "<span style='font-size: 13px; font-weight: 600; color: #e03e3e; padding-left: 6px;'>V1.0.0</span>"
        )
        lbl_header.setTextFormat(Qt.TextFormat.RichText)
        app_layout.addWidget(lbl_header)

        lbl_desc = QLabel(
            "HikView is a fast, lightweight Windows desktop application designed for low-latency live viewing "
            "of Network Video Recorders (NVRs) and standalone IP cameras. Built as a responsive, streamlined "
            "alternative to heavy surveillance suites, it supports up to 16 simultaneous camera channels with "
            "adaptive multi-camera grid and focus layouts, automatic HD/SD stream switching, ISAPI/CGI device "
            "discovery, and instant PNG snapshots."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #d5dce8; font-size: 12px; line-height: 1.4;")
        app_layout.addWidget(lbl_desc)

        meta_form = QFormLayout()
        meta_form.setContentsMargins(0, 6, 0, 0)
        meta_form.setSpacing(6)

        lbl_version = QLabel("V1.0.0")
        lbl_version.setStyleSheet("color: #ffffff; font-weight: 600;")
        meta_form.addRow("Version:", lbl_version)

        lbl_author = QLabel("LibbyLamarr")
        lbl_author.setStyleSheet("color: #ffffff; font-weight: 600;")
        meta_form.addRow("Developed By:", lbl_author)

        lbl_license = QLabel("Distributed under the MIT License")
        lbl_license.setStyleSheet("color: #d5dce8;")
        meta_form.addRow("License:", lbl_license)

        lbl_github = QLabel(
            "<a href='https://github.com/LibbyLamarr/HikView' style='color: #8ec5fe; text-decoration: none;'>"
            "https://github.com/LibbyLamarr/HikView</a>"
        )
        lbl_github.setTextFormat(Qt.TextFormat.RichText)
        lbl_github.setOpenExternalLinks(True)
        lbl_github.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        meta_form.addRow("GitHub Repository:", lbl_github)

        app_layout.addLayout(meta_form)
        layout.addWidget(grp_app)

        grp_compat = QGroupBox("Supported NVRs & IP Cameras")
        compat_layout = QVBoxLayout(grp_compat)
        compat_layout.setSpacing(6)

        lbl_compat = QLabel(
            "HikView works with a wide range of NVRs and standalone IP cameras supporting RTSP, ISAPI, CGI, or ONVIF:\n\n"
            "• Hikvision & HiLook NVRs / IP Cameras — Full support for ISAPI RTSP streaming (/Streaming/Channels/XY) "
            "and HTTP Digest auto-discovery (including HiLook NVR-104H-D/4P, NVR-108H/208M, and Hikvision DS-76xx / DS-77xx series).\n"
            "• Hikvision / HiLook Legacy Firmware — Supports older recorders and cameras using /h264/chX/main/av_stream paths.\n"
            "• Dahua, Amcrest & Lorex NVRs / Cameras — Built-in RTSP preset (/cam/realmonitor) and CGI device discovery.\n"
            "• Reolink NVRs & IP Cameras — Native preset for Main and Sub RTSP streams (/h264Preview_XX_main).\n"
            "• Uniview (UNV) & Standard ONVIF Devices — Compatible with UNV recorders and standard ONVIF unicast streams.\n"
            "• TP-Link Tapo & VIGI Cameras — Built-in preset for /stream1 (HD) and /stream2 (SD) RTSP feeds.\n"
            "• Multi-Source & Custom RTSP Feeds — Mix and match channels from a Primary NVR, Secondary NVR, "
            "or standalone custom RTSP:// cameras simultaneously in the same view."
        )
        lbl_compat.setWordWrap(True)
        lbl_compat.setStyleSheet("color: #c8d1e0; font-size: 12px;")
        compat_layout.addWidget(lbl_compat)

        layout.addWidget(grp_compat)
        layout.addStretch()

    def _on_preset_changed(self):
        self._update_url_preview()

    def _on_https_toggled(self, checked: bool):
        if checked and self.spin_http_port.value() == 80:
            self.spin_http_port.setValue(443)
        elif not checked and self.spin_http_port.value() == 443:
            self.spin_http_port.setValue(80)

    def _format_source_summary(self, ch: CameraChannelConfig) -> str:
        if ch.source_type == "primary_nvr" and not ch.use_custom_host and not ch.custom_rtsp_url.strip():
            rem = ch.remote_channel_id if ch.remote_channel_id > 0 else ch.channel_id
            return f"Primary NVR (Channel {rem})"
        elif ch.source_type == "secondary_nvr":
            host = ch.custom_host or "<nvr-ip>"
            rem = ch.remote_channel_id if ch.remote_channel_id > 0 else 1
            return f"Secondary NVR ({host}:{ch.custom_port} • Ch {rem})"
        else:
            if ch.custom_rtsp_url.strip():
                return f"Custom RTSP ({ch.custom_rtsp_url.strip()})"
            host = ch.custom_host or "<camera-ip>"
            return f"Standalone IP Cam ({host}:{ch.custom_port} • {ch.custom_brand.upper()})"

    def _sync_channels_from_table_ui(self):
        """Read current enabled checkboxes, names, and stream modes from the table into `self.config.channels`."""
        for row in range(min(self.table_channels.rowCount(), len(self.config.channels))):
            ch = self.config.channels[row]
            chk_widget = self.table_channels.cellWidget(row, 0)
            chk = chk_widget.findChild(QCheckBox) if chk_widget else None
            if chk is not None:
                ch.enabled = chk.isChecked()
            name_item = self.table_channels.item(row, 2)
            if name_item is not None:
                ch.name = name_item.text().strip() or f"Camera {ch.channel_id:02d}"
            combo_s = self.table_channels.cellWidget(row, 3)
            if combo_s is not None:
                ch.preferred_stream = combo_s.currentData()

    def _rebuild_channels_table(self):
        self.table_channels.setRowCount(len(self.config.channels))
        for row, ch in enumerate(self.config.channels):
            # Col 0: Enabled checkbox
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()
            chk.setChecked(ch.enabled)
            chk.toggled.connect(lambda _c: self._update_dynamic_layout_choices())
            chk_layout.addWidget(chk)
            self.table_channels.setCellWidget(row, 0, chk_widget)

            # Col 1: Channel ID label
            item_ch = QTableWidgetItem(f"CH {ch.channel_id:02d}")
            item_ch.setFlags(item_ch.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_ch.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_channels.setItem(row, 1, item_ch)

            # Col 2: Camera Name
            item_name = QTableWidgetItem(ch.name)
            self.table_channels.setItem(row, 2, item_name)

            # Col 3: Stream Mode preference
            combo_s = QComboBox()
            combo_s.addItem("Auto (SD in Multi, HD in Focus/Single)", "auto")
            combo_s.addItem("Always Main Stream (HD)", "main")
            combo_s.addItem("Always Sub Stream (SD)", "sub")
            s_idx = combo_s.findData(ch.preferred_stream)
            if s_idx >= 0:
                combo_s.setCurrentIndex(s_idx)
            self.table_channels.setCellWidget(row, 3, combo_s)

            # Col 4: Source Summary (read-only)
            item_src = QTableWidgetItem(self._format_source_summary(ch))
            item_src.setFlags(item_src.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_src.setToolTip("Click 'Configure' to change NVR, IP address, or custom RTSP URL.")
            self.table_channels.setItem(row, 4, item_src)

            # Col 5: Configure Source button
            btn_cfg = QPushButton("Configure")
            btn_cfg.clicked.connect(lambda _chk=False, r=row: self._open_camera_source_dialog(r))
            self.table_channels.setCellWidget(row, 5, btn_cfg)

        self.btn_add_cam.setEnabled(len(self.config.channels) < 16)
        self.btn_remove_cam.setEnabled(len(self.config.channels) > 1)
        self._update_dynamic_layout_choices()

    def _update_dynamic_layout_choices(self):
        """Refresh the Default Startup Layout dropdown and camera summary label based on configured/enabled cameras."""
        self._sync_channels_from_table_ui()
        avail_layouts = self.config.get_available_layouts()
        enabled_cnt = sum(1 for c in self.config.channels if c.enabled)
        total_cnt = len(self.config.channels)
        layout_names = ", ".join(lbl for lbl, _ in avail_layouts)
        self.lbl_cam_count_summary.setText(
            f"{enabled_cnt}/{total_cnt} Active • Available Layouts: {layout_names}"
        )

        current_default = self.combo_default_layout.currentData()
        if current_default is None:
            current_default = self.config.default_layout

        self.combo_default_layout.blockSignals(True)
        self.combo_default_layout.clear()
        for label, code in avail_layouts:
            self.combo_default_layout.addItem(label, code)
        idx = self.combo_default_layout.findData(current_default)
        if idx >= 0:
            self.combo_default_layout.setCurrentIndex(idx)
        else:
            idx_quad = self.combo_default_layout.findData(4)
            self.combo_default_layout.setCurrentIndex(max(0, idx_quad))
        self.combo_default_layout.blockSignals(False)

    def _open_camera_source_dialog(self, row: int):
        self._sync_channels_from_table_ui()
        if row < 0 or row >= len(self.config.channels):
            return

        # Sync current Tab 1 & Tab 3 fields so preview and stream test in sub-panel are accurate
        self.config.nvr_host = self.edit_host.text().strip()
        self.config.nvr_rtsp_port = self.spin_rtsp_port.value()
        self.config.nvr_username = self.edit_user.text().strip()
        self.config.nvr_password = self.edit_pass.text()
        self.config.url_style = self.combo_url_style.currentData()
        self.config.rtsp_transport = self.combo_transport.currentData() or "tcp"

        self._editing_channel_row = row
        self.source_panel.load_camera(self.config.channels[row], self.config)
        self.channels_stack.setCurrentWidget(self.source_panel)

    def _on_source_panel_applied(self, updated_cfg: CameraChannelConfig):
        if 0 <= self._editing_channel_row < len(self.config.channels):
            self.config.channels[self._editing_channel_row] = updated_cfg
        self._editing_channel_row = -1
        self.channels_stack.setCurrentWidget(self.page_channels_list)
        self._rebuild_channels_table()

    def _on_source_panel_cancelled(self):
        self._editing_channel_row = -1
        self.channels_stack.setCurrentWidget(self.page_channels_list)

    def _on_add_camera_clicked(self):
        self._sync_channels_from_table_ui()
        if len(self.config.channels) >= 16:
            QMessageBox.information(self, "Maximum Cameras", "Up to 16 camera channels can be configured.")
            return

        used_ids = {ch.channel_id for ch in self.config.channels}
        next_id = 1
        while next_id in used_ids:
            next_id += 1

        new_ch = CameraChannelConfig(
            channel_id=next_id,
            name=f"Camera {next_id:02d}",
            enabled=True,
            source_type="primary_nvr",
            remote_channel_id=next_id,
        )
        self.config.channels.append(new_ch)
        # Also assign to first empty slot in slot_assignments / focus_slot_assignments
        if next_id not in self.config.slot_assignments:
            for i, val in enumerate(self.config.slot_assignments):
                if val == 0:
                    self.config.slot_assignments[i] = next_id
                    break
        if next_id not in self.config.focus_slot_assignments:
            for i, val in enumerate(self.config.focus_slot_assignments):
                if val == 0:
                    self.config.focus_slot_assignments[i] = next_id
                    break

        self._rebuild_channels_table()
        self.table_channels.selectRow(len(self.config.channels) - 1)

    def _on_remove_camera_clicked(self):
        self._sync_channels_from_table_ui()
        if len(self.config.channels) <= 1:
            return
        row = self.table_channels.currentRow()
        if row < 0:
            row = len(self.config.channels) - 1
        removed = self.config.channels.pop(row)
        self.config.slot_assignments = [
            0 if cid == removed.channel_id else cid for cid in self.config.slot_assignments
        ]
        self.config.focus_slot_assignments = [
            0 if cid == removed.channel_id else cid for cid in self.config.focus_slot_assignments
        ]
        self._rebuild_channels_table()

    def _load_from_config(self):
        self.edit_device_model.setText(self.config.device_model)
        self.edit_host.setText(self.config.nvr_host)
        self.spin_rtsp_port.setValue(self.config.nvr_rtsp_port)
        self.spin_http_port.setValue(self.config.nvr_http_port)
        self.chk_https.setChecked(self.config.nvr_use_https)
        self.edit_user.setText(self.config.nvr_username)
        self.edit_pass.setText(self.config.nvr_password)

        idx_style = self.combo_url_style.findData(self.config.url_style)
        if idx_style >= 0:
            self.combo_url_style.setCurrentIndex(idx_style)

        idx_trans = self.combo_transport.findData(self.config.rtsp_transport)
        if idx_trans >= 0:
            self.combo_transport.setCurrentIndex(idx_trans)

        self.chk_auto_substream.setChecked(self.config.auto_substream_in_multi)
        self.spin_reconnect.setValue(self.config.reconnect_interval_sec)

        self.chk_auto_connect.setChecked(self.config.auto_connect_on_startup)
        self.chk_always_on_top.setChecked(self.config.always_on_top)
        self.chk_aspect_ratio.setChecked(self.config.maintain_aspect_ratio)
        self.chk_show_osd.setChecked(self.config.show_osd_overlay)
        self.edit_snap_dir.setText(self.config.snapshot_dir)

        self._rebuild_channels_table()

        idx_layout = self.combo_default_layout.findData(self.config.default_layout)
        if idx_layout >= 0:
            self.combo_default_layout.setCurrentIndex(idx_layout)

    def _update_url_preview(self):
        host = self.edit_host.text().strip() or "<nvr-ip>"
        port = self.spin_rtsp_port.value()
        user = self.edit_user.text().strip() or "admin"
        pwd = self.edit_pass.text()
        masked_pwd = "••••••" if pwd else "<password>"
        style = self.combo_url_style.currentData() or "isapi"

        main_url = format_rtsp_url_by_style(
            url_style=style,
            host=host,
            port=port,
            username=user,
            password=masked_pwd,
            channel_num=1,
            stream_type="main",
        )
        sub_url = format_rtsp_url_by_style(
            url_style=style,
            host=host,
            port=port,
            username=user,
            password=masked_pwd,
            channel_num=1,
            stream_type="sub",
        )

        self.lbl_url_preview.setText(f"Main Stream (HD):  {main_url}\nSub Stream  (SD):  {sub_url}")

    def _run_connection_test(self):
        host = self.edit_host.text().strip()
        if not host:
            QMessageBox.warning(self, "Missing Host", "Please enter the NVR or Camera IP address first.")
            return

        self.btn_test_conn.setEnabled(False)
        self.lbl_test_result.setStyleSheet("color: #f0b44c; font-size: 12px;")
        self.lbl_test_result.setText(f"Testing connection to {host}...")

        self._tester_thread = ConnectionTesterThread(
            host=host,
            rtsp_port=self.spin_rtsp_port.value(),
            http_port=self.spin_http_port.value(),
            username=self.edit_user.text().strip(),
            password=self.edit_pass.text(),
            use_https=self.chk_https.isChecked(),
            url_style=self.combo_url_style.currentData() or "isapi",
            parent=self,
        )
        self._tester_thread.finished_test.connect(self._on_test_finished)
        self._tester_thread.start()

    def _on_test_finished(self, rtsp_ok: bool, summary: str, dev_res: DeviceInfoResult):
        self.btn_test_conn.setEnabled(True)
        color = "#2ecc71" if rtsp_ok else "#f06565"
        self.lbl_test_result.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.lbl_test_result.setText(summary)

        if dev_res and dev_res.success:
            if dev_res.model:
                self.edit_device_model.setText(dev_res.model)

            # If NVR has more channels than currently configured, automatically expand primary NVR rows
            if dev_res.channels_discovered:
                self._sync_channels_from_table_ui()
                max_disc_ch = max(dev_res.channels_discovered.keys())
                existing_by_id = {ch.channel_id: ch for ch in self.config.channels}

                for ch_id in range(1, min(16, max_disc_ch) + 1):
                    disc_name = dev_res.channels_discovered.get(ch_id, f"Camera {ch_id:02d}")
                    is_on = dev_res.channels_online.get(ch_id, True) if dev_res.channels_online else True
                    if ch_id in existing_by_id:
                        ch_obj = existing_by_id[ch_id]
                        if ch_obj.source_type == "primary_nvr":
                            ch_obj.name = disc_name
                            if dev_res.channels_online:
                                ch_obj.enabled = is_on
                    else:
                        new_ch = CameraChannelConfig(
                            channel_id=ch_id,
                            name=disc_name,
                            enabled=is_on,
                            source_type="primary_nvr",
                            remote_channel_id=ch_id,
                        )
                        self.config.channels.append(new_ch)

                # Keep standalone/secondary cameras intact and sort by channel_id
                self.config.channels.sort(key=lambda c: c.channel_id)
                enabled_ids = [ch.channel_id for ch in self.config.channels if ch.enabled]
                if enabled_ids:
                    self.config.slot_assignments = (enabled_ids + [0] * 16)[:16]
                    self.config.focus_slot_assignments = list(self.config.slot_assignments[:16])

                self._rebuild_channels_table()

    def _browse_snapshot_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Snapshot Folder", self.edit_snap_dir.text())
        if folder:
            self.edit_snap_dir.setText(folder)

    def _on_save(self):
        # If the user clicked 'Save & Apply' while the inline Camera Source panel was open, apply its edits first
        if self.channels_stack.currentWidget() == self.source_panel and 0 <= self._editing_channel_row < len(self.config.channels):
            self.config.channels[self._editing_channel_row] = self.source_panel._build_temp_config()
            self._editing_channel_row = -1
        else:
            self._sync_channels_from_table_ui()

        self.config.device_model = self.edit_device_model.text().strip() or "Hikvision / ONVIF NVR"
        self.config.nvr_host = self.edit_host.text().strip()
        self.config.nvr_rtsp_port = self.spin_rtsp_port.value()
        self.config.nvr_http_port = self.spin_http_port.value()
        self.config.nvr_use_https = self.chk_https.isChecked()
        self.config.nvr_username = self.edit_user.text().strip()
        self.config.nvr_password = self.edit_pass.text()
        self.config.url_style = self.combo_url_style.currentData()
        self.config.rtsp_transport = self.combo_transport.currentData()
        self.config.auto_substream_in_multi = self.chk_auto_substream.isChecked()
        self.config.reconnect_interval_sec = self.spin_reconnect.value()
        self.config.default_layout = self.combo_default_layout.currentData() or 4
        self.config.auto_connect_on_startup = self.chk_auto_connect.isChecked()
        self.config.always_on_top = self.chk_always_on_top.isChecked()
        self.config.maintain_aspect_ratio = self.chk_aspect_ratio.isChecked()
        self.config.show_osd_overlay = self.chk_show_osd.isChecked()
        self.config.snapshot_dir = self.edit_snap_dir.text().strip()

        self.config.save()
        self.accept()
