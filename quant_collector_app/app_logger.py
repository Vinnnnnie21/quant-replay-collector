from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app_config import LOG_DIR


LOG_FILE = Path(LOG_DIR) / "app.log"
_LOGGER_READY = False
_ACTIVE_LOG_FILE = LOG_FILE


def _make_file_handler(path: Path) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )
    return handler


def setup_logging() -> Path:
    global _LOGGER_READY, _ACTIVE_LOG_FILE
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    has_file_handler = any(
        isinstance(handler, RotatingFileHandler)
        and getattr(handler, "baseFilename", "") == str(_ACTIVE_LOG_FILE)
        for handler in root.handlers
    )
    if not has_file_handler:
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            file_handler = _make_file_handler(LOG_FILE)
            _ACTIVE_LOG_FILE = LOG_FILE
        except OSError:
            fallback = LOG_FILE.with_name(
                f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.log"
            )
            try:
                file_handler = _make_file_handler(fallback)
                _ACTIVE_LOG_FILE = fallback
            except OSError:
                file_handler = logging.StreamHandler(sys.stderr)
                _ACTIVE_LOG_FILE = LOG_FILE
        root.addHandler(file_handler)

    logging.captureWarnings(True)
    _LOGGER_READY = True
    return _ACTIVE_LOG_FILE


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def install_exception_hook() -> None:
    setup_logging()
    old_hook = sys.excepthook

    def _log_unhandled(exc_type, exc, tb):
        logging.getLogger("app.unhandled").critical("未捕获异常", exc_info=(exc_type, exc, tb))
        if old_hook and old_hook is not sys.__excepthook__:
            old_hook(exc_type, exc, tb)
        else:
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _log_unhandled
