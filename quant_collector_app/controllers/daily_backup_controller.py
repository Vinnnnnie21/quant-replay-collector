from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6 import QtCore

try:
    from workers.database_backup_worker import DatabaseBackupWorker
except ImportError:  # pragma: no cover - package import path
    from ..workers.database_backup_worker import DatabaseBackupWorker


class DailyBackupController(QtCore.QObject):
    progress = QtCore.Signal(str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        *,
        db_path: str | Path,
        backup_dir: str | Path,
        lifecycle: Any | None = None,
        worker_factory: Callable[[str | Path, str | Path], Any] = DatabaseBackupWorker,
        thread_factory: Callable[[QtCore.QObject], Any] = QtCore.QThread,
        single_shot: Callable[[int, Callable[[], None]], None] = QtCore.QTimer.singleShot,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db_path = Path(db_path)
        self._backup_dir = Path(backup_dir)
        self._lifecycle = lifecycle
        self._worker_factory = worker_factory
        self._thread_factory = thread_factory
        self._single_shot = single_shot
        self._scheduled = False
        self._thread = None
        self._worker = None
        self._cancellation_token = None
        self._worker_deletes_on_thread_finish = False
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False
        self._shutting_down = False
        self._pending_terminal: tuple[str, tuple[Any, ...]] | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def _shutdown_in_progress(self) -> bool:
        return bool(
            self._shutting_down
            or (self._lifecycle is not None and self._lifecycle.shutdown_in_progress)
        )

    def schedule(self) -> bool:
        if self._scheduled or self.is_running or self._shutdown_in_progress():
            return False
        self._scheduled = True
        self._single_shot(0, self.start)
        return True

    @QtCore.Slot()
    def start(self) -> bool:
        self._scheduled = False
        if self.is_running or self._shutdown_in_progress():
            return False
        if self._lifecycle is not None and not self._lifecycle.start(
            "daily_backup",
            request_stop=self.request_stop,
        ):
            return False
        try:
            self._thread = self._thread_factory(self)
            self._worker = self._worker_factory(self._db_path, self._backup_dir)
            self._cancellation_token = getattr(
                self._worker, "cancellation_token", None
            )
            self._worker.moveToThread(self._thread)
            worker_destroyed = getattr(self._worker, "destroyed", None)
            if worker_destroyed is not None and hasattr(worker_destroyed, "connect"):
                worker_destroyed.connect(self._on_worker_destroyed)
                self._worker_destroyed_signal_connected = True
            self._thread.started.connect(self._worker.run)
            self._worker.progress.connect(self.progress.emit, QtCore.Qt.QueuedConnection)
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
            message = f"{type(exc).__name__}: {exc}"
            thread = self._thread
            is_running = getattr(thread, "isRunning", lambda: False)
            if thread is not None and bool(is_running()):
                self._pending_terminal = ("failed", (message,))
                self.request_stop()
                thread.quit()
                return False
            if self._lifecycle is not None:
                self._lifecycle.fail("daily_backup", message)
            self.failed.emit(message)
            self._cleanup()
            return False

    @QtCore.Slot(object)
    def _on_finished(self, result: dict[str, Any]) -> None:
        self._begin_thread_teardown("finished", result)

    @QtCore.Slot(str)
    def _on_failed(self, error: str) -> None:
        self._begin_thread_teardown("failed", error)

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
                self._lifecycle.complete("daily_backup")
            self.finished.emit(args[0])
        elif outcome == "failed":
            error = str(args[0])
            if self._lifecycle is not None:
                self._lifecycle.fail("daily_backup", error)
            self.failed.emit(error)
        else:
            if self._lifecycle is not None:
                self._lifecycle.complete("daily_backup")
            self.cancelled.emit()

    def request_stop(self) -> None:
        self._shutting_down = True
        self._scheduled = False
        request = getattr(self._cancellation_token, "request", None)
        if callable(request):
            request()

    def _cleanup(self) -> None:
        thread = self._thread
        worker = self._worker
        if thread is not None:
            thread.quit()
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        self._thread = None
        self._worker = None
        self._cancellation_token = None
        self._worker_deletes_on_thread_finish = False
        self._worker_destroyed_signal_connected = False
        self._thread_destroyed_signal_connected = False

    def _cleanup_finished_thread(self) -> None:
        thread = self._thread
        worker = self._worker
        if worker is not None and not self._worker_deletes_on_thread_finish:
            worker.deleteLater()
        self._thread = None
        self._worker = None
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

    def shutdown(self) -> bool:
        self.request_stop()
        return not self.is_running


__all__ = ["DailyBackupController"]
