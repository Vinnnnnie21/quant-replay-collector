from __future__ import annotations

import threading

import pandas as pd
import pytest


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from controllers.historical_performance_controller import (
    HistoricalPerformanceController,
)
from cancellation import CancellationToken
from market_data.cache import read_cached_kline_range
from storage import StorageManager
import workers.historical_performance_worker as historical_worker_module
from workers.historical_performance_worker import HistoricalPerformanceWorker


class _BlockingWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(object)

    def __init__(self, release: threading.Event, worker_threads: list[object]) -> None:
        super().__init__()
        self._release = release
        self._worker_threads = worker_threads

    @QtCore.Slot(object)
    def run(self, request) -> None:
        self._worker_threads.append(QtCore.QThread.currentThread())
        if not self._release.wait(2.0):
            self.failed.emit(
                type("Failure", (), {"revision": request.revision, "message": "timeout"})()
            )
            return
        self.finished.emit(
            type(
                "Result",
                (),
                {
                    "revision": request.revision,
                    "session_id": request.session_id,
                    "payload": request.session_id,
                },
            )()
        )

    def request_stop(self) -> None:
        self._release.set()


class _ManualWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(object)

    def __init__(self, requests: list[object]) -> None:
        super().__init__()
        self.requests = requests
        self.stop_calls = 0

    @QtCore.Slot(object)
    def run(self, request) -> None:
        self.requests.append(request)

    def request_stop(self) -> None:
        self.stop_calls += 1


def _process_until(predicate, timeout_ms: int = 2_000) -> bool:
    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer()
    timer.setInterval(0)

    def poll() -> None:
        if predicate():
            loop.quit()

    timer.timeout.connect(poll)
    timer.start()
    QtCore.QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()
    return bool(predicate())


def test_historical_performance_request_keeps_qt_heartbeat_responsive():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main_thread = QtCore.QThread.currentThread()
    release = threading.Event()
    worker_threads: list[object] = []
    order: list[str] = []
    loop = QtCore.QEventLoop()
    controller = HistoricalPerformanceController(
        db_path="history.db",
        worker_factory=lambda _db_path: _BlockingWorker(release, worker_threads),
    )
    controller.resultReady.connect(
        lambda result: (order.append(f"result:{result.session_id}"), loop.quit())
    )

    assert controller.request("session_a") is True
    QtCore.QTimer.singleShot(0, lambda: (order.append("heartbeat"), release.set()))
    QtCore.QTimer.singleShot(3000, loop.quit)
    loop.exec()
    app.processEvents()

    assert order == ["heartbeat", "result:session_a"]
    assert worker_threads and worker_threads[0] is not main_thread
    assert controller.is_running is False


def test_historical_performance_discards_a_and_runs_only_latest_b():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from task_lifecycle import BackgroundTaskLifecycle, TaskState

    requests: list[object] = []
    workers: list[_ManualWorker] = []
    lifecycle = BackgroundTaskLifecycle()

    def worker_factory(_db_path: str) -> _ManualWorker:
        worker = _ManualWorker(requests)
        workers.append(worker)
        return worker

    controller = HistoricalPerformanceController(
        db_path="history.db",
        worker_factory=worker_factory,
        lifecycle=lifecycle,
    )
    visible: list[str] = []
    controller.resultReady.connect(lambda result: visible.append(result.session_id))

    assert controller.request("session_a") is True
    assert _process_until(lambda: len(requests) == 1)
    assert controller.request("session_b") is False
    workers[0].finished.emit(
        type(
            "Result",
            (),
            {"revision": requests[0].revision, "session_id": "session_a", "payload": "A"},
        )()
    )

    assert _process_until(lambda: len(requests) == 2)
    assert visible == []
    assert requests[1].session_id == "session_b"

    workers[1].finished.emit(
        type(
            "Result",
            (),
            {"revision": requests[1].revision, "session_id": "session_b", "payload": "B"},
        )()
    )
    assert _process_until(lambda: visible == ["session_b"])
    app.processEvents()

    assert visible == ["session_b"]
    assert controller.is_running is False
    assert lifecycle.state("historical_performance") is TaskState.COMPLETED


def test_historical_controller_requests_token_without_cross_thread_worker_call():
    requests: list[object] = []
    workers: list[object] = []

    class TokenWorker(_ManualWorker):
        def __init__(self, values: list[object]) -> None:
            super().__init__(values)
            self.cancellation_token = CancellationToken()

        def request_stop(self) -> None:
            raise AssertionError("controller must not call a worker QObject across threads")

    def worker_factory(_db_path):
        worker = TokenWorker(requests)
        workers.append(worker)
        return worker

    controller = HistoricalPerformanceController(
        db_path="history.db",
        worker_factory=worker_factory,
    )
    assert controller.request("session_a") is True
    assert _process_until(lambda: len(requests) == 1)
    worker = workers[0]

    controller.request_stop()

    assert worker.cancellation_token.is_requested() is True
    worker.cancelled.emit(
        type("Cancelled", (), {"revision": requests[0].revision})()
    )
    assert _process_until(lambda: not controller.is_running)


def test_historical_controller_captures_token_before_worker_moves_threads():
    requests: list[object] = []
    workers: list[object] = []

    class AffinityGuardedWorker(_ManualWorker):
        def __init__(self, values: list[object]) -> None:
            super().__init__(values)
            self._plain_token = CancellationToken()
            self._moved = False
            self.invalid_wrapper_access = False

        @property
        def cancellation_token(self):
            if self._moved:
                self.invalid_wrapper_access = True
            return self._plain_token

        def moveToThread(self, thread) -> None:
            super().moveToThread(thread)
            self._moved = True

    def worker_factory(_db_path):
        worker = AffinityGuardedWorker(requests)
        workers.append(worker)
        return worker

    controller = HistoricalPerformanceController(
        db_path="history.db",
        worker_factory=worker_factory,
    )
    assert controller.request("session_a") is True
    assert _process_until(lambda: len(requests) == 1)
    worker = workers[0]

    controller.request_stop()
    worker.cancelled.emit(
        type("Cancelled", (), {"revision": requests[0].revision})()
    )
    assert _process_until(lambda: not controller.is_running)

    assert worker.invalid_wrapper_access is False
    assert worker._plain_token.is_requested() is True


def test_historical_worker_cancels_during_curve_construction_without_ui_result(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    entered_construction = threading.Event()
    release_construction = threading.Event()

    class SlowMarketRows:
        def __iter__(self):
            for index in range(2_000):
                if index == 0:
                    entered_construction.set()
                    assert release_construction.wait(2.0)
                yield {
                    "bar_index": index,
                    "open_time_bjt": f"2026-01-01T00:{index % 60:02d}:00+08:00",
                    "open_time_utc_ms": 1_767_196_800_000 + index * 60_000,
                    "close": 100.0,
                }

    class StorageBoundary:
        def load_session_snapshot(self, _session_id):
            return (
                {
                    "session_id": "session_history",
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "start_date_bjt": "2026-01-01",
                    "end_date_bjt": "2026-01-02",
                    "initial_equity": 1_000.0,
                    "trade_notional": 500.0,
                },
                [],
                [],
            )

        def fetch_klines_for_range(self, **_kwargs):
            return SlowMarketRows()

    monkeypatch.setattr(
        historical_worker_module,
        "StorageManager",
        lambda _db_path: StorageBoundary(),
    )
    worker_finished: list[object] = []
    worker_cancelled: list[object] = []

    def worker_factory(db_path: str):
        worker = HistoricalPerformanceWorker(db_path)
        worker.finished.connect(worker_finished.append)
        worker.cancelled.connect(worker_cancelled.append)
        return worker

    controller = HistoricalPerformanceController(
        db_path="history.db",
        worker_factory=worker_factory,
    )
    visible_results: list[object] = []
    controller.resultReady.connect(visible_results.append)

    assert controller.request("session_history") is True
    assert entered_construction.wait(2.0)
    controller.request_stop()
    release_construction.set()

    assert _process_until(lambda: not controller.is_running, timeout_ms=3_000)
    app.processEvents()
    assert worker_cancelled
    assert worker_finished == []
    assert visible_results == []


def test_historical_worker_cancels_during_csv_cache_read_without_ui_result(
    tmp_path,
    monkeypatch,
):
    import market_data.cache as market_cache_module

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    entered_cache_read = threading.Event()
    release_cache_read = threading.Event()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "BTCUSDT_1m_20260101_20260101_bjt.csv").touch()

    class StorageBoundary:
        def load_session_snapshot(self, _session_id):
            return (
                {
                    "session_id": "session_history",
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "start_date_bjt": "2026-01-01",
                    "end_date_bjt": "2026-01-01",
                    "cursor_bar_index": 1,
                    "initial_equity": 1_000.0,
                    "trade_notional": 500.0,
                },
                [],
                [],
            )

        def fetch_klines_for_range(self, **_kwargs):
            return []

    def blocking_read_csv(*_args, **_kwargs):
        def chunks():
            entered_cache_read.set()
            assert release_cache_read.wait(2.0)
            yield pd.DataFrame(
                {
                    "open_time_ms": [1_767_196_800_000, 1_767_196_860_000],
                    "open_time_bjt": [
                        "2026-01-01T00:00:00+08:00",
                        "2026-01-01T00:01:00+08:00",
                    ],
                    "close": [100.0, 100.0],
                }
            )

        return chunks()

    monkeypatch.setattr(
        historical_worker_module,
        "StorageManager",
        lambda _db_path: StorageBoundary(),
    )
    monkeypatch.setattr(market_cache_module.pd, "read_csv", blocking_read_csv)
    worker_finished: list[object] = []
    worker_cancelled: list[object] = []

    def worker_factory(db_path: str):
        worker = HistoricalPerformanceWorker(db_path)
        worker.finished.connect(worker_finished.append)
        worker.cancelled.connect(worker_cancelled.append)
        return worker

    controller = HistoricalPerformanceController(
        db_path=tmp_path / "history.db",
        worker_factory=worker_factory,
    )
    visible_results: list[object] = []
    controller.resultReady.connect(visible_results.append)

    assert controller.request("session_history") is True
    assert entered_cache_read.wait(2.0)
    controller.request_stop()
    release_cache_read.set()

    assert _process_until(lambda: not controller.is_running, timeout_ms=3_000)
    app.processEvents()
    assert worker_cancelled
    assert worker_finished == []
    assert visible_results == []


def test_historical_worker_cancels_inside_accounting_curve_loop(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    entered_accounting = threading.Event()
    release_first_bar = threading.Event()
    allow_uncancelled_finish = threading.Event()

    class BlockingClose:
        def __init__(self, *, first: bool) -> None:
            self.first = first

        def __float__(self) -> float:
            if self.first:
                entered_accounting.set()
                assert release_first_bar.wait(2.0)
            else:
                assert allow_uncancelled_finish.wait(2.0)
            return 100.0

    class StorageBoundary:
        def load_session_snapshot(self, _session_id):
            return (
                {
                    "session_id": "session_history",
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "start_date_bjt": "2026-01-01",
                    "end_date_bjt": "2026-01-01",
                    "initial_equity": 1_000.0,
                    "trade_notional": 500.0,
                },
                [],
                [],
            )

        def fetch_klines_for_range(self, **_kwargs):
            return [
                {
                    "bar_index": 0,
                    "open_time_bjt": "2026-01-01T00:00:00+08:00",
                    "open_time_utc_ms": 1_767_196_800_000,
                    "close": BlockingClose(first=True),
                },
                {
                    "bar_index": 1,
                    "open_time_bjt": "2026-01-01T00:01:00+08:00",
                    "open_time_utc_ms": 1_767_196_860_000,
                    "close": BlockingClose(first=False),
                },
            ]

    monkeypatch.setattr(
        historical_worker_module,
        "StorageManager",
        lambda _db_path: StorageBoundary(),
    )
    worker_finished: list[object] = []
    worker_cancelled: list[object] = []

    def worker_factory(db_path: str):
        worker = HistoricalPerformanceWorker(db_path)
        worker.finished.connect(worker_finished.append)
        worker.cancelled.connect(worker_cancelled.append)
        return worker

    controller = HistoricalPerformanceController(
        db_path="history.db",
        worker_factory=worker_factory,
    )

    assert controller.request("session_history") is True
    assert entered_accounting.wait(2.0)
    controller.request_stop()
    release_first_bar.set()

    cancelled_promptly = _process_until(
        lambda: not controller.is_running,
        timeout_ms=500,
    )
    allow_uncancelled_finish.set()
    assert _process_until(lambda: not controller.is_running, timeout_ms=3_000)
    app.processEvents()
    assert cancelled_promptly is True
    assert worker_cancelled
    assert worker_finished == []


def test_historical_controller_keeps_thread_wrapper_until_qobject_destroyed():
    class Signal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback, *_args) -> None:
            self.callbacks.append(callback)

        def emit(self, *args) -> None:
            for callback in list(self.callbacks):
                callback(*args)

    class Worker:
        last_instance = None

        def __init__(self, _db_path) -> None:
            self.finished = Signal()
            self.failed = Signal()
            self.cancelled = Signal()
            self.cancellation_token = CancellationToken()
            Worker.last_instance = self

        def moveToThread(self, _thread) -> None:
            pass

        def run(self, _request) -> None:
            pass

        def deleteLater(self) -> None:
            pass

    class Thread:
        last_instance = None

        def __init__(self, _parent=None) -> None:
            self.finished = Signal()
            self.destroyed = Signal()
            Thread.last_instance = self

        def start(self) -> None:
            pass

        def quit(self) -> None:
            self.finished.emit()

        def deleteLater(self) -> None:
            pass

    controller = HistoricalPerformanceController(
        db_path="history.db",
        worker_factory=Worker,
        thread_factory=Thread,
    )
    assert controller.request("session_a") is True
    worker = Worker.last_instance
    thread = Thread.last_instance

    worker.cancelled.emit(type("Cancelled", (), {"revision": 1})())

    assert controller.shutdown() is False
    thread.destroyed.emit()
    assert controller.shutdown() is True


def test_historical_start_failure_retains_running_thread_until_finished():
    class Signal:
        def __init__(self) -> None:
            self.callbacks = []

        def connect(self, callback, *_args) -> None:
            self.callbacks.append(callback)

        def emit(self, *args) -> None:
            for callback in list(self.callbacks):
                callback(*args)

    class Worker:
        def __init__(self, _db_path) -> None:
            self.finished = Signal()
            self.failed = Signal()
            self.cancelled = Signal()
            self.cancellation_token = CancellationToken()

        def moveToThread(self, _thread) -> None:
            pass

        def run(self, _request) -> None:
            pass

        def deleteLater(self) -> None:
            pass

    class Thread:
        last_instance = None

        def __init__(self, _parent=None) -> None:
            self.finished = Signal()
            self.running = False
            self.quit_calls = 0
            Thread.last_instance = self

        def start(self) -> None:
            self.running = True
            raise RuntimeError("historical start failed after ownership was published")

        def isRunning(self) -> bool:
            return self.running

        def quit(self) -> None:
            self.quit_calls += 1

        def deleteLater(self) -> None:
            pass

    from task_lifecycle import BackgroundTaskLifecycle, TaskState

    lifecycle = BackgroundTaskLifecycle()
    errors: list[str] = []
    controller = HistoricalPerformanceController(
        db_path="history.db",
        worker_factory=Worker,
        thread_factory=Thread,
        lifecycle=lifecycle,
    )
    controller.failed.connect(errors.append)

    assert controller.request("session_a") is False
    thread = Thread.last_instance
    assert controller.is_running is True
    assert lifecycle.state("historical_performance") is TaskState.RUNNING
    assert errors == []

    thread.finished.emit()

    assert controller.is_running is False
    assert lifecycle.state("historical_performance") is TaskState.FAILED
    assert errors and "historical start failed" in errors[0]


def test_historical_performance_default_worker_reads_private_sqlite_connection(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "history.db")
    storage.upsert_session(
        {
            "session_id": "session_history",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
            "initial_equity": 1_000.0,
            "trade_notional": 500.0,
            "last_saved_at": "2026-01-01T00:01:00+08:00",
        }
    )
    with storage.connect() as connection:
        connection.execute(
            """
            INSERT INTO trades (
                trade_id, session_id, side, status, net_return_pct,
                net_pnl_quote, entry_bar_index, exit_bar_index,
                entry_fill_price, notional_quote, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trade_history",
                "session_history",
                "LONG",
                "CLOSED",
                2.0,
                10.0,
                0,
                0,
                100.0,
                500.0,
                "2026-01-01T00:00:00+08:00",
                "2026-01-01T00:01:00+08:00",
            ),
        )
    storage.replace_equity_curve(
        "session_history",
        [
            {
                "session_id": "session_history",
                "sequence_no": 1,
                "equity_before": 1_000.0,
                "realized_net_pnl": 10.0,
                "equity_after": 1_010.0,
                "equity_return_pct": 1.0,
                "drawdown_pct": 0.0,
                "created_at": "2026-01-01T00:01:00+08:00",
            }
        ],
    )
    storage.upsert_klines(
        [
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "open_time_utc_ms": 1_767_196_800_000,
                "open_time_bjt": "2026-01-01T00:00:00+08:00",
                "close_time_utc_ms": 1_767_196_859_999,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
            }
        ]
    )
    controller = HistoricalPerformanceController(db_path=storage.db_path)
    results: list[object] = []
    errors: list[str] = []
    controller.resultReady.connect(results.append)
    controller.failed.connect(errors.append)

    assert controller.request("session_history") is True
    assert _process_until(lambda: bool(results) or bool(errors), timeout_ms=3_000)
    app.processEvents()

    assert errors == []
    assert results[0].session_id == "session_history"
    assert results[0].payload.default_notional == 500.0
    assert results[0].payload.metrics["current_equity"] == 1_010.0


def test_historical_worker_reports_missing_data_when_saved_cursor_exceeds_klines(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "partial_history.db")
    storage.upsert_session(
        {
            "session_id": "session_partial",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
            "cursor_bar_index": 2,
            "initial_equity": 1_000.0,
            "trade_notional": 500.0,
        }
    )
    storage.upsert_klines(
        [
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "open_time_utc_ms": 1_767_196_800_000,
                "open_time_bjt": "2026-01-01T00:00:00+08:00",
                "close_time_utc_ms": 1_767_196_859_999,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1.0,
            }
        ]
    )
    controller = HistoricalPerformanceController(db_path=storage.db_path)
    results: list[object] = []
    errors: list[str] = []
    controller.resultReady.connect(results.append)
    controller.failed.connect(errors.append)

    assert controller.request("session_partial") is True
    assert _process_until(lambda: bool(results) or bool(errors), timeout_ms=3_000)
    app.processEvents()

    assert errors == []
    assert results[0].payload is None
    assert results[0].empty_reason == "performance.curve_missing_market_data"


def test_historical_worker_uses_csv_cache_when_sqlite_klines_are_empty(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    storage = StorageManager(tmp_path / "history.db")
    storage.upsert_session(
        {
            "session_id": "session_cached_history",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
            "cursor_bar_index": 2,
            "initial_equity": 1_000.0,
            "trade_notional": 500.0,
        }
    )
    storage.insert_trade(
        {
            "trade_id": "trade_cached_history",
            "session_id": "session_cached_history",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "side": "LONG",
            "status": "CLOSED",
            "entry_bar_index": 0,
            "exit_bar_index": 2,
            "entry_fill_price": 100.0,
            "exit_fill_price": 102.0,
            "notional_quote": 500.0,
            "net_pnl_quote": 10.0,
            "created_at": "2026-01-01T00:00:00+08:00",
            "updated_at": "2026-01-01T00:02:00+08:00",
        }
    )
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    history_times = [
        "2026-01-01T00:00:00+08:00",
        "2026-01-01T00:01:00+08:00",
        "2026-01-01T00:02:00+08:00",
    ]
    pd.DataFrame(
        [
            {
                "open_time_ms": 1_767_196_800_000 + index * 60_000,
                "open_time_bjt": open_time,
                "close": close,
                "bar_index": index,
            }
            for index, (open_time, close) in enumerate(
                zip(history_times, (100.0, 101.0, 102.0), strict=True)
            )
        ]
    ).to_csv(
        cache_dir / "BTCUSDT_1m_20260101_20260101_bjt.csv",
        index=False,
    )
    assert storage.fetch_table("klines") == []
    controller = HistoricalPerformanceController(db_path=storage.db_path)
    results: list[object] = []
    errors: list[str] = []
    controller.resultReady.connect(results.append)
    controller.failed.connect(errors.append)

    assert controller.request("session_cached_history") is True
    assert _process_until(lambda: bool(results) or bool(errors), timeout_ms=3_000)
    app.processEvents()

    assert errors == []
    assert results[0].payload is not None
    assert [row["time"] for row in results[0].payload.equity_rows] == history_times
    assert results[0].payload.metrics["current_equity"] == pytest.approx(1_010.0)
    assert storage.fetch_table("klines") == []


def test_historical_cache_range_reader_combines_overlaps_without_mutating_files(
    tmp_path,
):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    start_time_utc_ms = 1_767_196_800_000
    paths = [
        cache_dir / "BTCUSDT_1m_20251231_20260101_bjt.csv",
        cache_dir / "BTCUSDT_1m_20260101_20260102_bjt.csv",
    ]
    pd.DataFrame(
        {
            "open_time_ms": [start_time_utc_ms, start_time_utc_ms + 60_000],
            "open_time_bjt": [
                "2026-01-01T00:00:00+08:00",
                "2026-01-01T00:01:00+08:00",
            ],
            "close": [100.0, 101.0],
        }
    ).to_csv(paths[0], index=False)
    pd.DataFrame(
        {
            "open_time_ms": [
                start_time_utc_ms + 60_000,
                start_time_utc_ms + 120_000,
            ],
            "open_time_bjt": [
                "2026-01-01T00:01:00+08:00",
                "2026-01-01T00:02:00+08:00",
            ],
            "close": [101.0, 102.0],
        }
    ).to_csv(paths[1], index=False)
    modified_times = [path.stat().st_mtime_ns for path in paths]

    rows = read_cached_kline_range(
        cache_dir,
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=start_time_utc_ms,
        end_time_utc_ms=start_time_utc_ms + 120_000,
        minimum_rows=3,
    )

    assert [row["bar_index"] for row in rows] == [0, 1, 2]
    assert [row["open_time_utc_ms"] for row in rows] == [
        start_time_utc_ms,
        start_time_utc_ms + 60_000,
        start_time_utc_ms + 120_000,
    ]
    assert [row["close"] for row in rows] == [100.0, 101.0, 102.0]
    assert [path.stat().st_mtime_ns for path in paths] == modified_times
