from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from controllers.export_task_controller import ExportTaskController
from cancellation import CancellationToken
from services.export_service import ExportTaskRequest
from storage import StorageManager
from task_lifecycle import BackgroundTaskLifecycle, TaskState
from workers.export_worker import ExportWorker


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

    def __init__(self, db_path, session_id, target, language, selected_label) -> None:
        self.args = (db_path, session_id, target, language, selected_label)
        self.progress = _Signal()
        self.finished = _Signal()
        self.failed = _Signal()
        self.cancelled = _Signal()
        self.thread = None
        self.run_calls = 0
        self.cancel_calls = 0
        self.cancellation_token = CancellationToken()
        self.deleted = False
        _Worker.last_instance = self

    def moveToThread(self, thread) -> None:
        self.thread = thread

    def run(self) -> None:
        self.run_calls += 1

    def cancel(self) -> None:
        self.cancel_calls += 1

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

    def wait(self, _timeout) -> bool:
        self.wait_calls += 1
        return True

    def deleteLater(self) -> None:
        self.deleted = True


def _request() -> ExportTaskRequest:
    return ExportTaskRequest(
        target=Path("exports"),
        session_id="sess_1",
        language="zh_CN",
        selected_label="fwd_ret_10_side_adj",
    )


def test_export_task_controller_owns_worker_thread_and_rejects_duplicate_start():
    controller = ExportTaskController(worker_factory=_Worker, thread_factory=_Thread)

    assert controller.start("test.db", _request()) is True
    assert controller.is_running is True
    assert _Thread.last_instance.started_calls == 1
    assert _Worker.last_instance.run_calls == 1
    assert controller.start("test.db", _request()) is False


def test_export_task_controller_finishes_and_cleans_worker_thread():
    controller = ExportTaskController(worker_factory=_Worker, thread_factory=_Thread)
    results: list[tuple[str, list, float]] = []
    controller.finished.connect(lambda output, warnings, elapsed: results.append((output, warnings, elapsed)))
    controller.start("test.db", _request())
    worker = _Worker.last_instance
    thread = _Thread.last_instance

    worker.finished.emit("exports/session_1", ["warning"], 1.25)

    assert results == [("exports/session_1", ["warning"], 1.25)]
    assert controller.is_running is False
    assert thread.quit_calls == 1
    assert thread.wait_calls == 0
    assert worker.deleted is True
    assert thread.deleted is True


def test_export_task_controller_cancel_preserves_worker_cancel_contract_and_cleans_on_signal():
    lifecycle = BackgroundTaskLifecycle()
    controller = ExportTaskController(
        worker_factory=_Worker,
        thread_factory=_Thread,
        lifecycle=lifecycle,
    )
    cancelled: list[bool] = []
    finished: list[bool] = []
    controller.cancelled.connect(lambda: cancelled.append(True))
    controller.finished.connect(lambda *_args: finished.append(True))
    controller.start("test.db", _request())
    worker = _Worker.last_instance
    assert lifecycle.state("export") is TaskState.RUNNING

    controller.cancel()
    worker.cancelled.emit()

    assert worker.cancel_calls == 0
    assert worker.cancellation_token.is_requested() is True
    assert cancelled == [True]
    assert finished == []
    assert controller.is_running is False
    assert lifecycle.state("export") is TaskState.COMPLETED


def test_export_controller_captures_token_before_worker_moves_threads():
    class AffinityGuardedWorker(_Worker):
        @property
        def cancellation_token(self):
            if self.thread is not None:
                raise AssertionError(
                    "controller touched the export worker after moveToThread"
                )
            return self._plain_token

        @cancellation_token.setter
        def cancellation_token(self, token) -> None:
            self._plain_token = token

    controller = ExportTaskController(
        worker_factory=AffinityGuardedWorker,
        thread_factory=_Thread,
    )
    assert controller.start("test.db", _request()) is True
    worker = AffinityGuardedWorker.last_instance

    controller.cancel()

    assert worker._plain_token.is_requested() is True


def test_export_start_failure_retains_started_thread_until_finished_signal():
    class StartedThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.running = False

        def start(self) -> None:
            self.started_calls += 1
            self.running = True
            self.started.emit()

        def isRunning(self) -> bool:
            return self.running

        def quit(self) -> None:
            self.quit_calls += 1

    class FailingWorker(_Worker):
        def run(self) -> None:
            raise RuntimeError("worker startup failed after thread ownership was published")

    lifecycle = BackgroundTaskLifecycle()
    errors: list[tuple[str, float]] = []
    controller = ExportTaskController(
        worker_factory=FailingWorker,
        thread_factory=StartedThread,
        lifecycle=lifecycle,
    )
    controller.failed.connect(lambda error, elapsed: errors.append((error, elapsed)))

    assert controller.start("test.db", _request()) is False
    thread = StartedThread.last_instance
    assert controller.is_running is True
    assert lifecycle.state("export") is TaskState.RUNNING
    assert errors == []

    thread.finished.emit()

    assert controller.is_running is False
    assert lifecycle.state("export") is TaskState.FAILED
    assert errors and "worker startup failed" in errors[0][0]


def test_export_worker_emits_only_cancelled_when_real_chunked_csv_is_cancelled(tmp_path):
    db_path = tmp_path / "worker_cancel.db"
    storage = StorageManager(db_path)
    storage.upsert_session(
        {
            "session_id": "sess_worker_cancel",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
            "cursor_bar_index": 0,
            "follow_latest": 0,
            "speed": 1.0,
            "last_opened_at": "2026-01-01T00:00:00+08:00",
            "last_saved_at": "2026-01-01T00:00:00+08:00",
            "app_version": "test",
        }
    )
    with storage.connect() as connection:
        connection.executemany(
            """
            INSERT INTO trades (trade_id, session_id, side, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    f"trade_{index:05d}",
                    "sess_worker_cancel",
                    "LONG",
                    "OPEN",
                    "2026-01-01T00:00:00+08:00",
                )
                for index in range(10_001)
            ),
        )

    worker = ExportWorker(
        str(db_path),
        "sess_worker_cancel",
        tmp_path / "exports",
    )
    cancelled: list[bool] = []
    finished: list[bool] = []
    failed: list[str] = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.finished.connect(lambda *_args: finished.append(True))
    worker.failed.connect(lambda error, _elapsed: failed.append(error))
    worker.progress.connect(
        lambda message: worker.cancel()
        if message == "Writing export table: trades (chunk 1/2)"
        else None
    )

    worker.run()

    export_dir = tmp_path / "exports" / "session_sess_worker_cancel"
    assert cancelled == [True]
    assert finished == []
    assert failed == []
    assert not (export_dir / "trades.csv").exists()
    assert not list(export_dir.glob("*.partial"))
    assert not (export_dir / "export_manifest.json").exists()
    assert not list((tmp_path / "exports").glob(".session_sess_worker_cancel.staging-*"))
    assert not list((tmp_path / "exports").glob(".session_sess_worker_cancel.backup-*"))


def test_export_task_controller_reports_start_failure_without_staying_running():
    def broken_worker(*_args):
        raise RuntimeError("worker boom")

    controller = ExportTaskController(worker_factory=broken_worker, thread_factory=_Thread)
    errors: list[tuple[str, float]] = []
    controller.failed.connect(lambda error, elapsed: errors.append((error, elapsed)))

    assert controller.start("test.db", _request()) is False
    assert controller.is_running is False
    assert errors == [("RuntimeError: worker boom", 0.0)]


def test_export_task_controller_real_qthread_returns_completion_to_main_thread():
    probe = textwrap.dedent(
        """
        from pathlib import Path
        from PySide6 import QtCore, QtWidgets
        from quant_collector_app.controllers.export_task_controller import ExportTaskController
        from quant_collector_app.services.export_service import ExportTaskRequest

        class RealWorker(QtCore.QObject):
            progress = QtCore.Signal(str)
            finished = QtCore.Signal(str, object, float)
            failed = QtCore.Signal(str, float)
            cancelled = QtCore.Signal()

            @QtCore.Slot()
            def run(self):
                self.finished.emit("exports/session_1", [], 0.25)

            @QtCore.Slot()
            def cancel(self):
                pass

        app = QtWidgets.QApplication([])
        main_thread = QtCore.QThread.currentThread()
        loop = QtCore.QEventLoop()
        observed = []
        controller = ExportTaskController(worker_factory=lambda *_args: RealWorker())

        def receive(output_dir, _warnings, _elapsed):
            observed.append((output_dir, QtCore.QThread.currentThread() is main_thread))
            loop.quit()

        controller.finished.connect(receive)
        request = ExportTaskRequest(
            target=Path("exports"),
            session_id="sess_1",
            language="zh_CN",
            selected_label="fwd_ret_10_side_adj",
        )
        assert controller.start("test.db", request) is True
        QtCore.QTimer.singleShot(3000, loop.quit)
        loop.exec()
        app.processEvents()
        assert observed == [("exports/session_1", True)]
        assert controller.is_running is False
        controller.shutdown()
        """
    )
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr


def test_export_task_controller_defers_completion_until_thread_finished_without_waiting():
    class SlowStoppingThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.wait_timeouts: list[int | None] = []

        def wait(self, timeout=None) -> bool:
            self.wait_timeouts.append(timeout)
            raise AssertionError("the UI thread must not wait for export teardown")

        def quit(self) -> None:
            self.quit_calls += 1

    lifecycle = BackgroundTaskLifecycle()
    controller = ExportTaskController(
        worker_factory=_Worker,
        thread_factory=SlowStoppingThread,
        lifecycle=lifecycle,
    )
    results: list[str] = []
    controller.finished.connect(lambda output, *_args: results.append(output))
    controller.start("test.db", _request())
    worker = _Worker.last_instance
    thread = SlowStoppingThread.last_instance

    worker.finished.emit("exports/session_1", [], 0.25)

    assert thread.wait_timeouts == []
    assert controller.is_running is True
    assert lifecycle.state("export") is TaskState.RUNNING
    assert results == []
    assert thread.deleted is False
    heartbeats: list[bool] = []
    QtCore.QTimer.singleShot(0, lambda: heartbeats.append(True))
    QtWidgets.QApplication.instance().processEvents()
    assert heartbeats == [True]

    thread.finished.emit()

    assert controller.is_running is False
    assert lifecycle.state("export") is TaskState.COMPLETED
    assert results == ["exports/session_1"]
    assert thread.deleted is True


def test_export_controller_keeps_thread_wrapper_until_qobject_destroyed():
    class DestroyAwareThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.destroyed = _Signal()

    controller = ExportTaskController(
        worker_factory=_Worker,
        thread_factory=DestroyAwareThread,
    )
    assert controller.start("test.db", _request()) is True
    worker = _Worker.last_instance
    thread = DestroyAwareThread.last_instance

    worker.cancelled.emit()

    assert controller.shutdown() is False
    thread.destroyed.emit()
    assert controller.shutdown() is True


def test_export_task_controller_reports_shared_task_lifecycle() -> None:
    lifecycle = BackgroundTaskLifecycle()
    controller = ExportTaskController(
        worker_factory=_Worker,
        thread_factory=_Thread,
        lifecycle=lifecycle,
    )

    controller.start("test.db", _request())
    assert lifecycle.state("export") is TaskState.RUNNING

    _Worker.last_instance.finished.emit("exports/session_1", [], 0.25)
    assert lifecycle.state("export") is TaskState.COMPLETED
