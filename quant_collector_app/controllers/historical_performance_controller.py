from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6 import QtCore


@dataclass(frozen=True)
class HistoricalPerformanceRequest:
    session_id: str
    revision: int


@dataclass(frozen=True)
class _HistoricalPerformanceStartFailure:
    revision: int
    message: str


class HistoricalPerformanceController(QtCore.QObject):
    """Run one cancellable historical-performance request outside the UI thread."""

    requestRun = QtCore.Signal(object)
    resultReady = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        *,
        db_path: str | Path,
        worker_factory: Callable[[str], Any] | None = None,
        thread_factory: Callable[[QtCore.QObject], Any] = QtCore.QThread,
        lifecycle: Any | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if worker_factory is None:
            try:
                from workers.historical_performance_worker import HistoricalPerformanceWorker
            except ImportError:  # pragma: no cover - package import path
                from ..workers.historical_performance_worker import HistoricalPerformanceWorker

            worker_factory = HistoricalPerformanceWorker
        self._db_path = str(db_path)
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._lifecycle = lifecycle
        self._latest_revision = 0
        self._thread: QtCore.QThread | None = None
        self._worker: Any | None = None
        self._cancellation_token = None
        self._terminal: tuple[str, Any] | None = None
        self._pending_request: HistoricalPerformanceRequest | None = None
        self._shutting_down = False
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def request(self, session_id: str) -> bool:
        if self._shutting_down:
            return False
        self._latest_revision += 1
        request = HistoricalPerformanceRequest(str(session_id), self._latest_revision)
        if self.is_running:
            self._pending_request = request
            self._cancel_active()
            return False
        return self._start_request(request)

    def _start_request(self, request: HistoricalPerformanceRequest) -> bool:
        if self._lifecycle is not None:
            task_active = "historical_performance" in self._lifecycle.active_tasks
            if not task_active and not self._lifecycle.start(
                "historical_performance",
                request_stop=self.request_stop,
            ):
                return False
        try:
            thread = self._thread_factory(self)
            worker = self._worker_factory(self._db_path)
            self._thread = thread
            self._worker = worker
            self._cancellation_token = getattr(worker, "cancellation_token", None)
            worker.moveToThread(thread)
            worker_destroyed = getattr(worker, "destroyed", None)
            if worker_destroyed is not None and hasattr(worker_destroyed, "connect"):
                worker_destroyed.connect(self._on_worker_destroyed)
                self._worker_destroyed_signal_connected = True
            self.requestRun.connect(worker.run, QtCore.Qt.QueuedConnection)
            worker.finished.connect(self._on_finished, QtCore.Qt.QueuedConnection)
            worker.failed.connect(self._on_failed, QtCore.Qt.QueuedConnection)
            worker.cancelled.connect(self._on_cancelled, QtCore.Qt.QueuedConnection)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(self._on_thread_finished)
            thread.finished.connect(thread.deleteLater)
            thread_destroyed = getattr(thread, "destroyed", None)
            if thread_destroyed is not None and hasattr(thread_destroyed, "connect"):
                thread_destroyed.connect(self._on_thread_destroyed)
                self._thread_destroyed_signal_connected = True
            thread.start()
            self.requestRun.emit(request)
            return True
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            thread = self._thread
            is_running = getattr(thread, "isRunning", lambda: False)
            if thread is not None and bool(is_running()):
                self._terminal = (
                    "failed",
                    _HistoricalPerformanceStartFailure(request.revision, message),
                )
                self._cancel_active()
                thread.quit()
                return False
            worker = self._worker
            if worker is not None:
                worker.deleteLater()
            if thread is not None:
                thread.deleteLater()
            self._worker = None
            self._thread = None
            self._cancellation_token = None
            if self._lifecycle is not None:
                self._lifecycle.fail("historical_performance", message)
            self.failed.emit(message)
            return False

    @QtCore.Slot(object)
    def _on_finished(self, result: Any) -> None:
        self._finish_thread("finished", result)

    @QtCore.Slot(object)
    def _on_failed(self, error: Any) -> None:
        self._finish_thread("failed", error)

    @QtCore.Slot(object)
    def _on_cancelled(self, event: Any) -> None:
        self._finish_thread("cancelled", event)

    def _finish_thread(self, kind: str, event: Any) -> None:
        if self._terminal is not None:
            return
        self._terminal = (kind, event)
        if self._thread is not None:
            self._thread.quit()

    @QtCore.Slot()
    def _on_thread_finished(self) -> None:
        if self._thread_destroyed_signal_connected:
            return
        self._clear_finished_wrappers()
        self._complete_terminal()

    def _complete_terminal(self) -> None:
        terminal = self._terminal
        self._terminal = None
        if terminal is None:
            return
        kind, event = terminal
        revision = getattr(event, "revision", None)
        if self._pending_request is not None and not self._shutting_down:
            pending = self._pending_request
            self._pending_request = None
            self._start_request(pending)
            return
        if self._shutting_down:
            if self._lifecycle is not None:
                self._lifecycle.complete("historical_performance")
            return
        if revision != self._latest_revision:
            return
        if kind == "finished":
            if self._lifecycle is not None:
                self._lifecycle.complete("historical_performance")
            self.resultReady.emit(event)
        elif kind == "failed":
            message = str(getattr(event, "message", event))
            if self._lifecycle is not None:
                self._lifecycle.fail("historical_performance", message)
            self.failed.emit(message)
        elif self._lifecycle is not None:
            self._lifecycle.complete("historical_performance")

    def _clear_finished_wrappers(self) -> None:
        self._thread = None
        self._worker = None
        self._cancellation_token = None
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
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False
        self._complete_terminal()

    def _cancel_active(self) -> None:
        request = getattr(self._cancellation_token, "request", None)
        if callable(request):
            request()

    def request_stop(self) -> None:
        self._shutting_down = True
        self._pending_request = None
        self._cancel_active()

    def shutdown(self) -> bool:
        self.request_stop()
        return not self.is_running


__all__ = ["HistoricalPerformanceController", "HistoricalPerformanceRequest"]
