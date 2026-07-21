from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore

try:
    from services.research_data_availability import ResearchRangeRequest
    from workers.research_backfill_worker import (
        FullHistoryBackfillFailure,
        ResearchBackfillFailure,
        ResearchBackfillTask,
        ResearchBackfillWorker,
        ResearchDataTaskMode,
    )
except ImportError:  # pragma: no cover - package import path
    from ..services.research_data_availability import ResearchRangeRequest
    from ..workers.research_backfill_worker import (
        FullHistoryBackfillFailure,
        ResearchBackfillFailure,
        ResearchBackfillTask,
        ResearchBackfillWorker,
        ResearchDataTaskMode,
    )


class ResearchBackfillController(QtCore.QObject):
    """Own one cancellable research-data worker without owning widgets."""

    requestRun = QtCore.Signal(object)
    progress = QtCore.Signal(object)
    inspected = QtCore.Signal(object)
    auditFailed = QtCore.Signal(object)
    auditCancelled = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(object)
    idle = QtCore.Signal()
    maintenanceFinished = QtCore.Signal(object)
    maintenanceFailed = QtCore.Signal(object)
    maintenanceCancelled = QtCore.Signal(object)

    TASK_NAME = "research_data_backfill"

    def __init__(
        self,
        *,
        db_path: str | Path,
        worker_factory: Callable[[], Any] = ResearchBackfillWorker,
        thread_factory: Callable[[QtCore.QObject], Any] = QtCore.QThread,
        lifecycle: Any | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db_path = str(db_path)
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._lifecycle = lifecycle
        self._thread = None
        self._worker = None
        self._cancellation_token = None
        self._pending_terminal: tuple[str, Any] | None = None
        self._latest_revision = 0
        self._active_revision: int | None = None
        self._active_mode: ResearchDataTaskMode | None = None
        self._last_request: ResearchRangeRequest | None = None
        self._last_mode: ResearchDataTaskMode | None = None
        self._retry_available = False
        self._shutting_down = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    @property
    def can_retry(self) -> bool:
        return bool(
            self._retry_available
            and self._last_request is not None
            and self._last_mode is ResearchDataTaskMode.BACKFILL
            and not self.is_running
            and not self._shutting_down
        )

    def start(self, request: ResearchRangeRequest) -> bool:
        return self._start_task(request, ResearchDataTaskMode.BACKFILL)

    def inspect(self, request: ResearchRangeRequest) -> bool:
        return self._start_task(request, ResearchDataTaskMode.AUDIT)

    def start_full_history(self) -> bool:
        return self._start_task(
            None,
            ResearchDataTaskMode.FULL_HISTORY,
        )

    def _start_task(
        self,
        request: ResearchRangeRequest | None,
        mode: ResearchDataTaskMode,
    ) -> bool:
        if self.is_running or self._shutting_down:
            return False
        if self._lifecycle is not None:
            if self._lifecycle.shutdown_in_progress:
                return False
            if tuple(self._lifecycle.active_tasks):
                return False
            if not self._lifecycle.start(
                self.TASK_NAME,
                request_stop=self.cancel,
            ):
                return False

        self._latest_revision += 1
        self._active_revision = self._latest_revision
        self._active_mode = mode
        self._last_request = request
        self._last_mode = mode
        self._retry_available = False
        try:
            thread = self._thread_factory(self)
            worker = self._worker_factory()
            token = getattr(worker, "cancellation_token", None)
            self._thread = thread
            self._worker = worker
            self._cancellation_token = token
            worker.moveToThread(thread)
            self.requestRun.connect(worker.run, QtCore.Qt.QueuedConnection)
            worker.progress.connect(
                self._on_progress,
                QtCore.Qt.QueuedConnection,
            )
            worker.inspected.connect(
                self._on_inspected,
                QtCore.Qt.QueuedConnection,
            )
            worker.finished.connect(
                self._on_finished,
                QtCore.Qt.QueuedConnection,
            )
            worker.failed.connect(
                self._on_failed,
                QtCore.Qt.QueuedConnection,
            )
            worker.cancelled.connect(
                self._on_cancelled,
                QtCore.Qt.QueuedConnection,
            )
            worker.maintenanceFinished.connect(
                self._on_maintenance_finished,
                QtCore.Qt.QueuedConnection,
            )
            worker.maintenanceFailed.connect(
                self._on_maintenance_failed,
                QtCore.Qt.QueuedConnection,
            )
            worker.maintenanceCancelled.connect(
                self._on_maintenance_cancelled,
                QtCore.Qt.QueuedConnection,
            )
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(self._on_thread_finished)
            thread.finished.connect(thread.deleteLater)
            thread.start()
            self.requestRun.emit(
                ResearchBackfillTask(
                    revision=self._active_revision,
                    db_path=self._db_path,
                    request=request,
                    mode=mode,
                )
            )
            return True
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._handle_start_failure(mode=mode, message=message)
            return False

    def retry(self) -> bool:
        if self._last_request is None or self._last_mode is None:
            return False
        return self._start_task(self._last_request, self._last_mode)

    def invalidate(self) -> None:
        self._latest_revision += 1
        self._last_request = None
        self._last_mode = None
        self._retry_available = False
        self.cancel()

    def cancel(self) -> None:
        request = getattr(self._cancellation_token, "request", None)
        if callable(request):
            request()

    @QtCore.Slot(object)
    def _on_progress(self, event: Any) -> None:
        if getattr(event, "revision", None) == self._latest_revision:
            self.progress.emit(event)

    @QtCore.Slot(object)
    def _on_inspected(self, event: Any) -> None:
        self._begin_teardown("inspected", event)

    @QtCore.Slot(object)
    def _on_finished(self, event: Any) -> None:
        self._begin_teardown("finished", event)

    @QtCore.Slot(object)
    def _on_failed(self, event: Any) -> None:
        self._begin_teardown("failed", event)

    @QtCore.Slot(object)
    def _on_cancelled(self, event: Any) -> None:
        self._begin_teardown("cancelled", event)

    @QtCore.Slot(object)
    def _on_maintenance_finished(self, event: Any) -> None:
        self._begin_teardown("maintenance_finished", event)

    @QtCore.Slot(object)
    def _on_maintenance_failed(self, event: Any) -> None:
        self._begin_teardown("maintenance_failed", event)

    @QtCore.Slot(object)
    def _on_maintenance_cancelled(self, event: Any) -> None:
        self._begin_teardown("maintenance_cancelled", event)

    def _begin_teardown(self, outcome: str, event: Any) -> None:
        if self._pending_terminal is not None:
            return
        self._pending_terminal = (outcome, event)
        thread = self._thread
        if thread is None:
            self._on_thread_finished()
            return
        thread.quit()

    @QtCore.Slot()
    def _on_thread_finished(self) -> None:
        if self._thread is None and self._active_revision is None:
            return
        self._worker = None
        self._thread = None
        self._cancellation_token = None
        terminal = self._pending_terminal
        self._pending_terminal = None
        active_revision = self._active_revision
        active_mode = self._active_mode
        self._active_revision = None
        self._active_mode = None
        if terminal is None:
            self.idle.emit()
            return
        outcome, event = terminal
        revision = getattr(event, "revision", active_revision)
        if revision != self._latest_revision:
            if self._lifecycle is not None:
                self._lifecycle.complete(self.TASK_NAME)
            self.idle.emit()
            return
        if outcome == "maintenance_finished":
            self._retry_available = False
            if self._lifecycle is not None:
                self._lifecycle.complete(self.TASK_NAME)
            self.maintenanceFinished.emit(event)
        elif outcome == "maintenance_failed":
            self._retry_available = False
            if self._lifecycle is not None:
                self._lifecycle.fail(
                    self.TASK_NAME,
                    str(getattr(event, "message", event)),
                )
            self.maintenanceFailed.emit(event)
        elif outcome == "maintenance_cancelled":
            self._retry_available = False
            if self._lifecycle is not None:
                self._lifecycle.complete(self.TASK_NAME)
            self.maintenanceCancelled.emit(event)
        elif outcome == "inspected":
            self._retry_available = False
            if self._lifecycle is not None:
                self._lifecycle.complete(self.TASK_NAME)
            self.inspected.emit(event)
        elif outcome == "finished":
            self._retry_available = False
            if self._lifecycle is not None:
                self._lifecycle.complete(self.TASK_NAME)
            self.finished.emit(event)
        elif outcome == "failed":
            is_audit = active_mode is ResearchDataTaskMode.AUDIT
            self._retry_available = (
                active_mode is ResearchDataTaskMode.BACKFILL
            )
            if self._lifecycle is not None:
                self._lifecycle.fail(
                    self.TASK_NAME,
                    str(getattr(event, "message", event)),
                )
            if is_audit:
                self.auditFailed.emit(event)
            else:
                self.failed.emit(event)
        else:
            is_audit = active_mode is ResearchDataTaskMode.AUDIT
            self._retry_available = (
                active_mode is ResearchDataTaskMode.BACKFILL
            )
            if self._lifecycle is not None:
                self._lifecycle.complete(self.TASK_NAME)
            if is_audit:
                self.auditCancelled.emit(event)
            else:
                self.cancelled.emit(event)
        self.idle.emit()

    def _handle_start_failure(
        self,
        *,
        mode: ResearchDataTaskMode,
        message: str,
    ) -> None:
        if mode is ResearchDataTaskMode.FULL_HISTORY:
            outcome = "maintenance_failed"
            event: Any = FullHistoryBackfillFailure(
                revision=self._latest_revision,
                message=message,
                result=None,
            )
        else:
            outcome = "failed"
            event = ResearchBackfillFailure(
                revision=self._latest_revision,
                message=message,
                result=None,
            )
        thread = self._thread
        if thread is not None and getattr(thread, "isRunning", lambda: False)():
            self._begin_teardown(outcome, event)
            return
        worker = self._worker
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        self._pending_terminal = (outcome, event)
        self._on_thread_finished()

    def shutdown(self) -> bool:
        self._shutting_down = True
        self.cancel()
        return not self.is_running


__all__ = ["ResearchBackfillController"]
