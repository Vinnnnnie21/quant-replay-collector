from __future__ import annotations

import time
from pathlib import Path

from PySide6 import QtCore

try:
    from app_logger import get_logger
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger


logger = get_logger(__name__)


class ExportWorker(QtCore.QObject):
    started = QtCore.Signal()
    progress = QtCore.Signal(str)
    finished = QtCore.Signal(str, object, float)
    failed = QtCore.Signal(str, float)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        db_path: str,
        session_id: str,
        target: Path,
        language: str = "zh_CN",
        selected_label: str = "fwd_ret_10_side_adj",
    ):
        super().__init__()
        self.db_path = str(db_path)
        self.session_id = str(session_id)
        self.target = Path(target)
        self.language = str(language or "zh_CN")
        self.selected_label = str(selected_label or "fwd_ret_10_side_adj")
        self._cancelled = False

    @QtCore.Slot()
    def cancel(self) -> None:
        self._cancelled = True

    @QtCore.Slot()
    def run(self) -> None:
        started = time.perf_counter()
        self.started.emit()
        if self._cancelled:
            self.cancelled.emit()
            return
        try:
            self.progress.emit("Preparing export...")
            try:
                from exporter import Exporter
                from storage import StorageManager
            except ImportError:  # pragma: no cover - package import path
                from ..exporter import Exporter
                from ..storage import StorageManager

            output_dir = Exporter(StorageManager(self.db_path)).export_session(
                self.session_id,
                self.target,
                language=self.language,
                selected_label=self.selected_label,
            )
            if self._cancelled:
                self.cancelled.emit()
                return
            elapsed = time.perf_counter() - started
            self.finished.emit(str(output_dir), [], elapsed)
        except Exception as exc:
            logger.exception("Export background task failed.")
            self.failed.emit(f"{type(exc).__name__}: {exc}", time.perf_counter() - started)
