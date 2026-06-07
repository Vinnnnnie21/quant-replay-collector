from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from PySide6 import QtCore

try:
    from app_logger import get_logger
    from services.analysis_refresh import AnalysisRefreshSnapshot, DeferredAnalysisRefresh
    from workers.analysis_refresh_worker import AnalysisRefreshWorker
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger
    from ..services.analysis_refresh import AnalysisRefreshSnapshot, DeferredAnalysisRefresh
    from ..workers.analysis_refresh_worker import AnalysisRefreshWorker


logger = get_logger(__name__)


class AnalysisRefreshController(QtCore.QObject):
    """Coordinate deferred analysis workers without owning any Qt widgets."""

    requestRun = QtCore.Signal(object)
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
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._snapshot_factory = snapshot_factory
        self._is_playing = is_playing
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._single_shot = single_shot
        self._scheduler = DeferredAnalysisRefresh(delay_ms=delay_ms)
        self._thread = None
        self._worker = None
        self._worker_deletes_on_thread_finish = False
        self._started_at: float | None = None
        self._rerun_requested = False
        self._shutting_down = False

    @property
    def pending(self) -> bool:
        return bool(self._scheduler.pending)

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def schedule(self) -> bool:
        if self._shutting_down:
            return False
        if self.is_running:
            self._rerun_requested = True
            return False
        return self._scheduler.schedule(self._single_shot, self._try_start)

    def resume_if_idle(self) -> bool:
        if self._shutting_down:
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
        if self._shutting_down:
            return
        if not self._scheduler.should_run(
            is_playing=bool(self._is_playing()),
            is_running=self.is_running,
        ):
            return

        self._started_at = time.perf_counter()
        try:
            snapshot = self._snapshot_factory()
            self._start_worker(snapshot)
        except Exception as exc:
            logger.exception("Failed to start analysis refresh.")
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            self._finish_cycle()

    def _start_worker(self, snapshot: AnalysisRefreshSnapshot | Any) -> None:
        self._thread = self._thread_factory(self)
        self._worker = self._worker_factory()
        self._worker.moveToThread(self._thread)
        self.requestRun.connect(self._worker.run, QtCore.Qt.QueuedConnection)
        self._worker.finished.connect(self._on_worker_finished, QtCore.Qt.QueuedConnection)
        self._worker.failed.connect(self._on_worker_failed, QtCore.Qt.QueuedConnection)
        thread_finished = getattr(self._thread, "finished", None)
        if thread_finished is not None and hasattr(thread_finished, "connect"):
            thread_finished.connect(self._worker.deleteLater)
            self._worker_deletes_on_thread_finish = True
        else:
            self._worker_deletes_on_thread_finish = False
        self._thread.start()
        self.requestRun.emit(snapshot)

    @QtCore.Slot(object)
    def _on_worker_finished(self, result: Any) -> None:
        try:
            self.resultReady.emit(result)
        finally:
            self._finish_cycle()

    @QtCore.Slot(str)
    def _on_worker_failed(self, error: str) -> None:
        try:
            self.failed.emit(error)
        finally:
            self._finish_cycle()

    def _finish_cycle(self) -> None:
        started = self._started_at
        self._scheduler.pending = False
        self._cleanup_worker()
        self._started_at = None
        if started is not None:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if elapsed_ms >= 250.0:
                logger.warning("Analysis refresh took %.1f ms.", elapsed_ms)
        if self._rerun_requested and not self._shutting_down:
            self._rerun_requested = False
            self._scheduler.schedule(self._single_shot, self._try_start)

    def _cleanup_worker(self) -> None:
        worker = self._worker
        thread = self._thread
        if worker is not None:
            try:
                self.requestRun.disconnect(worker.run)
            except (RuntimeError, TypeError):
                pass
        if thread is not None:
            thread.quit()
            if thread.wait(1000) is False:
                thread.wait()
        if worker is not None and not self._worker_deletes_on_thread_finish:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        self._worker = None
        self._thread = None
        self._worker_deletes_on_thread_finish = False

    def shutdown(self) -> None:
        self._shutting_down = True
        self._rerun_requested = False
        self._scheduler.pending = False
        self._cleanup_worker()
        self._started_at = None


__all__ = ["AnalysisRefreshController"]
