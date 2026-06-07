from __future__ import annotations

import pandas as pd
import pytest

QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from services.analysis_refresh import AnalysisRefreshResult, AnalysisRefreshSnapshot
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
