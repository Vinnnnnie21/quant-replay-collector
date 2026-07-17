from __future__ import annotations

import pandas as pd
import pytest

from services.analysis_refresh import AnalysisRefreshSnapshot, build_analysis_refresh_result


def test_analysis_refresh_result_preserves_snapshot_revision():
    snapshot = AnalysisRefreshSnapshot(
        events=[],
        features=[],
        trades=[],
        equity_rows=[],
        initial_equity=10_000.0,
        revision=7,
    )

    result = build_analysis_refresh_result(
        snapshot,
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda _trades, _equity, _initial: {},
        format_performance_report_fn=lambda _summary: "ok",
    )

    assert result.revision == 7


def test_analysis_refresh_builds_trade_equity_in_worker_when_market_frame_is_absent():
    snapshot = AnalysisRefreshSnapshot(
        events=[],
        features=[],
        trades=[
            {
                "trade_id": "trd_closed",
                "status": "CLOSED",
                "net_pnl_quote": 20.0,
                "updated_at": "2026-01-01T00:01:00+08:00",
            }
        ],
        equity_rows=[],
        initial_equity=1_000.0,
        session_id="sess_no_market",
        trade_notional=500.0,
    )

    result = build_analysis_refresh_result(
        snapshot,
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda _trades, equity, _initial: {
            "last_equity": equity[-1]["equity_after"],
        },
        format_performance_report_fn=lambda summary: f"equity={summary['last_equity']}",
    )

    assert result.performance_text == "equity=1020.0"
    assert result.performance_workspace.metrics["total_pnl"] == 20.0


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


def test_analysis_refresh_builds_continuous_equity_from_market_frame_in_worker_path():
    market_frame = pd.DataFrame(
        {
            "bar_index": [0, 1, 2, 3],
            "open_time_bjt": pd.date_range(
                "2026-01-01",
                periods=4,
                freq="min",
                tz="Asia/Shanghai",
            ),
            "close": [100.0, 101.0, 102.0, 103.0],
        }
    )
    snapshot = AnalysisRefreshSnapshot(
        events=[],
        features=[],
        trades=[],
        equity_rows=[],
        initial_equity=10_000.0,
        market_frame=market_frame,
        market_cursor=2,
        session_id="sess_worker",
        trade_notional=1_000.0,
    )

    result = build_analysis_refresh_result(
        snapshot,
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda _trades, equity, _initial: {
            "equity_rows": len(equity),
            "last_bar_index": equity[-1]["bar_index"],
        },
        format_performance_report_fn=lambda summary: (
            f"equity={summary['equity_rows']}, last={summary['last_bar_index']}"
        ),
    )

    assert result.performance_text == "equity=3, last=2"


def test_analysis_refresh_limits_only_ui_equity_handoff_not_performance_input():
    equity_rows = [
        {"bar_index": index, "equity": 10_000.0 + index, "drawdown": 0.0}
        for index in range(3_001)
    ]
    snapshot = AnalysisRefreshSnapshot(
        events=[],
        features=[],
        trades=[],
        equity_rows=equity_rows,
        initial_equity=10_000.0,
    )

    result = build_analysis_refresh_result(
        snapshot,
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda _trades, rows, _initial: {
            "equity_rows": len(rows),
        },
        format_performance_report_fn=lambda summary: f"equity={summary['equity_rows']}",
    )

    assert result.performance_text == "equity=3001"
    assert result.equity_total_rows == 3_001
    assert len(result.equity_rows) == 2_000
    assert result.equity_rows[0]["bar_index"] == 0
    assert result.equity_rows[-1]["bar_index"] == 3_000


def test_analysis_refresh_builds_workspace_performance_payload_from_full_result():
    equity_rows = [
        {
            "bar_index": 0,
            "time": "2026-01-01T00:00:00+08:00",
            "current_equity": 1_000.0,
            "realized_net_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "open_position_count": 0,
        },
        {
            "bar_index": 1,
            "time": "2026-01-01T00:01:00+08:00",
            "current_equity": 1_040.0,
            "realized_net_pnl": 20.0,
            "unrealized_pnl": 20.0,
            "open_position_count": 1,
        },
    ]
    trades = [
        {
            "trade_id": "trd_win",
            "side": "LONG",
            "status": "CLOSED",
            "net_return_pct": 2.0,
            "net_pnl_quote": 20.0,
            "exit_bar_index": 1,
        },
        {
            "trade_id": "trd_open",
            "side": "LONG",
            "status": "OPEN",
            "entry_bar_index": 1,
            "entry_fill_price": 100.0,
            "notional_quote": 500.0,
        },
    ]
    result = build_analysis_refresh_result(
        AnalysisRefreshSnapshot(
            events=[],
            features=[],
            trades=trades,
            equity_rows=equity_rows,
            initial_equity=1_000.0,
            trade_notional=500.0,
        ),
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda _trades, _equity, _initial: {},
        format_performance_report_fn=lambda _summary: "ok",
    )

    payload = result.performance_workspace
    assert payload.metrics["total_return_pct"] == 4.0
    assert payload.metrics["total_pnl"] == 40.0
    assert payload.metrics["unrealized_pnl"] == 20.0
    assert payload.equity_values == (1_000.0, 1_040.0)
    assert payload.pnl_values == (0.0, 40.0)
    assert [trade["trade_id"] for trade in payload.trades] == ["trd_win", "trd_open"]
    assert payload.closed_pnls == (20.0,)

    with pytest.raises(TypeError):
        payload.metrics["total_pnl"] = -1.0
    with pytest.raises(TypeError):
        payload.trades[0]["trade_id"] = "mutated"


def test_analysis_refresh_progress_uses_snapshot_language():
    progress_messages: list[str] = []
    snapshot = AnalysisRefreshSnapshot(
        events=[],
        features=[],
        trades=[],
        equity_rows=[],
        initial_equity=10_000.0,
        language="zh_CN",
    )

    build_analysis_refresh_result(
        snapshot,
        build_event_study_fn=lambda _events, _features: pd.DataFrame(),
        build_ml_datasets_fn=lambda _features: {
            "ml_features": pd.DataFrame(),
            "ml_labels": pd.DataFrame(),
            "sample_index": pd.DataFrame(),
        },
        build_performance_summary_fn=lambda *_args: {},
        format_performance_report_fn=lambda _summary: "",
        progress=progress_messages.append,
    )

    assert progress_messages == ["正在准备事件研究…", "正在准备研究样本…", "正在计算绩效统计…"]
