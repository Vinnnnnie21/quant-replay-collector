from __future__ import annotations

import faulthandler
import threading
import time
from pathlib import Path

from PySide6 import QtCore

try:
    from app_config import LOG_DIR
    from app_logger import get_logger
except ImportError:  # pragma: no cover - package import path
    from .app_config import LOG_DIR
    from .app_logger import get_logger


logger = get_logger(__name__)


class UiFreezeWatchdog(QtCore.QObject):
    """Main-thread heartbeat watchdog.

    It only writes logs/dumps. It deliberately avoids message boxes because the
    UI may already be blocked.
    """

    def __init__(
        self,
        *,
        log_dir: str | Path = LOG_DIR,
        logger=None,
        warning_after_seconds: float = 2.0,
        dump_after_seconds: float = 5.0,
        interval_ms: int = 500,
        background_interval_seconds: float = 0.5,
        start_background: bool | None = None,
        parent=None,
        start: bool = True,
    ) -> None:
        super().__init__(parent)
        self.log_dir = Path(log_dir)
        self.logger = logger or globals()["logger"]
        self.warning_after_seconds = float(warning_after_seconds)
        self.dump_after_seconds = float(dump_after_seconds)
        self.background_interval_seconds = max(0.01, float(background_interval_seconds))
        self._last_heartbeat = time.monotonic()
        self._last_warning_at = 0.0
        self._last_dump_at = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        if start:
            self._timer.start(max(100, int(interval_ms)))
        should_start_background = start if start_background is None else bool(start_background)
        if should_start_background:
            self.start_background_thread()

    def record_heartbeat(self, now: float | None = None) -> None:
        with self._lock:
            self._last_heartbeat = time.monotonic() if now is None else float(now)

    def _on_timer(self) -> None:
        self.check()
        self.record_heartbeat()

    def start_background_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._background_loop,
            name="qrc-ui-freeze-watchdog",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self) -> None:
        self._timer.stop()
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _background_loop(self) -> None:
        while not self._stop_event.wait(self.background_interval_seconds):
            self.check()

    def check(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            delayed = current - self._last_heartbeat
        if delayed >= self.warning_after_seconds and current - self._last_warning_at >= self.warning_after_seconds:
            self._last_warning_at = current
            self.logger.warning("UI heartbeat delayed %.3fs; possible main-thread freeze.", delayed)
        if delayed >= self.dump_after_seconds and current - self._last_dump_at >= self.dump_after_seconds:
            self._last_dump_at = current
            self._dump_traceback(current, delayed)

    def _dump_traceback(self, current: float, delayed: float) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            path = self.log_dir / f"freeze_dump_{int(current * 1000)}.log"
            with path.open("w", encoding="utf-8") as handle:
                handle.write(f"UI heartbeat delayed {delayed:.3f}s\n")
                faulthandler.dump_traceback(file=handle, all_threads=True)
            self.logger.error("UI freeze traceback dumped to %s", path)
        except Exception:
            self.logger.exception("Failed to dump UI freeze traceback.")


__all__ = ["UiFreezeWatchdog"]
