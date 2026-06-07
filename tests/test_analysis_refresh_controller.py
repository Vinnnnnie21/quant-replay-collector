from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from controllers.analysis_controller import AnalysisRefreshController
from services.analysis_refresh import AnalysisRefreshSnapshot
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

    def emit(self, value) -> None:
        for callback, _connection_type in list(self.connections):
            callback(value)


class _Worker:
    last_instance = None

    def __init__(self) -> None:
        self.finished = _Signal()
        self.failed = _Signal()
        self.thread = None
        self.deleted = False
        self.runs: list[object] = []
        _Worker.last_instance = self

    def moveToThread(self, thread) -> None:
        self.thread = thread

    def run(self, snapshot) -> None:
        self.runs.append(snapshot)

    def deleteLater(self) -> None:
        self.deleted = True


class _Thread:
    last_instance = None

    def __init__(self, _parent=None) -> None:
        self.started = False
        self.quit_called = False
        self.waited = False
        self.deleted = False
        _Thread.last_instance = self

    def start(self) -> None:
        self.started = True

    def quit(self) -> None:
        self.quit_called = True

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
    assert controller.pending is False
    assert controller.is_running is False


def test_controller_shutdown_stops_active_thread_and_clears_pending():
    playing = SimpleNamespace(value=False)
    scheduled: list[tuple[int, object]] = []
    controller = _controller(playing=playing, scheduled=scheduled)

    controller.schedule()
    scheduled.pop(0)[1]()
    thread = _Thread.last_instance

    controller.shutdown()

    assert controller.pending is False
    assert controller.is_running is False
    assert thread.quit_called is True
    assert thread.waited is True


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


def test_controller_waits_until_thread_stops_before_deleting_it():
    class SlowStoppingThread(_Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self.wait_timeouts: list[int | None] = []

        def wait(self, timeout=None) -> bool:
            self.wait_timeouts.append(timeout)
            return len(self.wait_timeouts) > 1

    scheduled: list[tuple[int, object]] = []
    controller = AnalysisRefreshController(
        snapshot_factory=lambda: {"snapshot": 1},
        is_playing=lambda: False,
        worker_factory=_Worker,
        thread_factory=SlowStoppingThread,
        single_shot=lambda delay, callback: scheduled.append((delay, callback)),
    )
    _ACTIVE_FAKE_CONTROLLERS.append(controller)
    controller.schedule()
    scheduled.pop(0)[1]()
    worker = _Worker.last_instance
    thread = SlowStoppingThread.last_instance

    worker.finished.emit({"result": 1})

    assert thread.wait_timeouts == [1000, None]
    assert thread.deleted is True
