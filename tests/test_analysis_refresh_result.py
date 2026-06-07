from __future__ import annotations

import pandas as pd

from services.analysis_refresh import AnalysisRefreshSnapshot, build_analysis_refresh_result


def test_build_analysis_refresh_result_combines_all_outputs():
    snapshot = AnalysisRefreshSnapshot(
        events=[{"event_id": "evt_1"}],
        features=[{"event_id": "evt_1", "pre_ret_20": 0.1}],
        trades=[{"trade_id": "trd_1"}],
        equity_rows=[{"sequence_no": 1}],
        initial_equity=10000.0,
    )

    result = build_analysis_refresh_result(
        snapshot,
        build_event_study_fn=lambda events, features: pd.DataFrame(
            [{"event_count": len(events), "feature_count": len(features)}]
        ),
        build_ml_datasets_fn=lambda features: {
            "ml_features": features[["event_id", "pre_ret_20"]],
            "ml_labels": pd.DataFrame({"event_id": features["event_id"]}),
            "sample_index": pd.DataFrame({"event_id": features["event_id"]}),
        },
        build_performance_summary_fn=lambda trades, equity, initial: {
            "total_trades": len(trades),
            "equity_rows": len(equity),
            "initial_equity": initial,
        },
        format_performance_report_fn=lambda summary: f"trades={summary['total_trades']}",
    )

    assert result.event_study.iloc[0]["event_count"] == 1
    assert result.performance_text == "trades=1"
    assert result.dataset_text
    assert result.warnings == ()


def test_build_analysis_refresh_result_collects_warnings_without_stopping_other_outputs():
    snapshot = AnalysisRefreshSnapshot(
        events=[],
        features=[],
        trades=[{"trade_id": "trd_1"}],
        equity_rows=[],
        initial_equity=10000.0,
    )

    result = build_analysis_refresh_result(
        snapshot,
        build_event_study_fn=lambda _events, _features: (_ for _ in ()).throw(RuntimeError("study boom")),
        build_ml_datasets_fn=lambda _features: (_ for _ in ()).throw(RuntimeError("dataset boom")),
        build_performance_summary_fn=lambda trades, _equity, _initial: {"total_trades": len(trades)},
        format_performance_report_fn=lambda summary: f"trades={summary['total_trades']}",
    )

    assert result.event_study.empty
    assert result.performance_text == "trades=1"
    assert len(result.warnings) == 2


def test_analysis_refresh_snapshot_materializes_iterables_for_reuse():
    snapshot = AnalysisRefreshSnapshot(
        events=({"event_id": "evt_1"} for _ in range(1)),
        features=({"event_id": "evt_1", "pre_ret_20": 0.1} for _ in range(1)),
        trades=({"trade_id": "trd_1"} for _ in range(1)),
        equity_rows=({"sequence_no": 1} for _ in range(1)),
        initial_equity=10000.0,
    )

    result = build_analysis_refresh_result(
        snapshot,
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
        format_performance_report_fn=lambda summary: (
            f"trades={summary['total_trades']}, equity={summary['equity_rows']}"
        ),
    )

    assert result.event_study.iloc[0]["feature_count"] == 1
    assert "特征表行/列" in result.dataset_text or "鐗瑰緛琛ㄨ" in result.dataset_text
    assert result.performance_text == "trades=1, equity=1"
