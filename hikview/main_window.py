"""
Main Application Window for HikView — Lightweight iVMS-4200 Replacement
for HiLook by Hikvision NVR-104H-D/4P and IP Cameras.
Supports loading any active camera channel into any view slot, combined Layout dropdown
(Single, Quad, Focus) with automatic position swapping in 1+3 Focus mode,
per-tile Snapshot & Digital Zoom icons, vector toolbar icons, and pure black empty views.
"""

import ctypes
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import cv2
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, QSize
from PyQt6.QtGui import (
    QImage,
    QKeySequence,
    QShortcut,
    QIcon,
    QPixmap,
    QPainter,
    QColor,
    QFont,
    QPen,
)
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QFrame,
    QStatusBar,
    QMessageBox,
)

from .config import AppConfig, CameraChannelConfig
from .camera_tile import CameraTileWidget
from .stream_worker import RTSPStreamWorker
from .settings_dialog import SettingsDialog


def create_app_icon() -> QIcon:
    """Create a sleek custom vector-style icon for the window and taskbar."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QColor("#181d27"))
    painter.setPen(QColor("#e03e3e"))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

    painter.setBrush(QColor("#e03e3e"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(12, 16, 40, 10, 4, 4)

    font = QFont("Segoe UI", 16, QFont.Weight.Black)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(pix.rect().adjusted(0, 12, 0, 0), Qt.AlignmentFlag.AlignCenter, "HV")
    painter.end()
    return QIcon(pix)


def create_fullscreen_icon(color_hex: str = "#dce2ee") -> QIcon:
    """Draw a crisp 4-corner expand/fullscreen vector icon."""
    pix = QPixmap(24, 24)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color_hex), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    m = 4
    s = 5
    w = 24
    # Top-left corner
    painter.drawLine(m, m + s, m, m)
    painter.drawLine(m, m, m + s, m)
    # Top-right corner
    painter.drawLine(w - m - s, m, w - m, m)
    painter.drawLine(w - m, m, w - m, m + s)
    # Bottom-left corner
    painter.drawLine(m, w - m - s, m, w - m)
    painter.drawLine(m, w - m, m + s, w - m)
    # Bottom-right corner
    painter.drawLine(w - m - s, w - m, w - m, w - m)
    painter.drawLine(w - m, w - m - s, w - m, w - m)

    painter.end()
    return QIcon(pix)


def create_settings_icon(color_hex: str = "#dce2ee") -> QIcon:
    """Draw a crisp gear/cog vector icon for Settings."""
    pix = QPixmap(24, 24)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    c = QColor(color_hex)
    cx, cy = 12.0, 12.0

    # Draw 8 gear teeth around the outer ring
    pen_teeth = QPen(c, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen_teeth)
    for i in range(8):
        angle = i * (math.pi / 4.0)
        x1 = cx + 6.2 * math.cos(angle)
        y1 = cy + 6.2 * math.sin(angle)
        x2 = cx + 8.6 * math.cos(angle)
        y2 = cy + 8.6 * math.sin(angle)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    # Draw gear body ring and center hole
    painter.setBrush(QColor("#1e2433"))
    painter.setPen(QPen(c, 2.0))
    painter.drawEllipse(QPointF(cx, cy), 6.2, 6.2)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), 2.4, 2.4)

    painter.end()
    return QIcon(pix)


def create_power_icon(color_hex: str = "#ffffff") -> QIcon:
    """Draw a standard IEC power symbol (open top circle + vertical top bar)."""
    pix = QPixmap(24, 24)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(QColor(color_hex), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    # Arc from 130 degrees to 410 degrees (in 1/16th degree units; 0 deg is 3 o'clock, 90 deg is 12 o'clock)
    arc_rect = QRectF(5.0, 5.5, 14.0, 14.0)
    start_angle = int(125 * 16)
    span_angle = int(290 * 16)
    painter.drawArc(arc_rect, start_angle, span_angle)

    # Vertical power stroke at top center
    painter.drawLine(QPointF(12.0, 3.5), QPointF(12.0, 11.5))

    painter.end()
    return QIcon(pix)


class MainWindow(QMainWindow):
    """Primary surveillance viewer window supporting flexible camera-to-slot assignment and dynamic layouts."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle(f"HikView — {self.config.device_model} Live Viewer")
        self.setWindowIcon(create_app_icon())
        self.resize(1280, 780)
        self.setMinimumSize(860, 540)

        # Layout modes: 1 (1x1 Single), 4 (2x2 Quad), 13 (1+3 Focus), 6 (1+5 Focus), 9 (3x3 Grid), 16 (4x4 Grid)
        self.current_layout_mode: int = self.config.default_layout
        self.previous_layout_mode: int = 4
        self.selected_slot: int = 0
        self.is_streaming: bool = False

        self._normalize_slot_assignments()

        # Find initial selected_slot matching active_single_channel if present
        active_list = self._active_slot_list()
        if self.config.active_single_channel in active_list:
            self.selected_slot = active_list.index(self.config.active_single_channel)

        self.tiles: Dict[int, CameraTileWidget] = {}       # keyed by slot_index (0..15)
        self.workers: Dict[int, RTSPStreamWorker] = {}     # keyed by channel_id (1..16)
        self.manual_stream_override: Dict[int, str] = {}   # keyed by channel_id (1..16)

        self._apply_theme()
        self._build_ui()
        self._setup_shortcuts()
        self._sync_available_layouts_ui()
        self.set_layout_mode(self.current_layout_mode, self.selected_slot)
        self._apply_always_on_top()

        # Auto-connect on startup if enabled
        if self.config.auto_connect_on_startup and (
            self.config.nvr_host or any(ch.use_custom_host or ch.custom_rtsp_url for ch in self.config.channels)
        ):
            QTimer.singleShot(350, self.start_all_streams)

    def _is_focus_layout(self, mode: Optional[int] = None) -> bool:
        m = self.current_layout_mode if mode is None else mode
        return m in (13, 6)

    def _visible_slot_count_for_mode(self, mode: Optional[int] = None) -> int:
        m = self.current_layout_mode if mode is None else mode
        if m == 1:
            return 1
        elif m in (4, 13):
            return 4
        elif m == 6:
            return 6
        elif m == 9:
            return 9
        elif m == 16:
            return 16
        return 4

    def _active_slot_list(self) -> List[int]:
        """
        Return the slot-to-channel mapping list (length 16) for the current layout mode.
        - In Focus modes (1+3 or 1+5), returns `focus_slot_assignments` (so swapping in Focus never alters Grid order).
        - In Grid modes (2x2, 3x3, 4x4) or 1x1 Single mode, returns `slot_assignments` (or `focus_slot_assignments` if soloed from Focus).
        """
        if self._is_focus_layout(self.current_layout_mode):
            return self.config.focus_slot_assignments
        elif self.current_layout_mode == 1 and self._is_focus_layout(self.previous_layout_mode):
            return self.config.focus_slot_assignments
        return self.config.slot_assignments

    def _normalize_slot_assignments(self):
        """
        Ensure both `slot_assignments` and `focus_slot_assignments` have 16 entries,
        strip out any cameras that have been unchecked/disabled in Settings, and auto-populate newly enabled cameras.
        """
        enabled_ids = [ch.channel_id for ch in self.config.channels if ch.enabled]
        enabled_set = set(enabled_ids)

        if not self.config.slot_assignments:
            self.config.slot_assignments = (enabled_ids + [0] * 16)[:16]
        else:
            padded = (list(self.config.slot_assignments) + [0] * 16)[:16]
            cleaned = [cid if cid in enabled_set else 0 for cid in padded]
            # Ensure any newly added & enabled cameras that aren't in any slot get placed into open slots
            present = {cid for cid in cleaned if cid > 0}
            for cid in enabled_ids:
                if cid not in present:
                    for i in range(16):
                        if cleaned[i] == 0:
                            cleaned[i] = cid
                            present.add(cid)
                            break
            if not any(cleaned) and enabled_ids:
                cleaned = (enabled_ids + [0] * 16)[:16]
            self.config.slot_assignments = cleaned

        if not self.config.focus_slot_assignments:
            self.config.focus_slot_assignments = list(self.config.slot_assignments[:16])
        else:
            padded_f = (list(self.config.focus_slot_assignments) + [0] * 16)[:16]
            cleaned_focus = [cid if cid in enabled_set else 0 for cid in padded_f]
            seen: Set[int] = set()
            dedup_focus: List[int] = []
            for cid in cleaned_focus:
                if cid > 0 and cid in seen:
                    dedup_focus.append(0)
                else:
                    if cid > 0:
                        seen.add(cid)
                    dedup_focus.append(cid)
            for cid in enabled_ids:
                if cid not in seen:
                    for i in range(16):
                        if dedup_focus[i] == 0:
                            dedup_focus[i] = cid
                            seen.add(cid)
                            break
            if not any(dedup_focus) and enabled_ids:
                dedup_focus = (enabled_ids + [0] * 16)[:16]
            self.config.focus_slot_assignments = dedup_focus

    def _sync_available_layouts_ui(self):
        """
        Dynamically populate the main toolbar Layout dropdown and each tile's context menu
        with only the layouts suitable for the number of configured/enabled cameras.
        """
        avail_layouts = self.config.get_available_layouts()
        valid_codes = {code for _lbl, code in avail_layouts}

        if self.current_layout_mode not in valid_codes:
            self.current_layout_mode = 4
        if self.previous_layout_mode not in valid_codes:
            self.previous_layout_mode = 4

        self.combo_layout.blockSignals(True)
        self.combo_layout.clear()
        for label, code in avail_layouts:
            self.combo_layout.addItem(label, code)
        idx = self.combo_layout.findData(self.current_layout_mode)
        if idx >= 0:
            self.combo_layout.setCurrentIndex(idx)
        self.combo_layout.blockSignals(False)

        for tile in self.tiles.values():
            tile.set_available_layouts(avail_layouts)

    def _get_channel_config(self, channel_id: int) -> Optional[CameraChannelConfig]:
        for ch in self.config.channels:
            if ch.channel_id == channel_id:
                return ch
        return None

    def _get_available_cameras_list(self) -> List[Tuple[int, str, bool]]:
        """Return only active/enabled cameras from Settings."""
        return [(ch.channel_id, ch.name, ch.enabled) for ch in self.config.channels if ch.enabled]

    def _apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #000000;
                color: #e4e8f0;
            }
            QWidget#gridContainer {
                background-color: #000000;
            }
            QFrame#topToolbar {
                background-color: #131722;
                border-bottom: 1px solid #242b3a;
            }
            QLabel#brandLabel {
                color: #ffffff;
                font-size: 16px;
                font-weight: 800;
                letter-spacing: 0.5px;
            }
            QLabel#deviceSubLabel {
                color: #8b95a7;
                font-size: 12px;
                padding-left: 6px;
            }
            QPushButton {
                background-color: #1e2433;
                color: #dce2ee;
                border: 1px solid #2f384d;
                border-radius: 5px;
                padding: 5px 9px;
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #293145;
                border-color: #3f4b66;
            }
            QPushButton:checked {
                background-color: #2c364c;
                border: 1px solid #a83838;
                color: #ffffff;
            }
            QPushButton#powerOnBtn {
                background-color: #26332d;
                border: 1px solid #2ecc71;
            }
            QPushButton#powerOnBtn:hover {
                background-color: #304239;
            }
            QPushButton#powerOffBtn {
                background-color: #e03e3e;
                border: 1px solid #e03e3e;
            }
            QPushButton#powerOffBtn:hover {
                background-color: #c93333;
            }
            QComboBox {
                background-color: #1e2433;
                color: #e4e8f0;
                border: 1px solid #2f384d;
                border-radius: 5px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: 600;
            }
            QComboBox QAbstractItemView {
                background-color: #141820;
                color: #e4e8f0;
                selection-background-color: #e03e3e;
                selection-color: #ffffff;
                border: 1px solid #2e3646;
            }
            QStatusBar {
                background-color: #11151f;
                color: #8d97ab;
                border-top: 1px solid #222836;
                font-size: 12px;
            }
            """
        )

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_vbox = QVBoxLayout(central)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(0)

        # Top Control Bar
        self.toolbar_frame = QFrame()
        self.toolbar_frame.setObjectName("topToolbar")
        self.toolbar_frame.setFixedHeight(50)
        tb_layout = QHBoxLayout(self.toolbar_frame)
        tb_layout.setContentsMargins(14, 6, 14, 6)
        tb_layout.setSpacing(8)

        # Brand & Device Info
        lbl_brand = QLabel("HIKVIEW")
        lbl_brand.setObjectName("brandLabel")
        tb_layout.addWidget(lbl_brand)

        self.lbl_device_info = QLabel()
        self.lbl_device_info.setObjectName("deviceSubLabel")
        self._update_header_label()
        tb_layout.addWidget(self.lbl_device_info)

        tb_layout.addStretch()

        # Combined View Layout Dropdown (Single, Quad, Focus)
        lbl_layout = QLabel("Layout:")
        lbl_layout.setStyleSheet("color: #9aa4b8; font-size: 12px; font-weight: 600;")
        tb_layout.addWidget(lbl_layout)

        self.combo_layout = QComboBox()
        self.combo_layout.setToolTip("Switch camera view layout (Single 1×1, Quad 2×2, or Focus 1+3)")
        self.combo_layout.addItem("Single (1×1)", 1)
        self.combo_layout.addItem("Quad (2×2)", 4)
        self.combo_layout.addItem("Focus (1+3)", 13)
        self.combo_layout.currentIndexChanged.connect(self._on_layout_combo_changed)
        tb_layout.addWidget(self.combo_layout)

        tb_layout.addSpacing(6)

        # Full Screen Icon Button
        self.btn_fullscreen = QPushButton()
        self.btn_fullscreen.setIcon(create_fullscreen_icon())
        self.btn_fullscreen.setIconSize(QSize(18, 18))
        self.btn_fullscreen.setFixedSize(36, 34)
        self.btn_fullscreen.setCheckable(True)
        self.btn_fullscreen.setToolTip("Full Screen (F11)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        tb_layout.addWidget(self.btn_fullscreen)

        # Settings Gear Icon Button
        self.btn_settings = QPushButton()
        self.btn_settings.setIcon(create_settings_icon())
        self.btn_settings.setIconSize(QSize(18, 18))
        self.btn_settings.setFixedSize(36, 34)
        self.btn_settings.setToolTip("Settings")
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        tb_layout.addWidget(self.btn_settings)

        # Connect / Disconnect Power Icon Button
        self.btn_connect = QPushButton()
        self.btn_connect.setFixedSize(36, 34)
        self.btn_connect.setIconSize(QSize(18, 18))
        self._update_power_button_appearance()
        self.btn_connect.clicked.connect(self._on_connect_button_clicked)
        tb_layout.addWidget(self.btn_connect)

        main_vbox.addWidget(self.toolbar_frame)

        # Video Grid Viewport Container (pure black background)
        self.grid_container = QWidget()
        self.grid_container.setObjectName("gridContainer")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(1, 1, 1, 1)
        self.grid_layout.setSpacing(1)
        main_vbox.addWidget(self.grid_container, stretch=1)

        # Create the 16 Viewport Tile Widgets (Slots 0..15) so layouts from 1x1 up to 4x4 are supported
        avail_cams = self._get_available_cameras_list()
        slot_list = self._active_slot_list()
        for slot_idx in range(16):
            assigned_cid = slot_list[slot_idx]
            ch_cfg = self._get_channel_config(assigned_cid)
            cname = ch_cfg.name if (ch_cfg and ch_cfg.enabled) else ""
            tile = CameraTileWidget(
                slot_index=slot_idx,
                channel_id=assigned_cid if (ch_cfg and ch_cfg.enabled) else 0,
                camera_name=cname,
                maintain_aspect_ratio=self.config.maintain_aspect_ratio,
                show_osd=self.config.show_osd_overlay,
                parent=self.grid_container,
            )
            tile.set_available_cameras(avail_cams)
            tile.selected.connect(self._on_tile_selected)
            tile.double_clicked.connect(self._on_tile_double_clicked)
            tile.camera_assigned.connect(self.assign_camera_to_slot)
            tile.layout_mode_requested.connect(self.set_layout_mode)
            tile.promote_to_focus_requested.connect(self.promote_side_slot_to_large_focus)
            tile.stream_type_requested.connect(self._on_tile_stream_type_requested)
            tile.reconnect_requested.connect(self.reconnect_channel)
            tile.disconnect_requested.connect(self.stop_channel)
            tile.snapshot_requested.connect(self.take_snapshot)
            tile.fullscreen_requested.connect(self.toggle_fullscreen)
            self.tiles[slot_idx] = tile

        # Status Bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(
            "Ready — Hover any camera view to access Snapshot, Digital Zoom, and Camera selection • Double-click to solo/swap"
        )

    def _update_power_button_appearance(self):
        """Update the Power button icon, color, and tooltip based on streaming state."""
        if self.is_streaming:
            self.btn_connect.setIcon(create_power_icon("#2ecc71"))
            self.btn_connect.setObjectName("powerOnBtn")
            self.btn_connect.setToolTip("Disconnect All Streams")
        else:
            self.btn_connect.setIcon(create_power_icon("#ffffff"))
            self.btn_connect.setObjectName("powerOffBtn")
            self.btn_connect.setToolTip("Connect Live Streams")
        self.btn_connect.style().unpolish(self.btn_connect)
        self.btn_connect.style().polish(self.btn_connect)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._exit_fullscreen_if_active)
        QShortcut(QKeySequence("F"), self, activated=self.toggle_fullscreen)

        QShortcut(QKeySequence("G"), self, activated=lambda: self.set_layout_mode(4))
        QShortcut(QKeySequence("1"), self, activated=lambda: self._solo_slot_shortcut(0))
        QShortcut(QKeySequence("2"), self, activated=lambda: self._solo_slot_shortcut(1))
        QShortcut(QKeySequence("3"), self, activated=lambda: self._solo_slot_shortcut(2))
        QShortcut(QKeySequence("4"), self, activated=lambda: self._solo_slot_shortcut(3))
        QShortcut(QKeySequence("S"), self, activated=self._take_selected_snapshot)

    def _solo_slot_shortcut(self, slot_idx: int):
        if slot_idx in self.tiles:
            self._on_tile_selected(slot_idx)
            self.set_layout_mode(1, target_slot=slot_idx)

    def _update_header_label(self):
        self.setWindowTitle(f"HikView — {self.config.device_model} Live Viewer")
        host_part = f" ({self.config.nvr_host}:{self.config.nvr_rtsp_port})" if self.config.nvr_host else ""
        self.lbl_device_info.setText(f"|  {self.config.device_model}{host_part}")

    def _on_layout_combo_changed(self, _index: int):
        mode = self.combo_layout.currentData()
        if mode is not None and int(mode) != self.current_layout_mode:
            self.set_layout_mode(int(mode))

    def _refresh_tiles_from_active_slot_list(self):
        """Update all 16 tile widgets to reflect the active layout's slot assignments and current worker state."""
        slot_list = self._active_slot_list()
        is_focus = self._is_focus_layout(self.current_layout_mode)
        for s_idx, tile in self.tiles.items():
            tile.current_layout_mode = self.current_layout_mode
            tile.in_focus_layout = is_focus
            cid = slot_list[s_idx]
            ch_cfg = self._get_channel_config(cid)
            if cid > 0 and ch_cfg and ch_cfg.enabled:
                tile.set_assigned_camera(cid, ch_cfg.name)
                if cid in self.workers:
                    w = self.workers[cid]
                    tile.set_status("connected", f"LIVE ({w.stream_type.upper()})")
                    bgr = w.get_latest_frame()
                    if bgr is not None:
                        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                        h, width, ch = rgb.shape
                        qimg = QImage(rgb.data, width, h, ch * width, QImage.Format.Format_RGB888).copy()
                        tile.set_frame(qimg)
                elif not self.is_streaming:
                    tile.clear_frame()
                    tile.set_status("disconnected", "Ready")
            else:
                tile.set_assigned_camera(0, "")

    def promote_side_slot_to_large_focus(self, side_slot_index: int):
        """
        In Focus mode (1+3 or 1+5), move the camera from `side_slot_index` into the large primary view (slot 0),
        and swap the camera that was in slot 0 (if any) into `side_slot_index`.
        Does not affect `slot_assignments` (Grid layout order).
        """
        max_focus_slots = self._visible_slot_count_for_mode()
        if side_slot_index <= 0 or side_slot_index >= max_focus_slots:
            return
        focus_list = self.config.focus_slot_assignments
        focus_list[0], focus_list[side_slot_index] = focus_list[side_slot_index], focus_list[0]
        self.config.save()

        self._refresh_tiles_from_active_slot_list()
        self._on_tile_selected(0)
        if self.is_streaming:
            self._sync_workers_with_slots()
            self._adjust_streams_for_layout()

    def assign_camera_to_slot(self, slot_index: int, channel_id: int):
        """
        Assign an active camera (or 0 = None) to `slot_index` (0..15).
        - In Focus mode (`current_layout_mode in (13, 6)`):
          Updates `focus_slot_assignments` ONLY (preserving the user's Grid order in `slot_assignments`).
          If `channel_id > 0` was already present in another slot in Focus mode, swaps their positions
          so the same camera is never displayed twice and any displaced camera moves to the vacated view.
        - In Grid mode (2x2, 3x3, 4x4) or 1x1 Single mode:
          Updates `slot_assignments`.
        """
        if slot_index not in self.tiles:
            return

        active_list = self._active_slot_list()
        previous_cid_in_target = active_list[slot_index]

        if self._is_focus_layout(self.current_layout_mode):
            if channel_id > 0:
                other_slot = None
                for idx, existing_cid in enumerate(active_list):
                    if idx != slot_index and existing_cid == channel_id:
                        other_slot = idx
                        break
                if other_slot is not None:
                    active_list[other_slot] = previous_cid_in_target
            active_list[slot_index] = channel_id
        else:
            active_list[slot_index] = channel_id
            if channel_id > 0 and channel_id not in self.config.focus_slot_assignments:
                for f_idx, f_cid in enumerate(self.config.focus_slot_assignments):
                    if f_cid == 0:
                        self.config.focus_slot_assignments[f_idx] = channel_id
                        break

        self.config.save()
        self._refresh_tiles_from_active_slot_list()

        if self.is_streaming:
            self._sync_workers_with_slots()
            self._adjust_streams_for_layout()

        ch_cfg = self._get_channel_config(channel_id)
        if channel_id > 0 and ch_cfg:
            self.status_bar.showMessage(f"Loaded CH{channel_id:02d} ({ch_cfg.name}) into View {slot_index + 1}", 4000)
        else:
            self.status_bar.showMessage(f"Cleared View {slot_index + 1}", 4000)

    def _on_tile_selected(self, slot_index: int):
        self.selected_slot = slot_index
        slot_list = self._active_slot_list()
        assigned_cid = slot_list[slot_index]
        if assigned_cid > 0:
            self.config.active_single_channel = assigned_cid

        for s_idx, tile in self.tiles.items():
            tile.set_selected(s_idx == slot_index)

    def _on_tile_double_clicked(self, slot_index: int):
        """
        - In Focus mode (1+3 or 1+5): Double-clicking one of the smaller side/bottom views (slots > 0)
          moves/swaps that camera into the large primary view (slot 0)!
          Double-clicking the large primary view (slot 0) solos it to 1x1 Full View.
        - In Grid mode (2x2, 3x3, 4x4): Double-clicking any view solos it to 1x1 Full View.
        - In 1x1 Single mode: Double-clicking restores the previous multi-camera layout.
        """
        if self._is_focus_layout(self.current_layout_mode) and slot_index > 0:
            if self.config.focus_slot_assignments[slot_index] > 0:
                self.promote_side_slot_to_large_focus(slot_index)
                return

        self._on_tile_selected(slot_index)
        if self.current_layout_mode != 1:
            self.previous_layout_mode = self.current_layout_mode
            self.set_layout_mode(1, target_slot=slot_index)
        else:
            restore_mode = self.previous_layout_mode if self.previous_layout_mode != 1 else 4
            self.set_layout_mode(restore_mode, target_slot=slot_index)

    def set_layout_mode(self, mode: int, target_slot: Optional[int] = None):
        avail_codes = {code for _lbl, code in self.config.get_available_layouts()}
        if mode not in avail_codes:
            mode = 4

        if self._is_focus_layout(mode) and not self._is_focus_layout(self.current_layout_mode):
            self._normalize_slot_assignments()
            if target_slot is None:
                target_slot = 0

        visible_count = self._visible_slot_count_for_mode(mode)
        if target_slot is not None:
            self.selected_slot = target_slot
        elif mode != 1 and self.selected_slot >= visible_count:
            self.selected_slot = 0

        self.current_layout_mode = mode

        # Sync the combined Layout dropdown
        idx = self.combo_layout.findData(mode)
        if idx >= 0 and self.combo_layout.currentIndex() != idx:
            self.combo_layout.blockSignals(True)
            self.combo_layout.setCurrentIndex(idx)
            self.combo_layout.blockSignals(False)

        self._refresh_tiles_from_active_slot_list()
        self._apply_grid_layout(mode, self.selected_slot)
        if self.is_streaming:
            self._sync_workers_with_slots()
            self._adjust_streams_for_layout()

    def _apply_grid_layout(self, mode: int, focus_slot: int):
        for i in reversed(range(self.grid_layout.count())):
            item = self.grid_layout.itemAt(i)
            if item and item.widget():
                self.grid_layout.removeWidget(item.widget())

        for tile in self.tiles.values():
            tile.hide()

        for r in range(4):
            self.grid_layout.setRowStretch(r, 0)
            self.grid_layout.setColumnStretch(r, 0)

        if mode == 1:
            tile = self.tiles.get(focus_slot, self.tiles[0])
            tile.show()
            self.grid_layout.addWidget(tile, 0, 0, 1, 1)
            self.grid_layout.setRowStretch(0, 1)
            self.grid_layout.setColumnStretch(0, 1)

        elif mode == 13:
            # 1+3 Focus: Slot 0 spans rows 0..2, col 0; Slots 1..3 in col 1
            primary_tile = self.tiles[0]
            primary_tile.show()
            self.grid_layout.addWidget(primary_tile, 0, 0, 3, 1)

            for idx, s_idx in enumerate([1, 2, 3]):
                t = self.tiles[s_idx]
                t.show()
                self.grid_layout.addWidget(t, idx, 1, 1, 1)

            self.grid_layout.setColumnStretch(0, 3)
            self.grid_layout.setColumnStretch(1, 1)
            for r in range(3):
                self.grid_layout.setRowStretch(r, 1)

        elif mode == 6:
            # 1+5 Focus: 3x3 grid where Slot 0 spans rows 0..1, cols 0..1;
            # Slots 1, 2 on right column (rows 0, 1, col 2); Slots 3, 4, 5 along bottom row (row 2, cols 0..2)
            primary_tile = self.tiles[0]
            primary_tile.show()
            self.grid_layout.addWidget(primary_tile, 0, 0, 2, 2)

            side_positions = [
                (1, 0, 2),
                (2, 1, 2),
                (3, 2, 0),
                (4, 2, 1),
                (5, 2, 2),
            ]
            for s_idx, r, c in side_positions:
                t = self.tiles[s_idx]
                t.show()
                self.grid_layout.addWidget(t, r, c, 1, 1)

            for i in range(3):
                self.grid_layout.setRowStretch(i, 1)
                self.grid_layout.setColumnStretch(i, 1)

        elif mode == 9:
            # 3x3 Grid (Slots 0..8)
            for s_idx in range(9):
                tile = self.tiles[s_idx]
                tile.show()
                r, c = divmod(s_idx, 3)
                self.grid_layout.addWidget(tile, r, c, 1, 1)
            for i in range(3):
                self.grid_layout.setRowStretch(i, 1)
                self.grid_layout.setColumnStretch(i, 1)

        elif mode == 16:
            # 4x4 Grid (Slots 0..15)
            for s_idx in range(16):
                tile = self.tiles[s_idx]
                tile.show()
                r, c = divmod(s_idx, 4)
                self.grid_layout.addWidget(tile, r, c, 1, 1)
            for i in range(4):
                self.grid_layout.setRowStretch(i, 1)
                self.grid_layout.setColumnStretch(i, 1)

        else:
            # 2x2 Quad Grid (Slots 0..3)
            positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
            for idx, s_idx in enumerate([0, 1, 2, 3]):
                tile = self.tiles[s_idx]
                tile.show()
                r, c = positions[idx]
                self.grid_layout.addWidget(tile, r, c, 1, 1)

            self.grid_layout.setRowStretch(0, 1)
            self.grid_layout.setRowStretch(1, 1)
            self.grid_layout.setColumnStretch(0, 1)
            self.grid_layout.setColumnStretch(1, 1)

        self._on_tile_selected(focus_slot)

    def _determine_stream_type(self, ch_cfg: CameraChannelConfig) -> str:
        """Determine whether a channel should use 'main' (HD) or 'sub' (Fluent SD)."""
        if ch_cfg.channel_id in self.manual_stream_override:
            return self.manual_stream_override[ch_cfg.channel_id]

        if ch_cfg.preferred_stream in ("main", "sub"):
            return ch_cfg.preferred_stream

        if not self.config.auto_substream_in_multi:
            return "main"

        slot_list = self._active_slot_list()
        if self.current_layout_mode == 1:
            focus_cid = slot_list[self.selected_slot]
            return "main" if ch_cfg.channel_id == focus_cid else "sub"
        elif self._is_focus_layout(self.current_layout_mode):
            large_cid = self.config.focus_slot_assignments[0]
            return "main" if ch_cfg.channel_id == large_cid else "sub"
        else:
            return "sub"

    def _adjust_streams_for_layout(self):
        if not self.is_streaming:
            return

        for ch_cfg in self.config.channels:
            cid = ch_cfg.channel_id
            if cid not in self.workers:
                continue

            desired_stream = self._determine_stream_type(ch_cfg)
            url = ch_cfg.build_rtsp_url(
                nvr_host=self.config.nvr_host,
                nvr_rtsp_port=self.config.nvr_rtsp_port,
                nvr_username=self.config.nvr_username,
                nvr_password=self.config.nvr_password,
                stream_type=desired_stream,
                url_style=self.config.url_style,
            )
            worker = self.workers[cid]
            if worker.stream_type != desired_stream or worker.rtsp_url != url:
                worker.update_stream_config(
                    rtsp_url=url,
                    stream_type=desired_stream,
                    transport=self.config.rtsp_transport,
                )

    def _on_tile_stream_type_requested(self, channel_id: int, stream_type: str):
        self.manual_stream_override[channel_id] = stream_type
        if self.is_streaming:
            self.reconnect_channel(channel_id)
        else:
            self.status_bar.showMessage(f"Channel {channel_id} set to {stream_type.upper()} stream.")

    def _on_connect_button_clicked(self):
        if self.is_streaming:
            self.stop_all_streams()
        else:
            self.start_all_streams()

    def _get_assigned_channel_ids(self) -> Set[int]:
        """Return only camera channel IDs that are currently assigned to visible layout slots."""
        slot_list = self._active_slot_list()
        if self.current_layout_mode == 1:
            cid = slot_list[self.selected_slot]
            return {cid} if cid > 0 else set()
        vis_count = self._visible_slot_count_for_mode(self.current_layout_mode)
        return {cid for cid in slot_list[:vis_count] if cid > 0}

    def _sync_workers_with_slots(self):
        """Ensure background stream workers are running for all assigned & enabled camera channels."""
        assigned_cids = self._get_assigned_channel_ids()

        for running_cid in list(self.workers.keys()):
            if running_cid not in assigned_cids:
                self.stop_channel(running_cid)

        for cid in assigned_cids:
            ch_cfg = self._get_channel_config(cid)
            if ch_cfg and ch_cfg.enabled and cid not in self.workers:
                self._start_channel_worker(ch_cfg)

    def start_all_streams(self):
        self.stop_all_streams()
        self.is_streaming = True
        self._update_power_button_appearance()
        self._sync_workers_with_slots()

    def _start_channel_worker(self, ch_cfg: CameraChannelConfig):
        cid = ch_cfg.channel_id
        stream_type = self._determine_stream_type(ch_cfg)
        rtsp_url = ch_cfg.build_rtsp_url(
            nvr_host=self.config.nvr_host,
            nvr_rtsp_port=self.config.nvr_rtsp_port,
            nvr_username=self.config.nvr_username,
            nvr_password=self.config.nvr_password,
            stream_type=stream_type,
            url_style=self.config.url_style,
        )

        worker = RTSPStreamWorker(
            channel_id=cid,
            rtsp_url=rtsp_url,
            stream_type=stream_type,
            transport=self.config.rtsp_transport,
            reconnect_interval=self.config.reconnect_interval_sec,
            camera_name=ch_cfg.name,
            parent=self,
        )
        worker.frame_ready.connect(self._on_worker_frame)
        worker.status_changed.connect(self._on_worker_status)
        worker.stats_updated.connect(self._on_worker_stats)
        self.workers[cid] = worker
        worker.start()

    def reconnect_channel(self, channel_id: int):
        self.stop_channel(channel_id)
        ch_cfg = self._get_channel_config(channel_id)
        if ch_cfg and ch_cfg.enabled:
            self.is_streaming = True
            self._update_power_button_appearance()
            self._start_channel_worker(ch_cfg)

    def stop_channel(self, channel_id: int):
        worker = self.workers.pop(channel_id, None)
        if worker is not None:
            try:
                worker.frame_ready.disconnect()
                worker.status_changed.disconnect()
                worker.stats_updated.disconnect()
            except Exception:
                pass
            worker.stop()
            worker.deleteLater()
        for tile in self.tiles.values():
            if tile.channel_id == channel_id:
                tile.clear_frame()
                tile.set_status("disconnected", "Stopped")
        if not self.workers:
            self.is_streaming = False
            self._update_power_button_appearance()

    def stop_all_streams(self):
        for cid in list(self.workers.keys()):
            self.stop_channel(cid)
        self.is_streaming = False
        self._update_header_label()
        self._update_power_button_appearance()

    def _on_worker_frame(self, channel_id: int, qimg: QImage):
        for tile in self.tiles.values():
            if tile.channel_id == channel_id:
                tile.set_frame(qimg)

    def _on_worker_status(self, channel_id: int, state: str, message: str):
        for tile in self.tiles.values():
            if tile.channel_id == channel_id:
                tile.set_status(state, message)

    def _on_worker_stats(self, channel_id: int, fps: float, width: int, height: int, stream_type: str):
        for tile in self.tiles.values():
            if tile.channel_id == channel_id:
                tile.set_stats(fps, width, height, stream_type)

    def _take_selected_snapshot(self):
        slot_list = self._active_slot_list()
        cid = slot_list[self.selected_slot]
        if cid <= 0:
            QMessageBox.information(self, "Snapshot", f"View {self.selected_slot + 1} has no active camera assigned.")
            return
        self.take_snapshot(self.selected_slot, cid)

    def take_snapshot(self, slot_index: int, channel_id: int):
        """
        Save a clean PNG snapshot of `slot_index` / `channel_id` directly from the decoded video frame
        (never includes the camera title bar or UI chrome). If the tile is currently digitally zoomed,
        crops the snapshot to match the zoomed view area.
        """
        worker = self.workers.get(channel_id)
        if worker is None:
            QMessageBox.information(self, "Snapshot", f"Camera CH{channel_id:02d} is not currently streaming.")
            return

        bgr = worker.get_latest_frame()
        if bgr is None:
            QMessageBox.information(self, "Snapshot", f"No video frame available yet on Camera CH{channel_id:02d}.")
            return

        tile = self.tiles.get(slot_index)
        if tile is not None:
            zoom_rect = tile.get_zoom_norm_rect()
            if zoom_rect is not None:
                ih, iw = bgr.shape[:2]
                sx = max(0, int(zoom_rect.x() * iw))
                sy = max(0, int(zoom_rect.y() * ih))
                sw = max(1, int(zoom_rect.width() * iw))
                sh = max(1, int(zoom_rect.height() * ih))
                bgr = bgr[sy : min(ih, sy + sh), sx : min(iw, sx + sw)]
            tile.trigger_snapshot_feedback()

        snap_dir = Path(self.config.snapshot_dir)
        snap_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = snap_dir / f"HikView_CH{channel_id:02d}_{ts}.png"
        cv2.imwrite(str(filename), bgr)
        self.status_bar.showMessage(f"Snapshot saved to: {filename}", 6000)

    def _apply_always_on_top(self):
        """Apply or remove the Windows Always-on-Top window flag without losing window state."""
        on_top = bool(self.config.always_on_top)
        was_visible = self.isVisible()
        was_fullscreen = self.isFullScreen()
        was_maximized = self.isMaximized()

        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)

        if was_visible:
            if was_fullscreen:
                self.showFullScreen()
            elif was_maximized:
                self.showMaximized()
            else:
                self.show()

        if sys.platform == "win32":
            try:
                hwnd = int(self.winId())
                hwnd_flag = -1 if on_top else -2  # HWND_TOPMOST = -1, HWND_NOTOPMOST = -2
                swp_flags = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
                ctypes.windll.user32.SetWindowPos(hwnd, hwnd_flag, 0, 0, 0, 0, swp_flags)
            except Exception:
                pass

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_fullscreen_if_active()
        else:
            self.toolbar_frame.hide()
            self.status_bar.hide()
            self.showFullScreen()
            self.btn_fullscreen.setChecked(True)
            if self.config.always_on_top:
                self._apply_always_on_top()

    def _exit_fullscreen_if_active(self):
        if self.isFullScreen():
            self.showNormal()
            self.toolbar_frame.show()
            self.status_bar.show()
            self.btn_fullscreen.setChecked(False)
            if self.config.always_on_top:
                self._apply_always_on_top()

    def open_settings_dialog(self):
        dlg = SettingsDialog(self.config, parent=self)
        if dlg.exec():
            was_streaming = self.is_streaming
            self.stop_all_streams()
            self.config = dlg.config
            self._normalize_slot_assignments()
            self.manual_stream_override.clear()
            self._update_header_label()
            self._apply_always_on_top()

            avail_cams = self._get_available_cameras_list()
            for tile in self.tiles.values():
                tile.set_available_cameras(avail_cams)
                tile.maintain_aspect_ratio = self.config.maintain_aspect_ratio
                tile.show_osd = self.config.show_osd_overlay

            self._sync_available_layouts_ui()
            self.set_layout_mode(self.current_layout_mode, self.selected_slot)

            if was_streaming:
                self.start_all_streams()
            else:
                self.status_bar.showMessage("Settings saved. Click the Power button to start streaming.", 5000)

    def closeEvent(self, event):
        valid_codes = {code for _lbl, code in self.config.get_available_layouts()}
        self.config.default_layout = self.current_layout_mode if self.current_layout_mode in valid_codes else 4
        self.config.save()
        self.stop_all_streams()
        super().closeEvent(event)
