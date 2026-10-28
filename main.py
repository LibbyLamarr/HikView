"""
Entry point for HikView — Standalone Windows Live Viewer for
HiLook by Hikvision NVR-104H-D/4P and Hikvision IP Cameras.
"""

import sys
import ctypes
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from hikview.config import AppConfig
from hikview.main_window import MainWindow


def main():
    # Ensure crisp high-DPI scaling and Windows taskbar icon grouping
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("hikview.nvr.viewer.1.0")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("HikView")
    app.setOrganizationName("HikView")

    config = AppConfig.load()
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
