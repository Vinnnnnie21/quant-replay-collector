from __future__ import annotations

import threading
from types import SimpleNamespace

import pandas as pd
import pytest

QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from services.analysis_refresh import (
    AnalysisRefreshRequest,
    AnalysisRefreshResult,
    AnalysisRefreshSnapshot,
    PublishedMarketData,
)
from workers.analysis_refresh_worker import AnalysisRefreshWorker


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_analysis_refresh_worker_emits_result_without_qt_widget_access():
    _app()
    worker = AnalysisRefreshWorker(
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
    )
    results: list[AnalysisRefreshResult] = []
    failures: list[str] = []
    worker.finished.connect(results.append)
    worker.failed.connect(failures.append)

    worker.run(
        AnalysisRefreshSnapshot(
            events=[{"event_id": "evt_1"}],
            features=[{"event_id": "evt_1", "pre_ret_20": 0.1}],
            trades=[{"trade_id": "trd_1"}],
            equity_rows=[{"sequence_no": 1}],
            initial_equity=10000.0,
        )
    )

    assert failures == []
    assert len(results) == 1
    assert results[0].event_study.iloc[0]["feature_count"] == 1
    assert results[0].performance_text == "trades=1"


def test_analysis_refresh_worker_honors_stop_before_calculation() -> None:
    _app()
    calculations: list[bool] = []
    worker = AnalysisRefreshWorker(
        build_event_study_fn=lambda *_args: calculations.append(True),
    )
    cancelled: list[bool] = []
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.request_stop()
    worker.run(
        AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=[],
            equity_rows=[],
            initial_equity=10000.0,
        )
    )

    assert cancelled == [True]
    assert calculations == []


def test_analysis_refresh_worker_stops_between_calculation_stages() -> None:
    _app()
    later_stages: list[bool] = []
    holder = {"worker": None}

    def build_event_study(_events, _features):
        holder["worker"].request_stop()
        return pd.DataFrame()

    worker = AnalysisRefreshWorker(
        build_event_study_fn=build_event_study,
        build_ml_datasets_fn=lambda _features: later_stages.append(True),
    )
    holder["worker"] = worker
    cancelled: list[bool] = []
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.run(
        AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=[],
            equity_rows=[],
            initial_equity=10000.0,
        )
    )

    assert cancelled == [True]
    assert later_stages == []


def test_analysis_refresh_worker_emits_low_frequency_stage_progress() -> None:
    _app()
    worker = AnalysisRefreshWorker(
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda _trades, _equity, _initial: {},
        format_performance_report_fn=lambda _summary: "ok",
    )
    progress: list[object] = []
    worker.progress.connect(progress.append)

    worker.run(
        AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=[],
            equity_rows=[],
            initial_equity=10_000.0,
            revision=7,
        )
    )

    assert [(event.revision, event.message) for event in progress] == [
        (7, "正在准备事件研究…"),
        (7, "正在准备研究样本…"),
        (7, "正在计算绩效统计…"),
    ]


def test_analysis_request_preparation_and_feature_read_run_in_worker_thread():
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    main_thread_id = threading.get_ident()
    observed_thread_ids: list[int] = []
    results: list[AnalysisRefreshResult] = []
    loop = QtCore.QEventLoop()
    frame = pd.DataFrame(
        {
            "bar_index": [0, 1],
            "open_time_bjt": pd.date_range(
                "2025-01-01", periods=2, freq="min", tz="Asia/Shanghai"
            ),
            "close": [100.0, 101.0],
        }
    )

    class Storage:
        def load_session_snapshot(self, session_id):
            observed_thread_ids.append(threading.get_ident())
            assert session_id == "sess_worker"
            return ({"session_id": session_id}, [], [])

        def fetch_table(self, table, where, params):
            observed_thread_ids.append(threading.get_ident())
            assert (table, where, params) == (
                "event_features",
                "session_id=?",
                ("sess_worker",),
            )
            return []

    request = AnalysisRefreshRequest(
        db_path="worker.sqlite",
        session_id="sess_worker",
        market_data=PublishedMarketData(3, frame),
        market_cursor=1,
        initial_equity=10_000.0,
        trade_notional=1_000.0,
        revision=9,
    )
    worker = AnalysisRefreshWorker(
        storage_factory=lambda _path: Storage(),
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
    )
    thread = QtCore.QThread()
    bridge = SimpleNamespace()

    class Emitter(QtCore.QObject):
        run = QtCore.Signal(object)

    bridge = Emitter()
    worker.moveToThread(thread)
    bridge.run.connect(worker.run, QtCore.Qt.QueuedConnection)
    worker.finished.connect(lambda result: (results.append(result), thread.quit()))
    worker.failed.connect(lambda _error: thread.quit())
    thread.finished.connect(loop.quit)
    thread.start()
    bridge.run.emit(request)
    QtCore.QTimer.singleShot(5_000, loop.quit)
    loop.exec()
    app.processEvents()

    assert len(results) == 1
    assert observed_thread_ids
    assert set(observed_thread_ids) != {main_thread_id}
    assert set(observed_thread_ids) == {results[0].preparation.worker_thread_id}
    assert results[0].preparation.market_generation == 3
