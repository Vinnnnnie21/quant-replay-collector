from __future__ import annotations

from pathlib import Path
import threading

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from controllers.daily_backup_controller import DailyBackupController
from cancellation import CancellationToken
from task_lifecycle import BackgroundTaskLifecycle, TaskState
from workers.database_backup_worker import DatabaseBackupWorker


class _Signal:
    def __init__(self) -> None:
        self.connections: list[tuple[object, object | None]] = []

    def connect(self, callback, connection_type=None) -> None:
        self.connections.append((callback, connection_type))

    def emit(self, *args) -> None:
        for callback, _connection_type in list(self.connections):
            callback(*args)


class _Worker:
    last_instance = None

    def __init__(self, db_path, backup_dir) -> None:
        self.args = (Path(db_path), Path(backup_dir))
        self.progress = _Signal()
        self.finished = _Signal()
        self.failed = _Signal()
        self.cancelled = _Signal()
        self.run_calls = 0
        self.stop_calls = 0
        self.cancellation_token = CancellationToken()
        self.deleted = False
        _Worker.last_instance = self

    def moveToThread(self, _thread) -> None:
        pass

    def run(self) -> None:
        self.run_calls += 1

    def request_stop(self) -> None:
        self.stop_calls += 1

    def deleteLater(self) -> None:
        self.deleted = True


class _Thread:
    last_instance = None

    def __init__(self, _parent=None) -> None:
        self.started = _Signal()
        self.finished = _Signal()
        self.started_calls = 0
        self.quit_calls = 0
        self.wait_calls = 0
        self.deleted = False
        _Thread.last_instance = self

    def start(self) -> None:
        self.started_calls += 1
        self.started.emit()

    def quit(self) -> None:
        self.quit_calls += 1
        self.finished.emit()

    def wait(self, _timeout=None) -> bool:
        self.wait_calls += 1
        return True

    def deleteLater(self) -> None:
        self.deleted = True


def test_daily_backup_is_deferred_until_the_qt_event_loop_and_runs_in_lifecycle(tmp_path):
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    controller = DailyBackupController(
        db_path=tmp_path / "source.db",
        backup_dir=tmp_path / "backups",
        lifecycle=lifecycle,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )

    assert controller.schedule() is True
    assert _Worker.last_instance is None
    assert lifecycle.state("daily_backup") is None
    assert scheduled[0][0] == 0

    scheduled.pop(0)[1]()

    assert _Thread.last_instance.started_calls == 1
    assert _Worker.last_instance.run_calls == 1
    assert lifecycle.state("daily_backup") is TaskState.RUNNING


def test_daily_backup_safe_shutdown_requests_cooperative_cancel_and_waits_for_signal(tmp_path):
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    controller = DailyBackupController(
        db_path=tmp_path / "source.db",
        backup_dir=tmp_path / "backups",
        lifecycle=lifecycle,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )
    controller.schedule()
    scheduled.pop(0)[1]()
    worker = _Worker.last_instance

    lifecycle.request_stop_all()

    assert worker.stop_calls == 0
    assert worker.cancellation_token.is_requested() is True
    assert lifecycle.state("daily_backup") is TaskState.STOP_REQUESTED
    worker.cancelled.emit()
    assert lifecycle.state("daily_backup") is TaskState.COMPLETED
    assert controller.is_running is False


def test_daily_backup_captures_token_before_worker_moves_threads(tmp_path):
    class AffinityGuardedWorker(_Worker):
        def __init__(self, db_path, backup_dir) -> None:
            self.moved = False
            super().__init__(db_path, backup_dir)

        @property
        def cancellation_token(self):
            if self.moved:
                raise AssertionError(
                    "controller touched the backup worker after moveToThread"
                )
            return self._plain_token

        @cancellation_token.setter
        def cancellation_token(self, token) -> None:
            self._plain_token = token

        def moveToThread(self, _thread) -> None:
            self.moved = True

    controller = DailyBackupController(
        db_path=tmp_path / "source.db",
        backup_dir=tmp_path / "backups",
        worker_factory=AffinityGuardedWorker,
        thread_factory=_Thread,
    )
    assert controller.start() is True
    worker = AffinityGuardedWorker.last_instance

    controller.request_stop()

    assert worker._plain_token.is_requested() is True


def test_daily_backup_defers_completion_until_thread_finished_without_waiting(tmp_path):
    class SlowStoppingThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.wait_timeouts: list[int | None] = []

        def wait(self, timeout=None) -> bool:
            self.wait_timeouts.append(timeout)
            raise AssertionError("the UI thread must not wait for backup teardown")

        def quit(self) -> None:
            self.quit_calls += 1

    lifecycle = BackgroundTaskLifecycle()
    controller = DailyBackupController(
        db_path=tmp_path / "source.db",
        backup_dir=tmp_path / "backups",
        lifecycle=lifecycle,
        worker_factory=_Worker,
        thread_factory=SlowStoppingThread,
    )
    completed: list[object] = []
    controller.finished.connect(completed.append)
    assert controller.start() is True
    worker = _Worker.last_instance
    thread = SlowStoppingThread.last_instance

    worker.finished.emit({"status": "success"})

    assert thread.wait_timeouts == []
    assert controller.is_running is True
    assert lifecycle.state("daily_backup") is TaskState.RUNNING
    assert completed == []
    heartbeats: list[bool] = []
    QtCore.QTimer.singleShot(0, lambda: heartbeats.append(True))
    QtWidgets.QApplication.instance().processEvents()
    assert heartbeats == [True]

    thread.finished.emit()

    assert controller.is_running is False
    assert lifecycle.state("daily_backup") is TaskState.COMPLETED
    assert completed == [{"status": "success"}]


def test_daily_backup_keeps_thread_wrapper_until_qobject_destroyed(tmp_path):
    class DestroyAwareThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.destroyed = _Signal()

    controller = DailyBackupController(
        db_path=tmp_path / "source.db",
        backup_dir=tmp_path / "backups",
        worker_factory=_Worker,
        thread_factory=DestroyAwareThread,
    )
    assert controller.start() is True
    worker = _Worker.last_instance
    thread = DestroyAwareThread.last_instance

    worker.cancelled.emit()

    assert controller.shutdown() is False
    thread.destroyed.emit()
    assert controller.shutdown() is True


def test_daily_backup_start_failure_retains_running_thread_until_finished(tmp_path):
    class StartedThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.running = False

        def start(self) -> None:
            self.started_calls += 1
            self.running = True
            raise RuntimeError("backup start failed after ownership was published")

        def isRunning(self) -> bool:
            return self.running

        def quit(self) -> None:
            self.quit_calls += 1

    lifecycle = BackgroundTaskLifecycle()
    errors: list[str] = []
    controller = DailyBackupController(
        db_path=tmp_path / "source.db",
        backup_dir=tmp_path / "backups",
        lifecycle=lifecycle,
        worker_factory=_Worker,
        thread_factory=StartedThread,
    )
    controller.failed.connect(errors.append)

    assert controller.start() is False
    thread = StartedThread.last_instance
    assert controller.is_running is True
    assert lifecycle.state("daily_backup") is TaskState.RUNNING
    assert errors == []

    thread.finished.emit()

    assert controller.is_running is False
    assert lifecycle.state("daily_backup") is TaskState.FAILED
    assert errors and "backup start failed" in errors[0]


def test_daily_backup_worker_does_not_block_main_thread_heartbeat(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main_thread = QtCore.QThread.currentThread()
    release = threading.Event()
    loop = QtCore.QEventLoop()
    order: list[str] = []
    worker_threads: list[object] = []

    def controlled_backup(_db_path, _backup_dir, **_kwargs):
        worker_threads.append(QtCore.QThread.currentThread())
        if not release.wait(2.0):
            raise RuntimeError("main-thread heartbeat did not run")
        return {"status": "skipped", "reason": "controlled test"}

    controller = DailyBackupController(
        db_path=tmp_path / "source.db",
        backup_dir=tmp_path / "backups",
        worker_factory=lambda db_path, backup_dir: DatabaseBackupWorker(
            db_path,
            backup_dir,
            backup_fn=controlled_backup,
        ),
    )

    def heartbeat() -> None:
        order.append("heartbeat")
        release.set()

    def finished(_result) -> None:
        order.append("finished")
        loop.quit()

    controller.finished.connect(finished)
    assert controller.start() is True
    QtCore.QTimer.singleShot(0, heartbeat)
    QtCore.QTimer.singleShot(3000, loop.quit)
    loop.exec()
    app.processEvents()

    assert order == ["heartbeat", "finished"]
    assert len(worker_threads) == 1
    assert worker_threads[0] is not main_thread
    controller.shutdown()
