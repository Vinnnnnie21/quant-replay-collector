from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore

try:
    from workers.export_worker import ExportWorker
except ImportError:  # pragma: no cover - package import path
    from ..workers.export_worker import ExportWorker


class ExportTaskController(QtCore.QObject):
    """Own one background export task without owning any Qt widgets."""

    progress = QtCore.Signal(str)
    finished = QtCore.Signal(str, object, float)
    failed = QtCore.Signal(str, float)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        *,
        worker_factory: Callable[..., Any] = ExportWorker,
        thread_factory: Callable[[QtCore.QObject], Any] = QtCore.QThread,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._thread = None
        self._worker = None
        self._worker_deletes_on_thread_finish = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, db_path: str | Path, request: Any) -> bool:
        if self.is_running:
            return False
        try:
            self._thread = self._thread_factory(self)
            self._worker = self._worker_factory(
                str(db_path),
                request.session_id,
                request.target,
                request.language,
                request.selected_label,
            )
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.progress.connect(self.progress, QtCore.Qt.QueuedConnection)
            self._worker.finished.connect(self._on_finished, QtCore.Qt.QueuedConnection)
            self._worker.failed.connect(self._on_failed, QtCore.Qt.QueuedConnection)
            self._worker.cancelled.connect(self._on_cancelled, QtCore.Qt.QueuedConnection)
            thread_finished = getattr(self._thread, "finished", None)
            if thread_finished is not None and hasattr(thread_finished, "connect"):
                thread_finished.connect(self._worker.deleteLater)
                self._worker_deletes_on_thread_finish = True
            self._thread.start()
            return True
        except Exception as exc:
            self._finish()
            self.failed.emit(f"{type(exc).__name__}: {exc}", 0.0)
            return False

    def cancel(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.cancel()

    @QtCore.Slot(str, object, float)
    def _on_finished(self, output_dir: str, warnings: list, elapsed: float) -> None:
        self._finish()
        self.finished.emit(output_dir, warnings, elapsed)

    @QtCore.Slot(str, float)
    def _on_failed(self, error: str, elapsed: float) -> None:
        self._finish()
        self.failed.emit(error, elapsed)

    @QtCore.Slot()
    def _on_cancelled(self) -> None:
        self._finish()
        self.cancelled.emit()

    def _finish(self) -> None:
        worker = self._worker
        thread = self._thread
        if thread is None:
            return
        thread.quit()
        if thread.wait(1000) is False:
            thread.wait()
        if worker is not None and not self._worker_deletes_on_thread_finish:
            worker.deleteLater()
        thread.deleteLater()
        self._worker = None
        self._thread = None
        self._worker_deletes_on_thread_finish = False

    def shutdown(self) -> None:
        self.cancel()
        self._finish()


__all__ = ["ExportTaskController"]
