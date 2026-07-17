from __future__ import annotations

import time
import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6 import QtCore

try:
    from app_logger import get_logger
    from services.analysis_refresh import (
        AnalysisRefreshRequest,
        AnalysisRefreshFailure,
        AnalysisRefreshSnapshot,
        DeferredAnalysisRefresh,
    )
    from workers.analysis_refresh_worker import AnalysisRefreshWorker
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger
    from ..services.analysis_refresh import (
        AnalysisRefreshRequest,
        AnalysisRefreshFailure,
        AnalysisRefreshSnapshot,
        DeferredAnalysisRefresh,
    )
    from ..workers.analysis_refresh_worker import AnalysisRefreshWorker


logger = get_logger(__name__)


class AnalysisRefreshController(QtCore.QObject):
    """Coordinate deferred analysis workers without owning any Qt widgets."""

    requestRun = QtCore.Signal(object)
    progress = QtCore.Signal(str)
    resultReady = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        *,
        snapshot_factory: Callable[[], AnalysisRefreshSnapshot | Any],
        is_playing: Callable[[], bool],
        delay_ms: int = 300,
        worker_factory: Callable[[], Any] = AnalysisRefreshWorker,
        thread_factory: Callable[[QtCore.QObject], Any] = QtCore.QThread,
        single_shot: Callable[[int, Callable[[], None]], None] = QtCore.QTimer.singleShot,
        lifecycle: Any | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._snapshot_factory = snapshot_factory
        self._is_playing = is_playing
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._single_shot = single_shot
        self._lifecycle = lifecycle
        self._scheduler = DeferredAnalysisRefresh(delay_ms=delay_ms)
        self._thread = None
        self._worker = None
        self._cancellation_token = None
        self._worker_deletes_on_thread_finish = False
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False
        self._started_at: float | None = None
        self._rerun_requested = False
        self._shutting_down = False
        self._latest_revision = 0
        self._active_revision: int | None = None
        self._pending_terminal: tuple[str, tuple[Any, ...]] | None = None

    @property
    def pending(self) -> bool:
        return bool(self._scheduler.pending)

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def _shutdown_in_progress(self) -> bool:
        return bool(
            self._shutting_down
            or (self._lifecycle is not None and self._lifecycle.shutdown_in_progress)
        )

    def schedule(self) -> bool:
        if self._shutdown_in_progress():
            return False
        self._latest_revision += 1
        if self.is_running:
            self._rerun_requested = True
            return False
        return self._scheduler.schedule(self._single_shot, self._try_start)

    def resume_if_idle(self) -> bool:
        if self._shutdown_in_progress():
            return False
        if self._scheduler.should_run(
            is_playing=bool(self._is_playing()),
            is_running=self.is_running,
        ):
            self._single_shot(0, self._try_start)
            return True
        return False

    @QtCore.Slot()
    def _try_start(self) -> None:
        if self._shutdown_in_progress():
            self._scheduler.pending = False
            self._rerun_requested = False
            return
        if not self._scheduler.should_run(
            is_playing=bool(self._is_playing()),
            is_running=self.is_running,
        ):
            return

        self._started_at = time.perf_counter()
        if self._lifecycle is not None:
            task_active = "analysis_refresh" in self._lifecycle.active_tasks
            if not task_active and not self._lifecycle.start(
                "analysis_refresh",
                request_stop=self.request_stop,
            ):
                self._finish_cycle()
                return
        try:
            capture_started = time.perf_counter()
            snapshot = self._snapshot_factory()
            capture_seconds = time.perf_counter() - capture_started
            revision = self._latest_revision
            if isinstance(snapshot, AnalysisRefreshRequest):
                snapshot = replace(
                    snapshot,
                    revision=revision,
                    ui_input_capture_seconds=capture_seconds,
                    ui_thread_id=threading.get_ident(),
                )
            elif isinstance(snapshot, AnalysisRefreshSnapshot):
                snapshot = replace(snapshot, revision=revision)
            self._active_revision = revision
            self._start_worker(snapshot)
        except Exception as exc:
            logger.exception("Failed to start analysis refresh.")
            message = f"{type(exc).__name__}: {exc}"
            thread = self._thread
            is_running = getattr(thread, "isRunning", lambda: False)
            if thread is not None and bool(is_running()):
                self._begin_thread_teardown(
                    "failed",
                    AnalysisRefreshFailure(self._latest_revision, message),
                )
                return
            worker = self._worker
            if worker is not None:
                worker.deleteLater()
            if thread is not None:
                thread.deleteLater()
            self._worker = None
            self._thread = None
            self._cancellation_token = None
            self._worker_deletes_on_thread_finish = False
            if self._lifecycle is not None:
                self._lifecycle.fail("analysis_refresh", message)
            self.failed.emit(message)
            self._finish_cycle()

    def _start_worker(self, snapshot: AnalysisRefreshSnapshot | Any) -> None:
        self._thread = self._thread_factory(self)
        self._worker = self._worker_factory()
        self._cancellation_token = getattr(self._worker, "cancellation_token", None)
        self._worker.moveToThread(self._thread)
        worker_destroyed = getattr(self._worker, "destroyed", None)
        if worker_destroyed is not None and hasattr(worker_destroyed, "connect"):
            worker_destroyed.connect(self._on_worker_destroyed)
            self._worker_destroyed_signal_connected = True
        self.requestRun.connect(self._worker.run, QtCore.Qt.QueuedConnection)
        worker_progress = getattr(self._worker, "progress", None)
        if worker_progress is not None:
            worker_progress.connect(self._on_worker_progress, QtCore.Qt.QueuedConnection)
        self._worker.finished.connect(self._on_worker_finished, QtCore.Qt.QueuedConnection)
        self._worker.failed.connect(self._on_worker_failed, QtCore.Qt.QueuedConnection)
        cancelled = getattr(self._worker, "cancelled", None)
        if cancelled is not None:
            cancelled.connect(self._on_worker_cancelled, QtCore.Qt.QueuedConnection)
        thread_finished = getattr(self._thread, "finished", None)
        if thread_finished is not None and hasattr(thread_finished, "connect"):
            thread_finished.connect(self._worker.deleteLater)
            thread_finished.connect(self._on_thread_finished)
            thread_finished.connect(self._thread.deleteLater)
            self._worker_deletes_on_thread_finish = True
        else:
            self._worker_deletes_on_thread_finish = False
        thread_destroyed = getattr(self._thread, "destroyed", None)
        if thread_destroyed is not None and hasattr(thread_destroyed, "connect"):
            thread_destroyed.connect(self._on_thread_destroyed)
            self._thread_destroyed_signal_connected = True
        self._thread.start()
        self.requestRun.emit(snapshot)

    @QtCore.Slot(object)
    def _on_worker_progress(self, event: Any) -> None:
        revision = getattr(event, "revision", self._active_revision)
        if revision != self._latest_revision:
            return
        self.progress.emit(str(getattr(event, "message", event)))

    @QtCore.Slot(object)
    def _on_worker_finished(self, result: Any) -> None:
        self._begin_thread_teardown("finished", result)

    @QtCore.Slot(object)
    def _on_worker_failed(self, error: Any) -> None:
        self._begin_thread_teardown("failed", error)

    @QtCore.Slot(object)
    def _on_worker_cancelled(self, event: Any = None) -> None:
        self._begin_thread_teardown("cancelled", event)

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
        self._complete_pending_terminal()

    def _complete_pending_terminal(self) -> None:
        terminal = self._pending_terminal
        self._pending_terminal = None
        if terminal is None:
            return
        outcome, args = terminal
        event = args[0] if args else None
        terminal_revision = getattr(event, "revision", self._active_revision)
        has_newer_revision = bool(
            self._rerun_requested
            and terminal_revision != self._latest_revision
            and not self._shutting_down
        )
        if has_newer_revision:
            self._finish_cycle()
            return
        if outcome == "finished":
            result = event
            result_revision = terminal_revision
            if result_revision == self._latest_revision:
                self.resultReady.emit(result)
            if self._lifecycle is not None:
                self._lifecycle.complete("analysis_refresh")
        elif outcome == "failed":
            error = str(getattr(event, "message", event))
            if self._lifecycle is not None:
                self._lifecycle.fail("analysis_refresh", error)
            self.failed.emit(error)
        else:
            if self._lifecycle is not None:
                self._lifecycle.complete("analysis_refresh")
        self._finish_cycle()

    def _finish_cycle(self) -> None:
        started = self._started_at
        self._scheduler.pending = False
        self._started_at = None
        self._active_revision = None
        if started is not None:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if elapsed_ms >= 250.0:
                logger.warning("Analysis refresh took %.1f ms.", elapsed_ms)
        if self._rerun_requested and not self._shutting_down:
            self._rerun_requested = False
            self._scheduler.schedule(self._single_shot, self._try_start)

    def _cleanup_finished_thread(self) -> None:
        worker = self._worker
        thread = self._thread
        # Qt disconnects sender/receiver links when the worker is deleted by
        # QThread.finished. Touching worker.run here can dereference an already
        # destroyed Shiboken wrapper on Windows.
        if worker is not None and not self._worker_deletes_on_thread_finish:
            worker.deleteLater()
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
        self._complete_pending_terminal()

    def request_stop(self) -> None:
        self._shutting_down = True
        self._rerun_requested = False
        self._scheduler.pending = False
        request = getattr(self._cancellation_token, "request", None)
        if callable(request):
            request()

    def shutdown(self) -> bool:
        self.request_stop()
        return not self.is_running


__all__ = ["AnalysisRefreshController"]
