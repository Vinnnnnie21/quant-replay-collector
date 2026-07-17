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
        lifecycle: Any | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._lifecycle = lifecycle
        self._thread = None
        self._worker = None
        self._cancellation_token = None
        self._worker_deletes_on_thread_finish = False
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False
        self._pending_terminal: tuple[str, tuple[Any, ...]] | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, db_path: str | Path, request: Any) -> bool:
        if self.is_running:
            return False
        if self._lifecycle is not None and not self._lifecycle.start("export", request_stop=self.cancel):
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
            self._cancellation_token = getattr(
                self._worker, "cancellation_token", None
            )
            self._worker.moveToThread(self._thread)
            worker_destroyed = getattr(self._worker, "destroyed", None)
            if worker_destroyed is not None and hasattr(worker_destroyed, "connect"):
                worker_destroyed.connect(self._on_worker_destroyed)
                self._worker_destroyed_signal_connected = True
            self._thread.started.connect(self._worker.run)
            self._worker.progress.connect(self.progress, QtCore.Qt.QueuedConnection)
            self._worker.finished.connect(self._on_finished, QtCore.Qt.QueuedConnection)
            self._worker.failed.connect(self._on_failed, QtCore.Qt.QueuedConnection)
            self._worker.cancelled.connect(self._on_cancelled, QtCore.Qt.QueuedConnection)
            thread_finished = getattr(self._thread, "finished", None)
            if thread_finished is not None and hasattr(thread_finished, "connect"):
                thread_finished.connect(self._worker.deleteLater)
                thread_finished.connect(self._on_thread_finished)
                thread_finished.connect(self._thread.deleteLater)
                self._worker_deletes_on_thread_finish = True
            thread_destroyed = getattr(self._thread, "destroyed", None)
            if thread_destroyed is not None and hasattr(thread_destroyed, "connect"):
                thread_destroyed.connect(self._on_thread_destroyed)
                self._thread_destroyed_signal_connected = True
            self._thread.start()
            return True
        except Exception as exc:
            thread = self._thread
            is_running = getattr(thread, "isRunning", lambda: False)
            if thread is not None and bool(is_running()):
                self._pending_terminal = (
                    "failed",
                    (f"{type(exc).__name__}: {exc}", 0.0),
                )
                self.cancel()
                thread.quit()
                return False
            self._finish()
            if self._lifecycle is not None:
                self._lifecycle.fail("export", f"{type(exc).__name__}: {exc}")
            self.failed.emit(f"{type(exc).__name__}: {exc}", 0.0)
            return False

    def cancel(self) -> None:
        request = getattr(self._cancellation_token, "request", None)
        if callable(request):
            request()

    @QtCore.Slot(str, object, float)
    def _on_finished(self, output_dir: str, warnings: list, elapsed: float) -> None:
        self._begin_thread_teardown("finished", output_dir, warnings, elapsed)

    @QtCore.Slot(str, float)
    def _on_failed(self, error: str, elapsed: float) -> None:
        self._begin_thread_teardown("failed", error, elapsed)

    @QtCore.Slot()
    def _on_cancelled(self) -> None:
        self._begin_thread_teardown("cancelled")

    def _begin_thread_teardown(self, outcome: str, *args: Any) -> None:
        if self._pending_terminal is not None:
            return
        self._pending_terminal = (outcome, args)
        thread = self._thread
        if thread is None:
            self._on_thread_finished()
            return
        thread.quit()

    @QtCore.Slot()
    def _on_thread_finished(self) -> None:
        if self._thread_destroyed_signal_connected:
            return
        self._cleanup_finished_thread()
        self._complete_terminal()

    def _complete_terminal(self) -> None:
        terminal = self._pending_terminal
        self._pending_terminal = None
        if terminal is None:
            return
        outcome, args = terminal
        if outcome == "finished":
            if self._lifecycle is not None:
                self._lifecycle.complete("export")
            self.finished.emit(*args)
        elif outcome == "failed":
            error, elapsed = args
            if self._lifecycle is not None:
                self._lifecycle.fail("export", str(error))
            self.failed.emit(str(error), float(elapsed))
        else:
            if self._lifecycle is not None:
                self._lifecycle.complete("export")
            self.cancelled.emit()

    def _finish(self) -> None:
        worker = self._worker
        thread = self._thread
        if thread is None:
            return
        thread.quit()
        if worker is not None:
            worker.deleteLater()
        thread.deleteLater()
        self._worker = None
        self._thread = None
        self._cancellation_token = None
        self._worker_deletes_on_thread_finish = False
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False

    @QtCore.Slot()
    def _on_worker_destroyed(self) -> None:
        self._worker = None

    @QtCore.Slot()
    def _on_thread_destroyed(self) -> None:
        self._thread = None
        self._cancellation_token = None
        if not self._worker_destroyed_signal_connected:
            self._worker = None
        self._worker_deletes_on_thread_finish = False
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False
        self._complete_terminal()

    def _cleanup_finished_thread(self) -> None:
        worker = self._worker
        thread = self._thread
        if thread is None:
            return
        if worker is not None and not self._worker_deletes_on_thread_finish:
            worker.deleteLater()
        self._worker = None
        self._thread = None
        self._cancellation_token = None
        self._worker_deletes_on_thread_finish = False
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False

    def shutdown(self) -> bool:
        self.cancel()
        return not self.is_running


__all__ = ["ExportTaskController"]
