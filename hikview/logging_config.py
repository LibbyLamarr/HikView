"""
Application-wide logging, crash diagnostics, and unhandled exception protection for HikView.
"""

import sys
import os
import logging
from logging.handlers import RotatingFileHandler
import traceback
from pathlib import Path
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
from PyQt6.QtWidgets import QApplication, QMessageBox

from .config import get_config_dir

_LOGGER_INITIALIZED = False


class LogStream:
    """Redirect writes (e.g. from print, stdout, stderr) safely to the logging module."""
    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.level = level
        self._buffer = ""

    def write(self, message: str):
        if not message:
            return
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line:
                self.logger.log(self.level, line)

    def flush(self):
        if self._buffer.strip():
            self.logger.log(self.level, self._buffer.strip())
            self._buffer = ""


def get_log_file_path() -> Path:
    """Return path to the hikview.log file in AppData."""
    return get_config_dir() / "hikview.log"


def _qt_message_handler(mode: QtMsgType, context, message: str):
    """Route internal Qt messages to Python logging."""
    logger = logging.getLogger("HikView.Qt")
    if mode == QtMsgType.QtDebugMsg:
        logger.debug(message)
    elif mode == QtMsgType.QtInfoMsg:
        logger.info(message)
    elif mode == QtMsgType.QtWarningMsg:
        logger.warning(message)
    elif mode == QtMsgType.QtCriticalMsg:
        logger.error(message)
    elif mode == QtMsgType.QtFatalMsg:
        logger.critical(f"FATAL: {message}")


def _exception_hook(exc_type, exc_value, exc_traceback):
    """Global exception hook to capture unhandled exceptions and prevent silent app crashes."""
    logger = logging.getLogger("HikView.Crash")
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    tb_text = "".join(tb_lines)
    logger.critical(f"Unhandled Exception:\n{tb_text}")

    # Show an error notification if the Qt application is active
    app = QApplication.instance()
    if app and not issubclass(exc_type, KeyboardInterrupt):
        try:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("HikView — Unexpected Error")
            msg_box.setText("An unexpected error occurred in HikView.")
            msg_box.setInformativeText(f"{exc_type.__name__}: {exc_value}\n\nDetails have been logged to:\n{get_log_file_path()}")
            msg_box.setDetailedText(tb_text)
            msg_box.exec()
        except Exception:
            pass


def setup_logging():
    """Initialize logging, stream redirection, and crash hooks."""
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return
    _LOGGER_INITIALIZED = True

    log_file = get_log_file_path()
    log_dir = log_file.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 5MB rotating log with 2 backups
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # If running in console mode or dev, also output to console
    if sys.stdout is not None and hasattr(sys.stdout, "write"):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Prevent NoneType AttributeError when running compiled windowed / noconsole
    stdout_logger = logging.getLogger("STDOUT")
    stderr_logger = logging.getLogger("STDERR")
    if sys.stdout is None:
        sys.stdout = LogStream(stdout_logger, logging.INFO)
    if sys.stderr is None:
        sys.stderr = LogStream(stderr_logger, logging.ERROR)

    # Intercept Qt messages
    qInstallMessageHandler(_qt_message_handler)

    # Intercept unhandled Python exceptions
    sys.excepthook = _exception_hook

    logging.info("HikView application logger initialized. Log file: %s", log_file)
