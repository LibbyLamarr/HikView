"""
Camera Tile Widget for rendering real-time video frames, auto-hiding hover OSD bar,
snapshot icon button, interactive digital zoom (magnifying glass + crosshair drag-to-zoom),
camera assignment per view slot, context menu actions, and double-click maximize/restore.
"""

from typing import List, Optional, Tuple
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QRectF, QPoint, QTimer
from PyQt6.QtGui import (
    QImage,
    QPainter,
    QColor,
    QFont,
    QPen,
    QAction,
    QMouseEvent,
)
from PyQt6.QtWidgets import QWidget, QMenu


class CameraTileWidget(QWidget):
    """
    Individual viewport slot widget (Slot 0..3).
    Can display any assigned camera channel (CH 1..4) or be Unassigned (0 = Empty Black View).
    - Auto-hides the top title bar unless the mouse cursor is hovering inside the tile.
    - Includes a Snapshot camera icon button to the left of the Digital Zoom magnifying glass button:
      clicking it automatically saves a clean snapshot of that camera's view (without the title bar).
    - Includes a magnifying glass Digital Zoom button between the Snapshot icon and the camera dropdown:
      click to arm crosshair selection, drag a box over the video to zoom into that region, and click the
      zoom button again to restore the full camera view.
    - Double-click toggles between Single-Camera maximized view and Multi-Camera grid view (or swaps in 1+3 Focus).
    """
    double_clicked = pyqtSignal(int)                   # slot_index
    selected = pyqtSignal(int)                         # slot_index
    camera_assigned = pyqtSignal(int, int)             # (slot_index, channel_id) where 0 = None
    layout_mode_requested = pyqtSignal(int)            # mode: 1 (Single), 4 (Quad), 13 (Focus)
    promote_to_focus_requested = pyqtSignal(int)       # slot_index (move this side slot to the large view in 1+3 mode)
    stream_type_requested = pyqtSignal(int, str)       # (channel_id, "main" | "sub")
    reconnect_requested = pyqtSignal(int)              # channel_id
    disconnect_requested = pyqtSignal(int)             # channel_id
    snapshot_requested = pyqtSignal(int, int)          # (slot_index, channel_id)
    fullscreen_requested = pyqtSignal()

    def __init__(
        self,
        slot_index: int,
        channel_id: int = 0,
        camera_name: str = "",
        maintain_aspect_ratio: bool = True,
        show_osd: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.slot_index = slot_index
        self.channel_id = channel_id  # 0 means Unassigned / Empty view
        self.camera_name = camera_name or (f"Camera {channel_id:02d}" if channel_id > 0 else "")
        self.maintain_aspect_ratio = maintain_aspect_ratio
        self.show_osd = show_osd
        self.current_layout_mode = 4  # 1 (Single 1x1), 4 (Quad 2x2), 13 (Focus 1+3)
        self.in_focus_layout = False  # True when layout mode is 13 (1+3 Focus)

        # Available enabled cameras for the selector menu: list of (channel_id, name, enabled)
        self.available_cameras: List[Tuple[int, str, bool]] = []
        # Dynamic layout options based on camera count: list of (label, mode_code)
        self.available_layouts: List[Tuple[str, int]] = [
            ("Single (1×1)", 1),
            ("Quad (2×2)", 4),
            ("Focus (1+3)", 13),
        ]

        self.is_selected = False
        self._is_hovered = False
        self.state = "disconnected"  # "disconnected", "connecting", "connected", "error"
        self.status_message = "Ready"
        self.fps = 0.0
        self.frame_width = 0
        self.frame_height = 0
        self.stream_type = "main"

        self._current_image: Optional[QImage] = None
        self._selector_badge_rect = QRect()
        self._zoom_btn_rect = QRect()
        self._snap_btn_rect = QRect()
        self._snap_flash_active: bool = False

        # Digital Zoom state
        self._zoom_selecting: bool = False             # True when user clicked magnifier and is ready to drag a box
        self._zoom_dragging: bool = False              # True while left mouse button is dragging the zoom box
        self._zoom_drag_start: QPoint = QPoint()
        self._zoom_drag_current: QPoint = QPoint()
        self._zoom_norm_rect: Optional[QRectF] = None  # Normalized (0.0..1.0) crop region of the source frame

        self.setMinimumSize(220, 140)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_available_cameras(self, cameras: List[Tuple[int, str, bool]]):
        # Only retain cameras that are enabled in Settings
        self.available_cameras = [c for c in cameras if c[2]]

    def set_available_layouts(self, layouts: List[Tuple[str, int]]):
        """Set dynamic layout options for the context menu based on configured camera count."""
        if layouts:
            self.available_layouts = list(layouts)

    def get_zoom_norm_rect(self) -> Optional[QRectF]:
        """Return the current digital zoom normalized rectangle (or None if not zoomed)."""
        return self._zoom_norm_rect

    def trigger_snapshot_feedback(self):
        """Briefly highlight the snapshot button green to confirm capture."""
        self._snap_flash_active = True
        self.update()
        QTimer.singleShot(350, self._clear_snap_flash)

    def _clear_snap_flash(self):
        self._snap_flash_active = False
        self.update()

    def reset_zoom(self):
        """Reset digital zoom and restore normal cursor and full camera view."""
        self._zoom_selecting = False
        self._zoom_dragging = False
        self._zoom_norm_rect = None
        self.unsetCursor()
        self.update()

    def _toggle_zoom_button(self):
        """
        Handle clicking the magnifying glass button in the title bar:
        - If currently zoomed in (`_zoom_norm_rect` is active): restore the full camera view.
        - If currently in crosshair selection mode (`_zoom_selecting`): cancel selection mode.
        - Otherwise: enter crosshair selection mode so user can drag an area to zoom.
        """
        if self._zoom_norm_rect is not None or self._zoom_selecting:
            self.reset_zoom()
        else:
            self._zoom_selecting = True
            self._zoom_dragging = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.update()

    def set_assigned_camera(self, channel_id: int, camera_name: str = ""):
        if self.channel_id != channel_id:
            self.reset_zoom()
        self.channel_id = channel_id
        if channel_id <= 0:
            self.camera_name = ""
            self.state = "disconnected"
            self.status_message = ""
            self.clear_frame()
        else:
            self.camera_name = camera_name or f"Camera {channel_id:02d}"
            self.update()

    def set_frame(self, image: QImage):
        self._current_image = image
        self.update()

    def clear_frame(self):
        self._current_image = None
        self.fps = 0.0
        self.frame_width = 0
        self.frame_height = 0
        self.update()

    def set_status(self, state: str, message: str):
        self.state = state
        self.status_message = message
        if state in ("disconnected", "error"):
            self.fps = 0.0
        self.update()

    def set_stats(self, fps: float, width: int, height: int, stream_type: str):
        self.fps = fps
        self.frame_width = width
        self.frame_height = height
        self.stream_type = stream_type
        self.update()

    def set_selected(self, selected: bool):
        if self.is_selected != selected:
            self.is_selected = selected
            self.update()

    def enterEvent(self, event):
        self._is_hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)

    def _compute_video_target_rect(self, viewport_rect: QRect) -> QRect:
        """Return the QRect within the widget where the video image is drawn."""
        if self._current_image is None or self._current_image.isNull() or not self.maintain_aspect_ratio:
            return viewport_rect
        img_size = self._current_image.size()
        scaled_size = img_size.scaled(viewport_rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (viewport_rect.width() - scaled_size.width()) // 2
        y = (viewport_rect.height() - scaled_size.height()) // 2
        return QRect(x, y, scaled_size.width(), scaled_size.height())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.selected.emit(self.slot_index)

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            # 1. Check if user clicked the 'Cam ▾' dropdown badge in the title bar
            if self._is_hovered and self._selector_badge_rect.contains(pos):
                self._show_camera_picker_menu(self.mapToGlobal(pos))
                return

            # 2. Check if user clicked the Snapshot icon button in the title bar
            if self._is_hovered and self.channel_id > 0 and self._snap_btn_rect.contains(pos):
                self.snapshot_requested.emit(self.slot_index, self.channel_id)
                return

            # 3. Check if user clicked the magnifying glass Digital Zoom button in the title bar
            if self._is_hovered and self.channel_id > 0 and self._zoom_btn_rect.contains(pos):
                self._toggle_zoom_button()
                return

            # 4. If digital zoom crosshair mode is armed, begin dragging the zoom selection box
            if self._zoom_selecting and self.channel_id > 0:
                self._zoom_dragging = True
                self._zoom_drag_start = pos
                self._zoom_drag_current = pos
                self.update()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self._is_hovered:
            self._is_hovered = True
            self.update()

        if self._zoom_dragging:
            self._zoom_drag_current = event.pos()
            self.update()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._zoom_dragging:
            self._zoom_dragging = False
            self._zoom_drag_current = event.pos()
            sel_rect = QRect(self._zoom_drag_start, self._zoom_drag_current).normalized()

            video_rect = self._compute_video_target_rect(self.rect())
            intersected = sel_rect.intersected(video_rect)

            # Require a minimum drag size (12x12 pixels) so accidental single clicks don't zoom into 1 pixel
            if intersected.width() >= 12 and intersected.height() >= 12 and video_rect.width() > 0 and video_rect.height() > 0:
                nx = (intersected.left() - video_rect.left()) / float(video_rect.width())
                ny = (intersected.top() - video_rect.top()) / float(video_rect.height())
                nw = intersected.width() / float(video_rect.width())
                nh = intersected.height() / float(video_rect.height())

                nx = max(0.0, min(1.0, nx))
                ny = max(0.0, min(1.0, ny))
                nw = max(0.05, min(1.0 - nx, nw))
                nh = max(0.05, min(1.0 - ny, nh))

                self._zoom_norm_rect = QRectF(nx, ny, nw, nh)
                self._zoom_selecting = False
                self.unsetCursor()
            self.update()
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if (
                self._selector_badge_rect.contains(pos)
                or self._zoom_btn_rect.contains(pos)
                or self._snap_btn_rect.contains(pos)
            ):
                return
            if self._zoom_selecting:
                return
            self.double_clicked.emit(self.slot_index)
        super().mouseDoubleClickEvent(event)

    def _menu_stylesheet(self) -> str:
        return """
            QMenu {
                background-color: #141820;
                color: #e4e8f0;
                border: 1px solid #2e3646;
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #e03e3e;
                color: #ffffff;
            }
        """

    def _populate_camera_assignment_actions(self, target_menu: QMenu):
        for cid, cname, _enabled in self.available_cameras:
            act = QAction(f"CH{cid:02d}: {cname}", self)
            act.setCheckable(True)
            act.setChecked(self.channel_id == cid)
            act.triggered.connect(lambda _chk=False, c=cid: self.camera_assigned.emit(self.slot_index, c))
            target_menu.addAction(act)

        target_menu.addSeparator()
        act_none = QAction("None (Empty View)", self)
        act_none.setCheckable(True)
        act_none.setChecked(self.channel_id == 0)
        act_none.triggered.connect(lambda: self.camera_assigned.emit(self.slot_index, 0))
        target_menu.addAction(act_none)

    def _show_camera_picker_menu(self, global_pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_stylesheet())
        self._populate_camera_assignment_actions(menu)
        if self.in_focus_layout and self.slot_index > 0 and self.channel_id > 0:
            menu.addSeparator()
            act_promote = QAction("Move This Camera to Large View", self)
            act_promote.triggered.connect(lambda: self.promote_to_focus_requested.emit(self.slot_index))
            menu.addAction(act_promote)
        menu.exec(global_pos)
        self._is_hovered = self.rect().contains(self.mapFromGlobal(self.cursor().pos()))
        self.update()

    def _populate_layout_actions(self, target_menu: QMenu):
        for label, mode in self.available_layouts:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.current_layout_mode == mode)
            act.triggered.connect(lambda _chk=False, m=mode: self.layout_mode_requested.emit(m))
            target_menu.addAction(act)

    def _show_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_stylesheet())

        cam_submenu = menu.addMenu("Load Camera")
        cam_submenu.setStyleSheet(self._menu_stylesheet())
        self._populate_camera_assignment_actions(cam_submenu)

        layout_submenu = menu.addMenu("Layout")
        layout_submenu.setStyleSheet(self._menu_stylesheet())
        self._populate_layout_actions(layout_submenu)

        if self.in_focus_layout and self.slot_index > 0 and self.channel_id > 0:
            act_promote = QAction("Move Camera to Large Focus View (Swap)", self)
            act_promote.triggered.connect(lambda: self.promote_to_focus_requested.emit(self.slot_index))
            menu.addAction(act_promote)

        if self.channel_id > 0:
            menu.addSeparator()

            act_main = QAction("Main Stream", self)
            act_main.setCheckable(True)
            act_main.setChecked(self.stream_type == "main")
            act_main.triggered.connect(lambda: self.stream_type_requested.emit(self.channel_id, "main"))
            menu.addAction(act_main)

            act_sub = QAction("Sub Stream", self)
            act_sub.setCheckable(True)
            act_sub.setChecked(self.stream_type == "sub")
            act_sub.triggered.connect(lambda: self.stream_type_requested.emit(self.channel_id, "sub"))
            menu.addAction(act_sub)

            menu.addSeparator()

            act_snap = QAction("Save Snapshot", self)
            act_snap.setEnabled(self._current_image is not None)
            act_snap.triggered.connect(lambda: self.snapshot_requested.emit(self.slot_index, self.channel_id))
            menu.addAction(act_snap)

            if self.state in ("connected", "connecting"):
                act_toggle_cam = QAction("Stop Stream", self)
                act_toggle_cam.triggered.connect(lambda: self.disconnect_requested.emit(self.channel_id))
            else:
                act_toggle_cam = QAction("Start Stream", self)
                act_toggle_cam.triggered.connect(lambda: self.reconnect_requested.emit(self.channel_id))
            menu.addAction(act_toggle_cam)

        menu.addSeparator()

        act_fs = QAction("Full Screen", self)
        act_fs.triggered.connect(self.fullscreen_requested.emit)
        menu.addAction(act_fs)

        menu.exec(self.mapToGlobal(pos))
        self._is_hovered = self.rect().contains(self.mapFromGlobal(self.cursor().pos()))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = self.rect()

        # Pure black background (#000000) for all views
        painter.fillRect(rect, QColor("#000000"))

        # Draw video frame if available (cropped to _zoom_norm_rect when digitally zoomed)
        if self._current_image is not None and not self._current_image.isNull():
            target_rect = self._compute_video_target_rect(rect)
            if self._zoom_norm_rect is not None:
                iw = self._current_image.width()
                ih = self._current_image.height()
                sx = int(self._zoom_norm_rect.x() * iw)
                sy = int(self._zoom_norm_rect.y() * ih)
                sw = max(1, int(self._zoom_norm_rect.width() * iw))
                sh = max(1, int(self._zoom_norm_rect.height() * ih))
                src_rect = QRect(sx, sy, sw, sh)
                painter.drawImage(target_rect, self._current_image, src_rect)
            else:
                painter.drawImage(target_rect, self._current_image)
        elif self.channel_id > 0:
            # Draw connecting/error status for views that have an active camera assigned
            self._draw_placeholder(painter, rect)

        # Draw rubber-band selection rectangle while dragging digital zoom region
        if self._zoom_dragging:
            sel_rect = QRect(self._zoom_drag_start, self._zoom_drag_current).normalized()
            painter.setBrush(QColor(224, 62, 62, 40))
            painter.setPen(QPen(QColor("#e03e3e"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(sel_rect)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # Auto-hide title bar: only draw when mouse is hovering anywhere inside this camera tile
        if self._is_hovered:
            self._draw_osd(painter, rect)
        else:
            self._selector_badge_rect = QRect()
            self._zoom_btn_rect = QRect()
            self._snap_btn_rect = QRect()

        # Draw minimal, low-prominence 1px border around the tile
        border_color = QColor(145, 42, 42, 150) if self.is_selected else QColor("#14171f")
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(border_color, 1)
        painter.setPen(pen)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def _draw_placeholder(self, painter: QPainter, rect: QRect):
        """Draw status info only when an assigned camera is connecting or has an error."""
        if self.channel_id <= 0:
            return

        cx, cy = rect.center().x(), rect.center().y()

        font_title = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        painter.setFont(font_title)
        painter.setPen(QColor("#555e70"))
        title_rect = QRect(rect.left() + 12, cy - 12, rect.width() - 24, 22)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"CH{self.channel_id:02d} • {self.camera_name}",
        )

        font_sub = QFont("Segoe UI", 9)
        painter.setFont(font_sub)
        if self.state == "error":
            painter.setPen(QColor("#c94a4a"))
        elif self.state == "connecting":
            painter.setPen(QColor("#c9963b"))
        else:
            painter.setPen(QColor("#3d4454"))

        sub_rect = QRect(rect.left() + 16, cy + 12, rect.width() - 32, 20)
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self.status_message,
        )

    def _draw_snapshot_button(self, painter: QPainter, btn_rect: QRect):
        """Draw the Snapshot camera icon button to the left of the Digital Zoom icon."""
        if self._snap_flash_active:
            bg_color = QColor("#2ecc71")
            border_color = QColor("#6be69e")
            icon_color = QColor("#ffffff")
        else:
            bg_color = QColor("#1b212e")
            border_color = QColor("#333d52")
            icon_color = QColor("#d0d8e8")

        painter.setBrush(bg_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(btn_rect, 3, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Draw crisp vector camera body + lens
        cx = btn_rect.center().x()
        cy = btn_rect.center().y() + 1
        body_rect = QRect(cx - 7, cy - 4, 14, 9)
        painter.setPen(QPen(icon_color, 1.4))
        painter.drawRoundedRect(body_rect, 1.5, 1.5)
        # Top viewfinder bump
        painter.drawLine(cx - 3, cy - 6, cx + 3, cy - 6)
        # Center lens circle
        painter.drawEllipse(QPoint(cx, cy), 2, 2)

    def _draw_magnifier_button(self, painter: QPainter, btn_rect: QRect):
        """Draw the magnifying glass digital zoom button (between Snapshot icon and camera dropdown)."""
        is_zoomed = self._zoom_norm_rect is not None
        is_armed = self._zoom_selecting

        if is_zoomed or is_armed:
            bg_color = QColor("#e03e3e")
            border_color = QColor("#ff6b6b")
            icon_color = QColor("#ffffff")
        else:
            bg_color = QColor("#1b212e")
            border_color = QColor("#333d52")
            icon_color = QColor("#d0d8e8")

        painter.setBrush(bg_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(btn_rect, 3, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Draw crisp vector magnifying glass lens & handle
        cx = btn_rect.center().x() - 2
        cy = btn_rect.center().y() - 2
        radius = 4
        painter.setPen(QPen(icon_color, 1.6))
        painter.drawEllipse(QPoint(cx, cy), radius, radius)
        painter.drawLine(cx + 3, cy + 3, cx + 7, cy + 7)

        if is_zoomed:
            painter.setPen(QPen(icon_color, 1.4))
            painter.drawLine(cx - 2, cy, cx + 2, cy)

    def _draw_osd(self, painter: QPainter, rect: QRect):
        bar_height = 28
        bar_rect = QRect(rect.left() + 2, rect.top() + 2, rect.width() - 4, bar_height)

        badge_w = 64
        badge_rect = QRect(bar_rect.right() - badge_w - 6, bar_rect.top() + 4, badge_w, bar_height - 8)
        self._selector_badge_rect = badge_rect

        # If no camera is assigned to this view, draw ONLY the little corner dropdown box on hover
        if self.channel_id <= 0:
            self._zoom_btn_rect = QRect()
            self._snap_btn_rect = QRect()
            painter.setBrush(QColor(22, 27, 36, 190))
            painter.setPen(QPen(QColor("#2c3546"), 1))
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            font_badge = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
            painter.setFont(font_badge)
            painter.setPen(QColor("#8e99ad"))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "Cam ▾")
            return

        # Position the magnifying glass button immediately to the left of the camera dropdown badge
        icon_w = 26
        zoom_rect = QRect(badge_rect.left() - icon_w - 5, bar_rect.top() + 4, icon_w, bar_height - 8)
        self._zoom_btn_rect = zoom_rect

        # Position the Snapshot camera icon button immediately to the left of the magnifying glass button
        snap_rect = QRect(zoom_rect.left() - icon_w - 5, bar_rect.top() + 4, icon_w, bar_height - 8)
        self._snap_btn_rect = snap_rect

        if not self.show_osd:
            self._draw_snapshot_button(painter, snap_rect)
            self._draw_magnifier_button(painter, zoom_rect)
            painter.setBrush(QColor(22, 27, 36, 180))
            painter.setPen(QPen(QColor("#2c3546"), 1))
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            font_badge = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
            painter.setFont(font_badge)
            painter.setPen(QColor("#b8c2d4"))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, f"CH{self.channel_id:02d} ▾")
            return

        # Active camera OSD bar (shown on hover)
        painter.fillRect(bar_rect, QColor(0, 0, 0, 175))

        dot_color = {
            "connected": QColor("#2ecc71"),
            "connecting": QColor("#f39c12"),
            "error": QColor("#e74c3c"),
            "disconnected": QColor("#555d6d"),
        }.get(self.state, QColor("#555d6d"))

        painter.setBrush(dot_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(bar_rect.left() + 10, bar_rect.top() + 9, 8, 8)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Left text: Camera Channel & Name (+ ZOOM/SAVED state hint if active)
        font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#e8ecf2"))
        state_tag = ""
        if self._snap_flash_active:
            state_tag = "  [SNAPSHOT SAVED]"
        elif self._zoom_norm_rect is not None:
            state_tag = "  [ZOOMED]"
        elif self._zoom_selecting:
            state_tag = "  [DRAG AREA TO ZOOM]"
        left_text = f"CH{self.channel_id:02d}  {self.camera_name}{state_tag}"
        painter.drawText(
            bar_rect.adjusted(24, 0, -270, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            left_text,
        )

        # Draw Snapshot button (left of zoom) and Magnifying Glass Digital Zoom button (left of dropdown)
        self._draw_snapshot_button(painter, snap_rect)
        self._draw_magnifier_button(painter, zoom_rect)

        # Interactive "CHxx ▾" selector button in top-right corner
        painter.setBrush(QColor("#1b212e"))
        painter.setPen(QPen(QColor("#333d52"), 1))
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        font_badge = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font_badge)
        painter.setPen(QColor("#d0d8e8"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, f"CH{self.channel_id:02d} ▾")

        # Stream resolution + FPS info to the left of the Snapshot button
        font_meta = QFont("Consolas", 8, QFont.Weight.Bold)
        painter.setFont(font_meta)
        if self.state == "connected" and self.frame_width > 0:
            stream_tag = "HD" if self.stream_type == "main" else "SD"
            meta_text = f"[{stream_tag}] {self.frame_width}x{self.frame_height} {self.fps:.0f}fps"
            painter.setPen(QColor("#9ec5fe") if self.stream_type == "main" else QColor("#a3cfbb"))
        else:
            meta_text = self.state.upper()
            painter.setPen(QColor("#768094"))

        right_offset = (bar_rect.right() - snap_rect.left()) + 8
        painter.drawText(
            bar_rect.adjusted(140, 0, -right_offset, 0),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            meta_text,
        )
