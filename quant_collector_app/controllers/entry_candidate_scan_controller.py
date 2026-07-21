from __future__ import annotations

from typing import Any, Callable

from PySide6 import QtCore

try:
    from research.entry_candidate_generation import candidate_scan_overview
    from workers.entry_candidate_scan_worker import (
        CandidateScanFailure,
        EntryCandidateScanWorker,
    )
except ImportError:  # pragma: no cover - package import path
    from ..research.entry_candidate_generation import candidate_scan_overview
    from ..workers.entry_candidate_scan_worker import (
        CandidateScanFailure,
        EntryCandidateScanWorker,
    )


class EntryCandidateScanController(QtCore.QObject):
    resultReady = QtCore.Signal(object)
    progress = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        service: Any,
        *,
        worker_factory: Callable[..., Any] = EntryCandidateScanWorker,
        thread_factory: Callable[[QtCore.QObject], Any] = QtCore.QThread,
        lifecycle: Any | None = None,
        overview_factory: Callable[[Any], Any] = candidate_scan_overview,
        task_key: str = "entry_candidate_scan",
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._lifecycle = lifecycle
        self._overview_factory = overview_factory
        self._task_key = str(task_key)
        self._revision = 0
        self._thread = None
        self._worker = None
        self._token = None
        self._pending = None
        self._terminal = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(self, request: Any) -> int:
        self._revision += 1
        revision = self._revision
        if self.is_running:
            self._pending = (revision, request)
            self.cancel()
            return revision
        self._start(revision, request)
        return revision

    def _start(self, revision: int, request: Any) -> None:
        if self._lifecycle is not None and not self._lifecycle.start(
            self._task_key, request_stop=self.cancel
        ):
            self.failed.emit(
                "candidate scan cannot start while another task is active"
            )
            return
        try:
            self._thread = self._thread_factory(self)
            self._worker = self._worker_factory(self._service, request, revision)
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
                CandidateScanFailure(
                    revision,
                    f"{type(exc).__name__}: {exc}",
                )
            )

    def cancel(self) -> None:
        request = getattr(self._token, "request", None)
        if callable(request):
            request()

    def invalidate(self) -> None:
        """Discard any result tied to a research context that is no longer active."""

        self._revision += 1
        self._pending = None
        self.cancel()

    def _on_progress(self, event: Any) -> None:
        if event.revision == self._revision:
            self.progress.emit(event)

    def _on_finished(self, event: Any) -> None:
        self._begin_teardown("finished", event)

    def _on_failed(self, event: Any) -> None:
        self._begin_teardown("failed", event)

    def _on_cancelled(self, revision: int) -> None:
        self._begin_teardown("cancelled", int(revision))

    def _begin_teardown(self, kind: str, event: Any) -> None:
        if self._terminal is not None:
            return
        self._terminal = (kind, event)
        thread = self._thread
        if thread is None:
            self._finish_thread()
            return
        thread.quit()

    def _handle_start_failure(self, event: CandidateScanFailure) -> None:
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
        worker = self._worker
        if worker is not None:
            worker.deleteLater()
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
            revision = event.revision if hasattr(event, "revision") else int(event)
            if self._lifecycle is not None:
                if kind == "failed" and revision == self._revision:
                    self._lifecycle.fail(
                        self._task_key,
                        str(event.message),
                    )
                else:
                    self._lifecycle.complete(self._task_key)
            if revision == self._revision:
                if kind == "finished":
                    self.resultReady.emit(self._overview_factory(event.result))
                elif kind == "failed":
                    self.failed.emit(event.message)
                else:
                    self.cancelled.emit()
        elif self._lifecycle is not None:
            self._lifecycle.complete(self._task_key)
        pending = self._pending
        self._pending = None
        if pending is not None:
            self._start(*pending)

    def shutdown(self) -> bool:
        self._pending = None
        self.cancel()
        return not self.is_running


__all__ = ["EntryCandidateScanController"]
