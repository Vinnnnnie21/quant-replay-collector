from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6 import QtCore, QtWidgets

from main_app import MainWindow
from cancellation import CancellationToken
from multi_timeframe_panel import MultiTimeframeLoadWorker, MultiTimeframePanel
from safe_shutdown import SafeShutdownCoordinator
from task_lifecycle import BackgroundTaskLifecycle, TaskState


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _htf_frame() -> pd.DataFrame:
    times = pd.date_range("2026-05-27 09:00:00", periods=30, freq="5min", tz="Asia/Shanghai")
    return pd.DataFrame(
        {
            "bar_index": range(30),
            "open_time_bjt": times,
            "close_time_bjt": times + pd.Timedelta(minutes=5),
            "open": range(100, 130),
            "high": range(101, 131),
            "low": range(99, 129),
            "close": [100.5 + index for index in range(30)],
            "volume": range(1000, 1030),
        }
    )


def test_multi_timeframe_panel_imports_in_package_mode_without_app_dir_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    probe = (
        "import importlib, pathlib, sys; "
        "import quant_collector_app; "
        f"app_dir = {str(APP_DIR)!r}; "
        "sys.path = [p for p in sys.path if p != app_dir]; "
        "assert app_dir not in sys.path; "
        "importlib.import_module('quant_collector_app.multi_timeframe_panel')"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr


def test_panel_is_read_only_and_builds_cache_first_context_requests(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    requests = panel.build_load_requests(
        "BTCUSDT",
        "1m",
        dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    )

    assert "只读上下文" in panel.noticeLabel.text()
    assert [request.interval for request in requests] == ["5m", "15m"]
    assert all(request.symbol == "BTCUSDT" and request.use_cache is True for request in requests)
    panel.intervalChecks["1h"].setChecked(True)
    assert [request.interval for request in panel.build_load_requests("BTCUSDT", "1m", requests[0].start_dt_bjt, requests[0].end_dt_bjt)] == [
        "5m",
        "15m",
        "1h",
    ]
    panel.shutdown()


def test_primary_interval_is_shown_separately_from_selectable_contexts(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)

    panel.configure_for_primary("5m")

    assert "主周期" in panel.primaryIntervalLabel.text()
    assert "✓ 5m" in panel.primaryIntervalLabel.text()
    assert "高周期上下文" in panel.contextIntervalsLabel.text()
    assert panel.intervalChecks["5m"].isHidden()
    assert "5m" not in panel.selected_intervals()
    assert panel.selected_intervals() == ("15m", "1h")
    panel.shutdown()


def test_context_interval_buttons_show_checked_mark_and_reload_once(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    panel.configure_for_primary("1m")
    calls: list[tuple] = []
    args = ("BTCUSDT", "1m", object(), object())
    panel._last_request_args = args
    panel.request_context_load = lambda *payload: calls.append(payload)

    assert panel.intervalChecks["5m"].text() == "✓ 5m"
    assert panel.intervalChecks["15m"].text() == "✓ 15m"

    panel.intervalChecks["15m"].setChecked(False)
    assert panel.selected_intervals() == ("5m",)
    assert panel.intervalChecks["15m"].text() == "15m"
    assert calls == [args]

    calls.clear()
    panel.intervalChecks["15m"].setChecked(True)
    assert panel.selected_intervals() == ("5m", "15m")
    assert panel.intervalChecks["15m"].text() == "✓ 15m"
    assert calls == [args]
    panel.shutdown()


def test_context_render_translates_internal_status_without_duplicate_notice(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    panel.configure_for_primary("5m")
    context = {
        "1h": {
            "sync_status": "previous_completed_for_no_future",
            "htf_bar_index": None,
            "containing_htf_bar_index": None,
            "history_status": "insufficient_history",
            "htf_open_time_bjt": pd.Timestamp("2024-04-01 00:00:00", tz="Asia/Shanghai"),
            "close": 70486.0,
            "available_bars": 0,
            "pre_simple_ret_20": None,
            "realized_vol_20": None,
            "trend_regime": None,
            "volatility_regime": None,
        }
    }

    panel._latest_context = context
    panel._render_context(context)
    text = panel.summaryText.toPlainText()

    assert panel.noticeLabel.text() not in text
    assert "使用上一根已完成K线" in text
    assert "高周期时间" in text
    assert "收盘价" in text
    assert "历史不足" in text
    for forbidden in (
        "previous_completed_for_no_future",
        "contains_cursor",
        "HTF time",
        "close:",
        "ret20",
        "vol20",
        "trend:",
        "normal_vol",
        "high_vol",
        "low_vol",
    ):
        assert forbidden not in text
    panel.shutdown()


def test_context_render_retranslates_existing_summary_to_english(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    context = {
        "1h": {
            "sync_status": "previous_completed_for_no_future",
            "htf_bar_index": 19,
            "containing_htf_bar_index": 20,
            "history_status": "available",
            "htf_open_time_bjt": pd.Timestamp("2024-04-01 20:00:00", tz="Asia/Shanghai"),
            "close": 70486.0,
            "available_bars": 20,
            "pre_simple_ret_20": 0.0124,
            "realized_vol_20": 0.0218,
            "trend_regime": "uptrend",
            "volatility_regime": "normal_vol",
        }
    }
    panel._latest_context = context
    panel._render_context(context)

    panel.retranslate_ui("en_US")
    text = panel.summaryText.toPlainText()

    assert "Previous completed candle" in text
    assert "HTF Time" in text
    assert "Close" in text
    assert "20-Bar Return" in text
    assert "Uptrend" in text
    assert "Normal volatility" in text
    assert "previous_completed_for_no_future" not in text
    assert "normal_vol" not in text
    panel.shutdown()


def test_cursor_change_refreshes_context_summary(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    panel.set_context_frames({"5m": _htf_frame()})

    first = panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2026-05-27 10:42:00", tz="Asia/Shanghai")})
    first_text = panel.summaryText.toPlainText()
    second = panel.refresh_for_primary_row({"open_time_bjt": pd.Timestamp("2026-05-27 10:52:00", tz="Asia/Shanghai")})

    assert first["5m"]["htf_bar_index"] != second["5m"]["htf_bar_index"]
    assert panel.summaryText.toPlainText() != first_text
    panel.shutdown()


def test_context_failure_and_stale_state_do_not_touch_primary_samples(qapp):
    primary_df = pd.DataFrame({"close": [1.0, 2.0]})
    trades = [{"trade_id": "t1"}]
    events = [{"event_id": "e1"}]
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)

    panel.set_context_frames({}, {"5m": "network timeout"})
    assert "高周期上下文加载失败" in panel.summaryText.toPlainText()
    panel.mark_stale()

    assert primary_df["close"].tolist() == [1.0, 2.0]
    assert trades == [{"trade_id": "t1"}]
    assert events == [{"event_id": "e1"}]
    assert "待主周期重新加载" in panel.summaryText.toPlainText()
    panel.shutdown()


def test_main_window_context_refresh_reads_cursor_only_and_does_not_write_trade_events():
    received: list[dict] = []
    frame = pd.DataFrame({"open_time_bjt": [pd.Timestamp("2026-05-27 09:00:00", tz="Asia/Shanghai")]})
    window = SimpleNamespace(
        df=frame,
        cursor=0,
        trades=[{"trade_id": "t1"}],
        events=[{"event_id": "e1"}],
        multiTimeframePanel=SimpleNamespace(refresh_for_primary_row=lambda row: received.append(dict(row))),
    )

    MainWindow._refresh_multi_timeframe_context(window)

    assert len(received) == 1
    assert window.trades == [{"trade_id": "t1"}]
    assert window.events == [{"event_id": "e1"}]


def test_primary_context_load_uses_loaded_market_identity_without_changing_session():
    requests: list[tuple] = []
    window = SimpleNamespace(
        df=pd.DataFrame({"close": [1.0]}),
        market_dirty=False,
        _loaded_market_key=("BTCUSDT", "1m", "2026-05-26", "2026-05-27"),
        session_id="sess_primary",
        multiTimeframePanel=SimpleNamespace(request_context_load=lambda *args: requests.append(args)),
    )

    MainWindow._load_multi_timeframe_context(window)

    assert requests[0][0:2] == ("BTCUSDT", "1m")
    assert window.session_id == "sess_primary"


def test_dirty_primary_parameters_mark_old_context_stale_without_touching_samples():
    calls: list[str] = []
    window = SimpleNamespace(
        df=pd.DataFrame({"close": [1.0]}),
        playing=True,
        _accum=1.0,
        market_dirty=False,
        trades=[{"trade_id": "t1"}],
        events=[{"event_id": "e1"}],
        replay_controller=SimpleNamespace(playing=True, accumulated_bars=1.0),
        multiTimeframePanel=SimpleNamespace(mark_stale=lambda: calls.append("stale")),
        _is_market_params_dirty=lambda: True,
        _update_header=lambda: None,
        _show_market_dirty_feedback=lambda: None,
    )

    MainWindow.on_market_params_changed(window)

    assert calls == ["stale"]
    assert window.trades == [{"trade_id": "t1"}]
    assert window.events == [{"event_id": "e1"}]


def test_context_load_reports_shared_background_task_lifecycle(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    panel = MultiTimeframePanel(
        language="zh_CN",
        start_worker=False,
        lifecycle=lifecycle,
    )
    emitted: list[dict] = []
    panel._worker = SimpleNamespace(request_stop=lambda: None)
    panel.requestLoad.connect(emitted.append)

    panel.request_context_load(
        "BTCUSDT",
        "1m",
        dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    )
    assert lifecycle.state("multi_timeframe_load") is TaskState.RUNNING

    panel._on_loaded(panel._active_request_id, {"5m": _htf_frame()}, {})
    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED
    panel._worker = None
    panel.shutdown()


class _ControlledWorker(QtCore.QObject):
    finished = QtCore.Signal(str, object, object)
    cancelled = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.loads: list[dict] = []
        self.stop_calls = 0
        self.cancellation_token = CancellationToken()

    @QtCore.Slot(object)
    def load(self, payload: dict) -> None:
        self.loads.append(payload)

    def request_stop(self) -> None:
        self.stop_calls += 1


def _controlled_panel(lifecycle: BackgroundTaskLifecycle) -> tuple[MultiTimeframePanel, _ControlledWorker]:
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False, lifecycle=lifecycle)
    worker = _ControlledWorker()
    panel._worker = worker
    panel._cancellation_token = worker.cancellation_token
    panel.requestLoad.connect(worker.load)
    worker.finished.connect(panel._on_loaded)
    worker.cancelled.connect(panel._on_cancelled)
    return panel, worker


def test_multi_timeframe_worker_honors_stop_before_loading_requests() -> None:
    loads: list[object] = []
    loader = SimpleNamespace(load=lambda request, **_kwargs: loads.append(request))
    worker = MultiTimeframeLoadWorker(loader=loader)
    cancelled: list[str] = []
    worker.cancelled.connect(cancelled.append)

    worker.request_stop()
    worker.load({"request_id": "req_1", "requests": [object(), object()]})

    assert loads == []
    assert cancelled == ["req_1"]


def test_multi_timeframe_shutdown_requests_token_without_waiting_on_gui_thread(qapp):
    class RunningThread:
        def __init__(self) -> None:
            self.quit_calls = 0
            self.running = True

        def isRunning(self) -> bool:
            return self.running

        def quit(self) -> None:
            self.quit_calls += 1

        def wait(self, *_args):
            raise AssertionError("GUI shutdown must not wait for a QThread")

    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    token = CancellationToken()
    thread = RunningThread()
    panel._worker_thread = thread
    panel._worker = SimpleNamespace(cancellation_token=token)
    panel._cancellation_token = token
    panel._pending_request = {"request_id": "stale"}

    assert panel.shutdown() is False
    assert token.is_requested() is True
    assert panel._pending_request is None
    assert thread.quit_calls == 1


def test_multi_timeframe_panel_captures_token_before_worker_moves_threads(
    qapp, monkeypatch
):
    invalid_ui_wrapper_reads: list[bool] = []

    def get_token(worker):
        if (
            QtCore.QThread.currentThread() is qapp.thread()
            and worker.thread() is not qapp.thread()
        ):
            invalid_ui_wrapper_reads.append(True)
        return worker._plain_token

    def set_token(worker, token) -> None:
        worker._plain_token = token

    monkeypatch.setattr(
        MultiTimeframeLoadWorker,
        "cancellation_token",
        property(get_token, set_token),
        raising=False,
    )
    panel = MultiTimeframePanel(language="zh_CN", start_worker=True)

    assert panel.shutdown() is False
    loop = QtCore.QEventLoop()
    poll = QtCore.QTimer()
    poll.setInterval(0)
    poll.timeout.connect(lambda: panel.shutdown() and loop.quit())
    poll.start()
    QtCore.QTimer.singleShot(2_000, loop.quit)
    loop.exec()
    poll.stop()

    assert panel.shutdown() is True
    assert invalid_ui_wrapper_reads == []


def test_multi_timeframe_shutdown_treats_not_yet_running_thread_as_pending(qapp):
    class StartingThread:
        def isRunning(self) -> bool:
            return False

        def quit(self) -> None:
            raise AssertionError("quit is not useful before the event loop starts")

    panel = MultiTimeframePanel(language="zh_CN", start_worker=False)
    panel._worker_thread = StartingThread()
    token = CancellationToken()
    panel._worker = SimpleNamespace(cancellation_token=token)
    panel._cancellation_token = token

    assert panel.shutdown() is False

    panel._on_worker_thread_finished()
    assert panel.shutdown() is True


def test_multi_timeframe_worker_and_thread_are_deleted_on_qthread_finished(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=True)
    thread = panel._worker_thread
    worker = panel._worker
    destroyed: list[str] = []
    finished: list[bool] = []
    thread_destroyed_after_panel_cleanup: list[bool] = []
    references_at_thread_finished: list[bool] = []
    worker.destroyed.connect(lambda: destroyed.append("worker"))
    thread.destroyed.connect(
        lambda: (
            destroyed.append("thread"),
            thread_destroyed_after_panel_cleanup.append(panel._worker_thread is None),
        )
    )
    thread.finished.connect(lambda: finished.append(True))
    thread.finished.connect(
        lambda: references_at_thread_finished.append(
            panel._worker is worker and panel._worker_thread is thread
        )
    )

    assert panel.shutdown() is False
    loop = QtCore.QEventLoop()
    thread.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(2_000, loop.quit)
    loop.exec()
    qapp.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    qapp.processEvents()

    assert finished == [True]
    assert references_at_thread_finished == [True]
    assert panel._worker is None
    assert panel._worker_thread is None
    assert destroyed == ["worker", "thread"]
    assert thread_destroyed_after_panel_cleanup == [True]


def test_multi_timeframe_thread_deletion_is_wired_directly_to_finished(
    qapp, monkeypatch
):
    monkeypatch.setattr(
        MultiTimeframePanel,
        "_on_worker_thread_finished",
        lambda _self: None,
    )
    panel = MultiTimeframePanel(language="zh_CN", start_worker=True)
    thread = panel._worker_thread
    destroyed: list[bool] = []
    thread.destroyed.connect(lambda: destroyed.append(True))

    assert panel.shutdown() is False
    loop = QtCore.QEventLoop()
    thread.destroyed.connect(loop.quit)
    QtCore.QTimer.singleShot(2_000, loop.quit)
    loop.exec()

    assert destroyed == [True]
    assert panel._worker_thread is None


def test_multi_timeframe_thread_is_not_owned_by_the_widget_tree(qapp):
    panel = MultiTimeframePanel(language="zh_CN", start_worker=True)
    thread = panel._worker_thread

    assert thread.parent() is None

    panel.shutdown()
    loop = QtCore.QEventLoop()
    thread.destroyed.connect(loop.quit)
    QtCore.QTimer.singleShot(2_000, loop.quit)
    loop.exec()
    assert panel._worker_thread is None


def test_multi_timeframe_shutdown_completes_lifecycle_only_after_thread_finished(qapp):
    lifecycle = BackgroundTaskLifecycle()
    panel = MultiTimeframePanel(
        language="zh_CN",
        start_worker=True,
        lifecycle=lifecycle,
    )
    thread = panel._worker_thread
    panel._active_request_id = "req_shutdown"
    assert lifecycle.start(
        "multi_timeframe_load",
        request_stop=panel.request_stop,
    )

    lifecycle.request_stop_all()
    panel._on_cancelled("req_shutdown")

    assert lifecycle.state("multi_timeframe_load") is TaskState.STOP_REQUESTED
    assert panel.shutdown() is False
    loop = QtCore.QEventLoop()
    thread.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(2_000, loop.quit)
    if thread.isRunning():
        loop.exec()
    qapp.processEvents()

    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED


def test_cancelled_context_load_releases_shared_background_task(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False, lifecycle=lifecycle)
    panel._worker = SimpleNamespace(request_stop=lambda: None)
    panel.request_context_load(
        "BTCUSDT",
        "1m",
        dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    )
    request_id = panel._active_request_id
    lifecycle.request_stop_all()

    panel._on_cancelled(request_id)

    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED
    panel._worker = None
    panel.shutdown()


def test_context_load_after_shutdown_does_not_change_ui_or_emit_request(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.begin_shutdown()
    panel = MultiTimeframePanel(language="zh_CN", start_worker=False, lifecycle=lifecycle)
    panel._worker = SimpleNamespace(request_stop=lambda: None)
    panel.set_context_frames({"5m": _htf_frame()})
    previous_text = panel.summaryText.toPlainText()
    emitted: list[dict] = []
    panel.requestLoad.connect(emitted.append)

    panel.request_context_load(
        "BTCUSDT",
        "1m",
        dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    )

    assert panel.summaryText.toPlainText() == previous_text
    assert panel.refresh_for_primary_row(
        {"open_time_bjt": pd.Timestamp("2026-05-27 10:42:00", tz="Asia/Shanghai")}
    )
    assert emitted == []
    assert lifecycle.state("multi_timeframe_load") is None
    panel._worker = None
    panel.shutdown()


def test_context_load_single_flight_runs_only_first_and_latest_request(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    panel, worker = _controlled_panel(lifecycle)
    start = dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    end = dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8)))

    panel.request_context_load("AUSDT", "1m", start, end)
    panel.request_context_load("BUSDT", "1m", start, end)
    panel.request_context_load("CUSDT", "1m", start, end)

    assert [payload["requests"][0].symbol for payload in worker.loads] == ["AUSDT"]
    first_request_id = worker.loads[0]["request_id"]
    worker.finished.emit(first_request_id, {"5m": _htf_frame()}, {})

    assert [payload["requests"][0].symbol for payload in worker.loads] == ["AUSDT", "CUSDT"]
    assert lifecycle.state("multi_timeframe_load") is TaskState.RUNNING

    latest_request_id = worker.loads[-1]["request_id"]
    worker.finished.emit(latest_request_id, {"5m": _htf_frame()}, {})

    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED
    panel._worker = None
    panel.shutdown()


def test_safe_shutdown_discards_pending_context_load_and_completes_after_cancel(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    panel, worker = _controlled_panel(lifecycle)
    start = dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    end = dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    panel.request_context_load("AUSDT", "1m", start, end)
    panel.request_context_load("BUSDT", "1m", start, end)
    panel.request_context_load("CUSDT", "1m", start, end)
    scheduled: list[object] = []
    coordinator = SafeShutdownCoordinator(
        lifecycle=lifecycle,
        save=lambda: None,
        show_status=lambda _message: None,
        schedule_poll=scheduled.append,
        finalize=lambda: True,
    )

    assert coordinator.request_close() is False
    assert worker.stop_calls == 0
    assert worker.cancellation_token.is_requested() is True
    assert panel._pending_request is None
    assert lifecycle.state("multi_timeframe_load") is TaskState.STOP_REQUESTED

    current_request_id = worker.loads[0]["request_id"]
    worker.cancelled.emit(current_request_id)

    assert [payload["requests"][0].symbol for payload in worker.loads] == ["AUSDT"]
    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED
    scheduled.pop(0)()
    assert coordinator.request_close() is True
    panel._worker = None
    panel.shutdown()


def test_stale_context_signals_do_not_update_latest_ui_or_complete_lifecycle(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    panel, worker = _controlled_panel(lifecycle)
    start = dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    end = dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    failures: list[tuple[str, str]] = []
    panel.loadFailed.connect(lambda interval, error: failures.append((interval, error)))
    panel.request_context_load("AUSDT", "1m", start, end)
    panel.request_context_load("CUSDT", "1m", start, end)
    first_request_id = worker.loads[0]["request_id"]

    worker.finished.emit(first_request_id, {"5m": _htf_frame()}, {})
    latest_request_id = worker.loads[-1]["request_id"]
    latest_loading_text = panel.summaryText.toPlainText()
    worker.finished.emit(first_request_id, {}, {"5m": "stale failure"})
    worker.cancelled.emit(first_request_id)

    assert panel.summaryText.toPlainText() == latest_loading_text
    assert failures == []
    assert lifecycle.state("multi_timeframe_load") is TaskState.RUNNING

    worker.finished.emit(latest_request_id, {"5m": _htf_frame()}, {})
    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED
    panel._worker = None
    panel.shutdown()


def test_mark_stale_discards_pending_request_and_completes_running_load(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    panel, worker = _controlled_panel(lifecycle)
    start = dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    end = dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    panel.request_context_load("AUSDT", "1m", start, end)
    panel.request_context_load("BUSDT", "1m", start, end)
    first_request_id = worker.loads[0]["request_id"]

    panel.mark_stale()
    stale_text = panel.summaryText.toPlainText()
    worker.finished.emit(first_request_id, {"5m": _htf_frame()}, {})

    assert [payload["requests"][0].symbol for payload in worker.loads] == ["AUSDT"]
    assert panel.summaryText.toPlainText() == stale_text
    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED
    assert panel._pending_request is None
    panel._worker = None
    panel.shutdown()


def test_request_after_mark_stale_replaces_discarded_pending_request(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    panel, worker = _controlled_panel(lifecycle)
    start = dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    end = dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    panel.request_context_load("AUSDT", "1m", start, end)
    panel.request_context_load("BUSDT", "1m", start, end)
    first_request_id = worker.loads[0]["request_id"]

    panel.mark_stale()
    panel.request_context_load("CUSDT", "1m", start, end)
    worker.finished.emit(first_request_id, {"5m": _htf_frame()}, {})

    assert [payload["requests"][0].symbol for payload in worker.loads] == ["AUSDT", "CUSDT"]
    assert lifecycle.state("multi_timeframe_load") is TaskState.RUNNING

    latest_request_id = worker.loads[-1]["request_id"]
    worker.finished.emit(latest_request_id, {"5m": _htf_frame()}, {})

    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED
    assert panel._pending_request is None
    panel._worker = None
    panel.shutdown()


def test_marking_running_context_stale_keeps_latest_reload_in_single_flight(qapp) -> None:
    lifecycle = BackgroundTaskLifecycle()
    panel, worker = _controlled_panel(lifecycle)
    start = dt.datetime(2026, 5, 26, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    end = dt.datetime(2026, 5, 27, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    panel.request_context_load("AUSDT", "1m", start, end)
    first_request_id = worker.loads[0]["request_id"]

    panel.mark_stale()
    panel.request_context_load("CUSDT", "1m", start, end)

    assert [payload["requests"][0].symbol for payload in worker.loads] == ["AUSDT"]
    worker.finished.emit(first_request_id, {"5m": _htf_frame()}, {})
    assert [payload["requests"][0].symbol for payload in worker.loads] == ["AUSDT", "CUSDT"]
    assert lifecycle.state("multi_timeframe_load") is TaskState.RUNNING

    latest_request_id = worker.loads[-1]["request_id"]
    worker.finished.emit(latest_request_id, {"5m": _htf_frame()}, {})
    assert lifecycle.state("multi_timeframe_load") is TaskState.COMPLETED
    panel._worker = None
    panel.shutdown()


def test_multi_timeframe_worker_stops_between_context_requests() -> None:
    loads: list[object] = []
    holder = SimpleNamespace(worker=None)

    def load(request, **_kwargs):
        loads.append(request)
        holder.worker.request_stop()
        return pd.DataFrame(), "Loading cancelled."

    worker = MultiTimeframeLoadWorker(loader=SimpleNamespace(load=load))
    holder.worker = worker
    cancelled: list[str] = []
    worker.cancelled.connect(cancelled.append)

    worker.load({"request_id": "req_2", "requests": [object(), object()]})

    assert len(loads) == 1
    assert cancelled == ["req_2"]


def test_multi_timeframe_worker_normalizes_context_frame_before_emitting_result() -> None:
    raw_frame = _htf_frame().drop(columns=["close_time_bjt"])
    request = SimpleNamespace(interval="5m", symbol="BTCUSDT")
    worker = MultiTimeframeLoadWorker(
        loader=SimpleNamespace(load=lambda _request, **_kwargs: (raw_frame, "Loaded cache."))
    )
    completed: list[dict[str, pd.DataFrame]] = []
    worker.finished.connect(lambda _request_id, frames, _failures: completed.append(frames))

    worker.load({"request_id": "req_normalize", "requests": [request]})

    normalized = completed[0]["5m"]
    assert "_open_time" in normalized.columns
    assert "_close_time" in normalized.columns
    assert normalized.attrs["_qrc_htf_interval"] == "5m"
