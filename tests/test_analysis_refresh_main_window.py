from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

import main_app
from main_app import MainWindow
from services.analysis_refresh import AnalysisRefreshResult


def test_main_window_builds_analysis_snapshot_from_current_state():
    window = SimpleNamespace(
        trades=[{"trade_id": "trd_1"}],
        _event_rows_for_study=lambda: [{"event_id": "evt_1"}],
        _feature_rows_for_session=lambda: [{"event_id": "evt_1", "pre_ret_20": 0.1}],
        _current_equity_rows=lambda: [{"sequence_no": 1}],
        initialEquitySpin=SimpleNamespace(value=lambda: 10000.0),
    )

    snapshot = MainWindow._analysis_refresh_snapshot(window)

    assert snapshot.events == ({"event_id": "evt_1"},)
    assert snapshot.features == ({"event_id": "evt_1", "pre_ret_20": 0.1},)
    assert snapshot.trades == ({"trade_id": "trd_1"},)
    assert snapshot.equity_rows == ({"sequence_no": 1},)


def test_main_window_applies_completed_analysis_result_to_widgets(monkeypatch):
    populated: list[pd.DataFrame] = []
    dataset_values: list[str] = []
    performance_values: list[str] = []
    logs: list[str] = []
    monkeypatch.setattr(
        main_app,
        "populate_event_study_table",
        lambda _table, frame: populated.append(frame),
    )
    window = SimpleNamespace(
        eventStudyTable=object(),
        datasetText=SimpleNamespace(setPlainText=dataset_values.append),
        performanceText=SimpleNamespace(setPlainText=performance_values.append),
        _log=logs.append,
    )
    result = AnalysisRefreshResult(
        event_study=pd.DataFrame([{"sample_count": 1}]),
        dataset_text="dataset",
        performance_text="performance",
        warnings=("warning",),
    )

    MainWindow._apply_analysis_refresh_result(window, result)

    assert populated[0].iloc[0]["sample_count"] == 1
    assert dataset_values == ["dataset"]
    assert performance_values == ["performance"]
    assert logs == ["warning"]


def test_main_window_analysis_failure_only_logs_error():
    logs: list[str] = []
    window = SimpleNamespace(_log=logs.append)

    MainWindow._on_analysis_refresh_failed(window, "worker boom")

    assert logs == ["Analysis refresh failed: worker boom"]
