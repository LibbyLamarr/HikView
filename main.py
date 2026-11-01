"""
Entry point for HikView — Standalone Windows Live Viewer for
HiLook by Hikvision NVR-104H-D/4P and Hikvision IP Cameras.
"""

import sys
import os
import ctypes
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from hikview.config import AppConfig
from hikview.main_window import MainWindow, create_app_icon


def main():
    # Ensure crisp high-DPI scaling and Windows taskbar icon grouping
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("hikview.nvr.viewer.1.0.1")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("HikView")
    app.setOrganizationName("HikView")

    # Set application-level window icon so taskbar, alt-tab, and pinned shortcuts display it properly
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
    else:
        app_icon = create_app_icon()
    app.setWindowIcon(app_icon)

    config = AppConfig.load()
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
