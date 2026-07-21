from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6 import QtCore

try:
    from research.research_snapshot import ResearchSnapshotInput
    from workers.research_snapshot_worker import (
        ResearchSnapshotFailure,
        ResearchSnapshotWorker,
    )
except ImportError:  # pragma: no cover - package import path
    from ..research.research_snapshot import ResearchSnapshotInput
    from ..workers.research_snapshot_worker import (
        ResearchSnapshotFailure,
        ResearchSnapshotWorker,
    )


_TASK_NAME = "research_snapshot_publish"


@dataclass(frozen=True, slots=True)
class ResearchSnapshotPublishRequest:
    snapshot_input: ResearchSnapshotInput
    created_at: str


@dataclass(frozen=True, slots=True)
class ResearchSnapshotReadRequest:
    snapshot_id: str


class ResearchSnapshotController(QtCore.QObject):
    """Own snapshot publication and suppress stale worker events."""

    finished = QtCore.Signal(object)
    progress = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        service: Any,
        *,
        worker_factory: Callable[..., Any] = ResearchSnapshotWorker,
        thread_factory: Callable[[QtCore.QObject], Any] = QtCore.QThread,
        lifecycle: Any | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._lifecycle = lifecycle
        self._revision = 0
        self._thread = None
        self._worker = None
        self._token = None
        self._pending = None
        self._terminal = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(
        self,
        request: ResearchSnapshotPublishRequest | ResearchSnapshotReadRequest,
    ) -> int:
        self._revision += 1
        revision = self._revision
        if self.is_running:
            self._pending = (revision, request)
            self.cancel()
        else:
            self._start(revision, request)
        return revision

    def load(self, snapshot_id: str) -> int:
        return self.start(ResearchSnapshotReadRequest(str(snapshot_id)))

    def _start(
        self,
        revision: int,
        request: ResearchSnapshotPublishRequest | ResearchSnapshotReadRequest,
    ) -> None:
        if self._lifecycle is not None and not self._lifecycle.start(
            _TASK_NAME,
            request_stop=self.cancel,
        ):
            self.failed.emit("研究快照发布任务当前无法启动。")
            return
        try:
            self._thread = self._thread_factory(self)
            self._worker = self._worker_factory(
                self._service,
                request,
                revision,
            )
            self._token = self._worker.cancellation_token
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.progress.connect(
                self._on_progress,
                QtCore.Qt.QueuedConnection,
            )
            self._worker.finished.connect(
                self._on_finished,
                QtCore.Qt.QueuedConnection,
            )
            self._worker.failed.connect(
                self._on_failed,
                QtCore.Qt.QueuedConnection,
            )
            self._worker.cancelled.connect(
                self._on_cancelled,
                QtCore.Qt.QueuedConnection,
            )
            self._thread.finished.connect(self._worker.deleteLater)
            self._thread.finished.connect(self._finish_thread)
            self._thread.finished.connect(self._thread.deleteLater)
            self._thread.start()
        except Exception as exc:
            self._handle_start_failure(
                ResearchSnapshotFailure(
                    revision,
                    f"{type(exc).__name__}: {exc}",
                )
            )

    def cancel(self) -> None:
        request = getattr(self._token, "request", None)
        if callable(request):
            request()

    def invalidate(self) -> None:
        self._revision += 1
        self._pending = None
        self.cancel()

    def shutdown(self) -> bool:
        self._pending = None
        self.cancel()
        return not self.is_running

    def _on_progress(self, event: Any) -> None:
        if event.revision == self._revision:
            self.progress.emit(event.message)

    @QtCore.Slot(object)
    def _on_finished(self, event: Any) -> None:
        self._begin_teardown("finished", event)

    @QtCore.Slot(object)
    def _on_failed(self, event: Any) -> None:
        self._begin_teardown("failed", event)

    @QtCore.Slot(int)
    def _on_cancelled(self, revision: int) -> None:
        self._begin_teardown("cancelled", int(revision))

    def _begin_teardown(self, kind: str, event: Any) -> None:
        if self._terminal is not None:
            return
        self._terminal = (kind, event)
        if self._thread is None:
            self._finish_thread()
        else:
            self._thread.quit()

    def _handle_start_failure(self, event: ResearchSnapshotFailure) -> None:
        self._terminal = ("failed", event)
        self.cancel()
        thread = self._thread
        if thread is not None and getattr(
            thread,
            "isRunning",
            lambda: False,
        )():
            thread.quit()
            return
        if self._worker is not None:
            self._worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        self._finish_thread()

    def _finish_thread(self) -> None:
        terminal = self._terminal
        self._thread = None
        self._worker = None
        self._token = None
        self._terminal = None
        if terminal is not None:
            kind, event = terminal
            revision = (
                event.revision if hasattr(event, "revision") else int(event)
            )
            if self._lifecycle is not None:
                if kind == "failed" and revision == self._revision:
                    self._lifecycle.fail(_TASK_NAME, str(event.message))
                else:
                    self._lifecycle.complete(_TASK_NAME)
            if revision == self._revision:
                if kind == "finished":
                    self.finished.emit(event)
                elif kind == "failed":
                    self.failed.emit(event.message)
                else:
                    self.cancelled.emit()
        elif self._lifecycle is not None:
            self._lifecycle.complete(_TASK_NAME)
        pending = self._pending
        self._pending = None
        if pending is not None:
            self._start(*pending)


__all__ = [
    "ResearchSnapshotController",
    "ResearchSnapshotPublishRequest",
    "ResearchSnapshotReadRequest",
]
