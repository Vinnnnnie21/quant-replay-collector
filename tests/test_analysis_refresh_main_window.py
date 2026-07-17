from __future__ import annotations

import threading
from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

import main_app
from main_app import MainWindow
from services.analysis_refresh import (
    AnalysisRefreshRequest,
    AnalysisRefreshResult,
    PerformanceWorkspacePayload,
    PublishedMarketData,
    prepare_analysis_refresh_snapshot,
)


def test_main_window_builds_lightweight_analysis_request_from_current_state():
    window = SimpleNamespace(
        df=pd.DataFrame(),
        cursor=0,
        session_id="sess_1",
        storage=SimpleNamespace(db_path="analysis.sqlite"),
        initialEquitySpin=SimpleNamespace(value=lambda: 10000.0),
        tradeNotionalSpin=SimpleNamespace(value=lambda: 500.0),
    )

    request = MainWindow._analysis_refresh_request(window)

    assert request.session_id == "sess_1"
    assert request.db_path == "analysis.sqlite"
    assert request.market_data is None
    assert request.trade_notional == 500.0


def test_worker_private_analysis_snapshot_owns_required_market_columns():
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
    request = AnalysisRefreshRequest(
        db_path="",
        session_id="sess_large",
        market_data=PublishedMarketData(1, frame),
        market_cursor=len(frame) - 1,
        initial_equity=10_000.0,
        trade_notional=1_000.0,
    )

    snapshot, _preparation = prepare_analysis_refresh_snapshot(request)

    assert snapshot.market_frame is not frame
    assert list(snapshot.market_frame.columns) == [
        "bar_index",
        "open_time_bjt",
        "close",
    ]
    frame.loc[0, "close"] = 999.0
    assert snapshot.market_frame.loc[0, "close"] == 100.0
    assert snapshot.market_cursor == len(frame) - 1
    assert snapshot.equity_rows == ()
    assert snapshot.trade_notional == 1000.0


def test_main_window_analysis_request_is_lightweight_and_defers_storage_reads():
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
    storage = SimpleNamespace(
        db_path="analysis.sqlite",
        fetch_table=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("analysis request construction must not query SQLite")
        ),
    )
    window = SimpleNamespace(
        df=frame,
        cursor=len(frame) - 1,
        session_id="sess_large",
        storage=storage,
        _market_data_generation=7,
        initialEquitySpin=SimpleNamespace(value=lambda: 10_000.0),
        tradeNotionalSpin=SimpleNamespace(value=lambda: 1_000.0),
    )

    request = MainWindow._analysis_refresh_request(window)

    assert request.market_data.frame is frame
    assert request.market_data.generation == 7
    assert request.session_id == "sess_large"
    assert request.db_path == "analysis.sqlite"
    assert request.ui_thread_id == threading.get_ident()
    assert request.ui_input_capture_seconds < 0.1


def test_main_window_applies_completed_analysis_result_to_widgets(monkeypatch):
    populated: list[pd.DataFrame] = []
    equity_values: list[tuple[dict, ...]] = []
    dataset_values: list[str] = []
    performance_values: list[str] = []
    logs: list[str] = []
    monkeypatch.setattr(
        main_app,
        "populate_event_study_table",
        lambda _table, frame: populated.append(frame),
    )
    monkeypatch.setattr(
        main_app,
        "populate_equity_table",
        lambda _table, rows: equity_values.append(tuple(rows)),
    )
    window = SimpleNamespace(
        eventStudyTable=object(),
        equityTable=object(),
        datasetText=SimpleNamespace(setPlainText=dataset_values.append),
        performanceText=SimpleNamespace(setPlainText=performance_values.append),
        _log=logs.append,
    )
    result = AnalysisRefreshResult(
        event_study=pd.DataFrame([{"sample_count": 1}]),
        dataset_text="dataset",
        performance_text="performance",
        warnings=("warning",),
        equity_rows=({"bar_index": 0}, {"bar_index": 2}),
        equity_total_rows=3,
    )

    MainWindow._apply_analysis_refresh_result(window, result)

    assert populated[0].iloc[0]["sample_count"] == 1
    assert equity_values == [({"bar_index": 0}, {"bar_index": 2})]
    assert dataset_values == ["dataset"]
    assert performance_values == ["performance"]
    assert logs == ["warning"]


def test_default_table_refresh_defers_all_heavy_analysis_to_worker(monkeypatch):
    class FakeTable:
        def blockSignals(self, _blocked):
            return False

        def clearSelection(self):
            pass

        def setCurrentCell(self, _row, _column):
            pass

    populate_modes: list[bool] = []
    scheduled: list[bool] = []

    def populate_tables(*, include_heavy=True):
        populate_modes.append(include_heavy)

    window = SimpleNamespace(
        openTradesTable=FakeTable(),
        closedTradesTable=FakeTable(),
        eventTable=FakeTable(),
        equityTable=FakeTable(),
        eventStudyTable=FakeTable(),
        _populate_tables=populate_tables,
        _refresh_performance_summary=lambda: (_ for _ in ()).throw(
            AssertionError("performance calculation must not run on the UI thread")
        ),
        analysis_refresh_controller=SimpleNamespace(schedule=lambda: scheduled.append(True)),
    )
    monkeypatch.setattr(main_app, "_maybe_log_slow_operation", lambda *_args: None)

    MainWindow._refresh_tables(window)

    assert populate_modes == [False]
    assert scheduled == [True]


def test_main_window_analysis_failure_only_logs_error():
    logs: list[str] = []
    window = SimpleNamespace(_log=logs.append)

    MainWindow._on_analysis_refresh_failed(window, "worker boom")

    assert logs == ["Analysis refresh failed: worker boom"]


def test_main_window_forwards_completed_performance_payload_to_open_workspace(monkeypatch):
    monkeypatch.setattr(main_app, "populate_event_study_table", lambda *_args: None)
    monkeypatch.setattr(main_app, "populate_equity_table", lambda *_args: None)
    applied: list[PerformanceWorkspacePayload] = []
    payload = PerformanceWorkspacePayload(
        equity_rows=(),
        equity_total_rows=0,
        metrics={},
        distribution={},
        equity_values=(),
        pnl_values=(),
        trades=(),
        closed_pnls=(),
        initial_equity=10_000.0,
        default_notional=1_000.0,
    )
    window = SimpleNamespace(
        eventStudyTable=object(),
        equityTable=object(),
        datasetText=SimpleNamespace(setPlainText=lambda _text: None),
        performanceText=SimpleNamespace(setPlainText=lambda _text: None),
        _analysis_workspace=SimpleNamespace(apply_performance_payload=applied.append),
        _log=lambda _message: None,
    )

    MainWindow._apply_analysis_refresh_result(
        window,
        AnalysisRefreshResult(
            event_study=pd.DataFrame(),
            dataset_text="dataset",
            performance_text="performance",
            performance_workspace=payload,
        ),
    )

    assert applied == [payload]
