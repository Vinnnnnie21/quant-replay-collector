from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from controllers.analysis_controller import AnalysisRefreshController
from cancellation import CancellationToken
from main_app import MainWindow
from services.analysis_refresh import AnalysisRefreshResult, AnalysisRefreshSnapshot
from task_lifecycle import BackgroundTaskLifecycle, TaskState
from workers.analysis_refresh_worker import AnalysisRefreshWorker


_ACTIVE_FAKE_CONTROLLERS: list[AnalysisRefreshController] = []


@pytest.fixture(autouse=True)
def _drain_controller_qt_events():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield
    for controller in _ACTIVE_FAKE_CONTROLLERS:
        controller.shutdown()
    app.processEvents()
    _ACTIVE_FAKE_CONTROLLERS.clear()


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

    def __init__(self) -> None:
        self.progress = _Signal()
        self.finished = _Signal()
        self.failed = _Signal()
        self.cancelled = _Signal()
        self.thread = None
        self.deleted = False
        self.runs: list[object] = []
        self.stop_calls = 0
        self.cancellation_token = CancellationToken()
        _Worker.last_instance = self

    def moveToThread(self, thread) -> None:
        self.thread = thread

    def run(self, snapshot) -> None:
        self.runs.append(snapshot)

    def request_stop(self) -> None:
        self.stop_calls += 1

    def deleteLater(self) -> None:
        self.deleted = True


class _Thread:
    last_instance = None

    def __init__(self, _parent=None) -> None:
        self.finished = _Signal()
        self.started = False
        self.quit_called = False
        self.waited = False
        self.deleted = False
        _Thread.last_instance = self

    def start(self) -> None:
        self.started = True

    def quit(self) -> None:
        self.quit_called = True
        self.finished.emit()

    def wait(self, _timeout) -> None:
        self.waited = True

    def deleteLater(self) -> None:
        self.deleted = True


def _controller(*, playing: SimpleNamespace, scheduled: list[tuple[int, object]], snapshot_factory=None):
    controller = AnalysisRefreshController(
        snapshot_factory=snapshot_factory or (lambda: {"snapshot": 1}),
        is_playing=lambda: bool(playing.value),
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    return controller


def test_controller_defers_pending_refresh_while_playing_then_starts_when_idle():
    playing = SimpleNamespace(value=True)
    scheduled: list[tuple[int, object]] = []
    controller = _controller(playing=playing, scheduled=scheduled)

    assert controller.schedule() is True
    scheduled.pop(0)[1]()

    assert controller.pending is True
    assert controller.is_running is False
    assert scheduled == []

    playing.value = False
    assert controller.resume_if_idle() is True
    assert scheduled and scheduled[0][0] == 0
    scheduled.pop(0)[1]()

    assert controller.is_running is True
    assert _Thread.last_instance.started is True


def test_controller_uses_queued_connections_for_worker_result_handlers():
    playing = SimpleNamespace(value=False)
    scheduled: list[tuple[int, object]] = []
    controller = _controller(playing=playing, scheduled=scheduled)

    controller.schedule()
    scheduled.pop(0)[1]()

    worker = _Worker.last_instance
    assert worker.finished.connections == [
        (controller._on_worker_finished, QtCore.Qt.QueuedConnection)
    ]
    assert worker.failed.connections == [
        (controller._on_worker_failed, QtCore.Qt.QueuedConnection)
    ]


def test_controller_coalesces_requests_arriving_while_worker_runs():
    playing = SimpleNamespace(value=False)
    scheduled: list[tuple[int, object]] = []
    controller = _controller(playing=playing, scheduled=scheduled)

    controller.schedule()
    scheduled.pop(0)[1]()
    worker = _Worker.last_instance

    assert controller.schedule() is False
    assert controller.schedule() is False
    worker.finished.emit({"result": 1})

    assert controller.is_running is False
    assert controller.pending is True
    assert len(scheduled) == 1
    assert scheduled[0][0] == 300


def test_controller_discards_result_older_than_latest_requested_revision():
    playing = SimpleNamespace(value=False)
    scheduled: list[tuple[int, object]] = []
    input_state = {"trade_id": "trade_a"}
    controller = _controller(
        playing=playing,
        scheduled=scheduled,
        snapshot_factory=lambda: AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=[{"trade_id": input_state["trade_id"]}],
            equity_rows=[],
            initial_equity=10_000.0,
        ),
    )
    visible: list[AnalysisRefreshResult] = []
    controller.resultReady.connect(visible.append)

    controller.schedule()
    scheduled.pop(0)[1]()
    QtWidgets.QApplication.instance().processEvents()
    worker_a = _Worker.last_instance
    snapshot_a = worker_a.runs[0]

    input_state["trade_id"] = "trade_b"
    assert controller.schedule() is False
    worker_a.finished.emit(
        AnalysisRefreshResult(
            event_study=pd.DataFrame(),
            dataset_text="A",
            performance_text="A",
            revision=snapshot_a.revision,
        )
    )

    assert visible == []
    assert controller.pending is True
    assert len(scheduled) == 1


def test_controller_runs_coalesced_latest_revision_once_after_discarding_old_result():
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    input_state = {"trade_id": "trade_a"}
    snapshots: list[AnalysisRefreshSnapshot] = []

    def snapshot_factory() -> AnalysisRefreshSnapshot:
        snapshot = AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=[{"trade_id": input_state["trade_id"]}],
            equity_rows=[],
            initial_equity=10_000.0,
        )
        snapshots.append(snapshot)
        return snapshot

    controller = AnalysisRefreshController(
        snapshot_factory=snapshot_factory,
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    visible: list[str] = []
    controller.resultReady.connect(lambda result: visible.append(result.performance_text))

    controller.schedule()
    scheduled.pop(0)[1]()
    QtWidgets.QApplication.instance().processEvents()
    worker_a = _Worker.last_instance
    snapshot_a = worker_a.runs[0]

    input_state["trade_id"] = "trade_b"
    assert controller.schedule() is False
    worker_a.finished.emit(
        AnalysisRefreshResult(
            event_study=pd.DataFrame(),
            dataset_text="A",
            performance_text="A",
            revision=snapshot_a.revision,
        )
    )

    scheduled.pop(0)[1]()
    QtWidgets.QApplication.instance().processEvents()
    worker_b = _Worker.last_instance
    snapshot_b = worker_b.runs[0]
    worker_b.finished.emit(
        AnalysisRefreshResult(
            event_study=pd.DataFrame(),
            dataset_text="B",
            performance_text="B",
            revision=snapshot_b.revision,
        )
    )

    assert [snapshot.trades[0]["trade_id"] for snapshot in snapshots] == [
        "trade_a",
        "trade_b",
    ]
    assert (snapshot_a.revision, snapshot_b.revision) == (1, 2)
    assert visible == ["B"]
    assert controller.pending is False
    assert controller.is_running is False
    assert lifecycle.state("analysis_refresh") is TaskState.COMPLETED


def test_stale_worker_failure_does_not_fail_or_finish_latest_revision():
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: AnalysisRefreshSnapshot(
            events=[], features=[], trades=[], equity_rows=[], initial_equity=10_000.0
        ),
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    errors: list[object] = []
    visible: list[str] = []
    controller.failed.connect(errors.append)
    controller.resultReady.connect(lambda result: visible.append(result.performance_text))

    controller.schedule()
    scheduled.pop(0)[1]()
    QtWidgets.QApplication.instance().processEvents()
    worker_a = _Worker.last_instance
    snapshot_a = worker_a.runs[0]
    assert controller.schedule() is False

    worker_a.failed.emit(
        SimpleNamespace(revision=snapshot_a.revision, message="A failed")
    )

    assert errors == []
    assert lifecycle.state("analysis_refresh") is TaskState.RUNNING
    assert len(scheduled) == 1

    scheduled.pop(0)[1]()
    QtWidgets.QApplication.instance().processEvents()
    worker_b = _Worker.last_instance
    snapshot_b = worker_b.runs[0]
    worker_b.finished.emit(
        AnalysisRefreshResult(
            event_study=pd.DataFrame(),
            dataset_text="B",
            performance_text="B",
            revision=snapshot_b.revision,
        )
    )

    assert errors == []
    assert visible == ["B"]
    assert lifecycle.state("analysis_refresh") is TaskState.COMPLETED


def test_stale_worker_cancellation_keeps_latest_revision_pending():
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: AnalysisRefreshSnapshot(
            events=[], features=[], trades=[], equity_rows=[], initial_equity=10_000.0
        ),
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)

    controller.schedule()
    scheduled.pop(0)[1]()
    QtWidgets.QApplication.instance().processEvents()
    worker_a = _Worker.last_instance
    snapshot_a = worker_a.runs[0]
    assert controller.schedule() is False

    worker_a.cancelled.emit(SimpleNamespace(revision=snapshot_a.revision))

    assert lifecycle.state("analysis_refresh") is TaskState.RUNNING
    assert controller.pending is True
    assert len(scheduled) == 1

    scheduled.pop(0)[1]()
    QtWidgets.QApplication.instance().processEvents()
    worker_b = _Worker.last_instance
    snapshot_b = worker_b.runs[0]
    worker_b.finished.emit(
        AnalysisRefreshResult(
            event_study=pd.DataFrame(),
            dataset_text="B",
            performance_text="B",
            revision=snapshot_b.revision,
        )
    )

    assert lifecycle.state("analysis_refresh") is TaskState.COMPLETED
    assert controller.pending is False


def test_stale_worker_progress_does_not_update_current_status():
    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: AnalysisRefreshSnapshot(
            events=[], features=[], trades=[], equity_rows=[], initial_equity=10_000.0
        ),
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    visible_progress: list[str] = []
    controller.progress.connect(visible_progress.append)

    controller.schedule()
    scheduled.pop(0)[1]()
    QtWidgets.QApplication.instance().processEvents()
    worker_a = _Worker.last_instance
    snapshot_a = worker_a.runs[0]
    assert controller.schedule() is False

    worker_a.progress.emit(
        SimpleNamespace(revision=snapshot_a.revision, message="stale progress")
    )

    assert visible_progress == []


def test_controller_snapshot_failure_emits_error_and_clears_pending():
    playing = SimpleNamespace(value=False)
    scheduled: list[tuple[int, object]] = []
    controller = _controller(
        playing=playing,
        scheduled=scheduled,
        snapshot_factory=lambda: (_ for _ in ()).throw(RuntimeError("snapshot boom")),
    )
    errors: list[str] = []
    controller.failed.connect(errors.append)

    controller.schedule()
    scheduled.pop(0)[1]()

    assert errors == ["RuntimeError: snapshot boom"]


def test_analysis_startup_failure_retains_running_thread_until_finished():
    class StartedThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.running = False

        def start(self) -> None:
            self.started = True
            self.running = True
            raise RuntimeError("analysis start failed after thread ownership was published")

        def isRunning(self) -> bool:
            return self.running

        def quit(self) -> None:
            self.quit_called = True

    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    errors: list[str] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: AnalysisRefreshSnapshot([], [], [], [], 10_000.0),
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=StartedThread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    controller.failed.connect(errors.append)
    controller.schedule()

    scheduled.pop(0)[1]()

    thread = StartedThread.last_instance
    assert controller.is_running is True
    assert thread.quit_called is True
    assert lifecycle.state("analysis_refresh") is TaskState.RUNNING
    assert errors == []

    thread.finished.emit()

    assert controller.is_running is False
    assert lifecycle.state("analysis_refresh") is TaskState.FAILED
    assert errors and "analysis start failed" in errors[0]
    assert controller.pending is False
    assert controller.is_running is False


def test_controller_shutdown_requests_stop_and_returns_until_thread_finishes():
    playing = SimpleNamespace(value=False)
    scheduled: list[tuple[int, object]] = []
    controller = _controller(playing=playing, scheduled=scheduled)

    controller.schedule()
    scheduled.pop(0)[1]()
    thread = _Thread.last_instance

    worker = _Worker.last_instance
    assert controller.shutdown() is False

    assert controller.pending is False
    assert controller.is_running is True
    assert worker.stop_calls == 0
    assert worker.cancellation_token.is_requested() is True
    assert thread.quit_called is False
    assert thread.waited is False

    worker.cancelled.emit()

    assert controller.is_running is False
    assert thread.quit_called is True


def test_controller_real_qthread_returns_result_to_main_thread():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main_thread = QtCore.QThread.currentThread()
    loop = QtCore.QEventLoop()
    observed: list[tuple[object, bool]] = []
    errors: list[str] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: AnalysisRefreshSnapshot(
            events=[{"event_id": "evt_1"}],
            features=[{"event_id": "evt_1", "pre_ret_20": 0.1}],
            trades=[{"trade_id": "trd_1"}],
            equity_rows=[{"sequence_no": 1}],
            initial_equity=10000.0,
        ),
        is_playing=lambda: False,
        delay_ms=0,
        worker_factory=lambda: AnalysisRefreshWorker(
            build_event_study_fn=lambda events, features: pd.DataFrame(
                [{"event_count": len(events), "feature_count": len(features)}]
            ),
            build_ml_datasets_fn=lambda features: {
                "ml_features": features[["event_id", "pre_ret_20"]],
                "ml_labels": pd.DataFrame({"event_id": features["event_id"]}),
                "sample_index": pd.DataFrame({"event_id": features["event_id"]}),
            },
            build_performance_summary_fn=lambda trades, equity, _initial: {
                "total_trades": len(trades),
                "equity_rows": len(equity),
            },
            format_performance_report_fn=lambda summary: f"trades={summary['total_trades']}",
        ),
    )

    def receive_result(result) -> None:
        observed.append((result, QtCore.QThread.currentThread() is main_thread))
        loop.quit()

    controller.resultReady.connect(receive_result)
    controller.failed.connect(errors.append)
    controller.schedule()
    QtCore.QTimer.singleShot(3000, loop.quit)
    loop.exec()
    app.processEvents()

    assert errors == []
    assert len(observed) == 1
    assert observed[0][1] is True
    assert observed[0][0].performance_text == "trades=1"
    assert controller.is_running is False
    controller.shutdown()


def test_controller_defers_completion_until_thread_finished_without_waiting():
    class SlowStoppingThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.wait_timeouts: list[int | None] = []

        def wait(self, timeout=None) -> bool:
            self.wait_timeouts.append(timeout)
            raise AssertionError("the UI thread must not wait for worker teardown")

        def quit(self) -> None:
            self.quit_called = True

    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=SlowStoppingThread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    controller.schedule()
    scheduled.pop(0)[1]()
    worker = _Worker.last_instance
    thread = SlowStoppingThread.last_instance
    visible: list[object] = []
    controller.resultReady.connect(visible.append)

    worker.finished.emit({"result": 1})

    assert thread.wait_timeouts == []
    assert controller.is_running is True
    assert lifecycle.state("analysis_refresh") is TaskState.RUNNING
    assert visible == []
    assert thread.deleted is False
    heartbeats: list[bool] = []
    QtCore.QTimer.singleShot(0, lambda: heartbeats.append(True))
    QtWidgets.QApplication.instance().processEvents()
    assert heartbeats == [True]

    thread.finished.emit()

    assert controller.is_running is False
    assert lifecycle.state("analysis_refresh") is TaskState.COMPLETED
    assert visible == [{"result": 1}]
    assert thread.deleted is True


def test_controller_keeps_thread_wrapper_until_qobject_destroyed():
    class DestroyAwareThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.destroyed = _Signal()

    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=DestroyAwareThread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    controller.schedule()
    scheduled.pop(0)[1]()
    worker = _Worker.last_instance
    thread = DestroyAwareThread.last_instance

    worker.finished.emit({"result": 1})

    assert controller.shutdown() is False
    thread.destroyed.emit()
    assert controller.shutdown() is True


def test_controller_reports_shared_analysis_task_lifecycle() -> None:
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)

    controller.schedule()
    scheduled.pop(0)[1]()
    assert lifecycle.state("analysis_refresh") is TaskState.RUNNING

    _Worker.last_instance.finished.emit({"result": 1})
    assert lifecycle.state("analysis_refresh") is TaskState.COMPLETED


def test_controller_requests_analysis_stop_and_waits_for_cancelled_signal() -> None:
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    controller.schedule()
    scheduled.pop(0)[1]()
    worker = _Worker.last_instance

    lifecycle.request_stop_all()

    assert worker.stop_calls == 0
    assert worker.cancellation_token.is_requested() is True
    assert lifecycle.state("analysis_refresh") is TaskState.STOP_REQUESTED
    assert controller.is_running is True

    worker.cancelled.emit()
    assert lifecycle.state("analysis_refresh") is TaskState.COMPLETED
    assert controller.is_running is False


def test_controller_requests_thread_safe_token_without_calling_worker_qobject():
    class Token:
        def __init__(self) -> None:
            self.requested = False

        def request(self) -> None:
            self.requested = True

    class TokenWorker(_Worker):
        def __init__(self) -> None:
            super().__init__()
            self.cancellation_token = Token()

        def request_stop(self) -> None:
            raise AssertionError("controller must not call a worker QObject across threads")

    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=TokenWorker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    controller.schedule()
    scheduled.pop(0)[1]()
    worker = TokenWorker.last_instance

    controller.request_stop()

    assert worker.cancellation_token.requested is True


def test_controller_captures_cancellation_token_before_worker_moves_threads():
    class AffinityGuardedWorker(_Worker):
        @property
        def cancellation_token(self):
            if self.thread is not None:
                raise AssertionError(
                    "controller touched the worker wrapper after moveToThread"
                )
            return self._plain_token

        @cancellation_token.setter
        def cancellation_token(self, token) -> None:
            self._plain_token = token

    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=AffinityGuardedWorker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    controller.schedule()
    scheduled.pop(0)[1]()
    worker = AffinityGuardedWorker.last_instance

    controller.request_stop()

    assert worker._plain_token.is_requested() is True


def test_controller_rejects_analysis_refresh_after_shutdown_without_scheduling() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.begin_shutdown()
    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)

    assert controller.schedule() is False
    assert scheduled == []
    assert controller.pending is False
    assert controller.is_running is False
    assert lifecycle.state("analysis_refresh") is None


def test_pending_analysis_refresh_does_not_resume_after_shutdown() -> None:
    lifecycle = BackgroundTaskLifecycle()
    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=_Thread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
        lifecycle=lifecycle,
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    assert controller.schedule() is True
    scheduled.clear()
    lifecycle.begin_shutdown()

    assert controller.resume_if_idle() is False
    assert scheduled == []
    assert lifecycle.state("analysis_refresh") is None


def test_large_analysis_refresh_keeps_main_thread_heartbeat_responsive():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main_thread = QtCore.QThread.currentThread()
    loop = QtCore.QEventLoop()
    frame = pd.DataFrame(
        {
            "bar_index": range(270_000),
            "open_time_bjt": pd.date_range(
                "2025-01-01",
                periods=270_000,
                freq="min",
                tz="Asia/Shanghai",
            ),
            "close": 100.0,
        }
    )
    window = SimpleNamespace(
        df=frame,
        cursor=len(frame) - 1,
        session_id="sess_large",
        storage=SimpleNamespace(db_path=""),
        _market_data_generation=4,
        trades=[],
        _event_rows_for_study=lambda: [],
        _feature_rows_for_session=lambda: [],
        _current_equity_rows=lambda: (_ for _ in ()).throw(
            AssertionError("large equity rows must not be built on the UI thread")
        ),
        initialEquitySpin=SimpleNamespace(value=lambda: 10_000.0),
        tradeNotionalSpin=SimpleNamespace(value=lambda: 1_000.0),
    )
    order: list[str] = []
    calculation_threads: list[object] = []

    def build_performance(_trades, equity, _initial):
        calculation_threads.append(QtCore.QThread.currentThread())
        return {"equity_rows": len(equity)}

    controller = AnalysisRefreshController(
        snapshot_factory=lambda: MainWindow._analysis_refresh_request(window),
        is_playing=lambda: False,
        delay_ms=0,
        worker_factory=lambda: AnalysisRefreshWorker(
            build_event_study_fn=lambda _events, _features: pd.DataFrame(),
            build_ml_datasets_fn=lambda _features: {
                "ml_features": pd.DataFrame(),
                "ml_labels": pd.DataFrame(),
                "sample_index": pd.DataFrame(),
            },
            build_performance_summary_fn=build_performance,
            format_performance_report_fn=lambda summary: f"equity={summary['equity_rows']}",
        ),
    )
    controller.resultReady.connect(lambda _result: (order.append("result"), loop.quit()))
    controller.failed.connect(lambda _error: loop.quit())

    controller.schedule()
    QtCore.QTimer.singleShot(0, lambda: order.append("heartbeat"))
    QtCore.QTimer.singleShot(5000, loop.quit)
    loop.exec()
    app.processEvents()

    assert order == ["heartbeat", "result"]
    assert len(calculation_threads) == 1
    assert calculation_threads[0] is not main_thread
    controller.shutdown()


def test_large_analysis_refresh_returns_bounded_workspace_payload_after_heartbeat():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main_thread = QtCore.QThread.currentThread()
    loop = QtCore.QEventLoop()
    frame = pd.DataFrame(
        {
            "bar_index": range(270_000),
            "open_time_bjt": pd.date_range(
                "2025-01-01",
                periods=270_000,
                freq="min",
                tz="Asia/Shanghai",
            ),
            "close": 100.0,
        }
    )
    order: list[str] = []
    calculation_threads: list[object] = []
    results: list[object] = []

    def build_performance(_trades, equity, _initial):
        calculation_threads.append(QtCore.QThread.currentThread())
        return {"equity_rows": len(equity)}

    controller = AnalysisRefreshController(
        snapshot_factory=lambda: AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=[],
            equity_rows=[],
            initial_equity=10_000.0,
            market_frame=frame,
            market_cursor=len(frame) - 1,
            session_id="sess_workspace_large",
            trade_notional=1_000.0,
        ),
        is_playing=lambda: False,
        delay_ms=0,
        worker_factory=lambda: AnalysisRefreshWorker(
            build_event_study_fn=lambda _events, _features: pd.DataFrame(),
            build_ml_datasets_fn=lambda _features: {
                "ml_features": pd.DataFrame(),
                "ml_labels": pd.DataFrame(),
                "sample_index": pd.DataFrame(),
            },
            build_performance_summary_fn=build_performance,
            format_performance_report_fn=lambda summary: f"equity={summary['equity_rows']}",
        ),
    )

    def receive_result(result) -> None:
        results.append(result)
        order.append("result")
        loop.quit()

    controller.resultReady.connect(receive_result)
    controller.failed.connect(lambda _error: loop.quit())
    controller.schedule()
    QtCore.QTimer.singleShot(0, lambda: order.append("heartbeat"))
    QtCore.QTimer.singleShot(5000, loop.quit)
    loop.exec()
    app.processEvents()

    assert order == ["heartbeat", "result"]
    assert len(calculation_threads) == 1
    assert calculation_threads[0] is not main_thread
    payload = results[0].performance_workspace
    assert payload.equity_total_rows == 270_000
    assert len(payload.equity_rows) == 2_000
    assert payload.equity_rows[0]["bar_index"] == 0
    assert payload.equity_rows[-1]["bar_index"] == 269_999
    controller.shutdown()
