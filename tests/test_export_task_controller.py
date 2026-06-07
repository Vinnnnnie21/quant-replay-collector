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
from services.export_service import ExportTaskRequest


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
    assert thread.wait_calls == 1
    assert worker.deleted is True
    assert thread.deleted is True


def test_export_task_controller_cancel_preserves_worker_cancel_contract_and_cleans_on_signal():
    controller = ExportTaskController(worker_factory=_Worker, thread_factory=_Thread)
    cancelled: list[bool] = []
    controller.cancelled.connect(lambda: cancelled.append(True))
    controller.start("test.db", _request())
    worker = _Worker.last_instance

    controller.cancel()
    worker.cancelled.emit()

    assert worker.cancel_calls == 1
    assert cancelled == [True]
    assert controller.is_running is False


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


def test_export_task_controller_waits_until_thread_stops_before_deleting_it():
    class SlowStoppingThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.wait_timeouts: list[int | None] = []

        def wait(self, timeout=None) -> bool:
            self.wait_timeouts.append(timeout)
            return len(self.wait_timeouts) > 1

    controller = ExportTaskController(worker_factory=_Worker, thread_factory=SlowStoppingThread)
    controller.start("test.db", _request())
    worker = _Worker.last_instance
    thread = SlowStoppingThread.last_instance

    worker.finished.emit("exports/session_1", [], 0.25)

    assert thread.wait_timeouts == [1000, None]
    assert thread.deleted is True
