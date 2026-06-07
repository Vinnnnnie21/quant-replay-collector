from __future__ import annotations

import pytest
import pandas as pd

from services.analysis_refresh import (
    DeferredAnalysisRefresh,
    build_dataset_summary_text,
    build_event_study_summary_frame,
    build_performance_summary_text,
)


def test_deferred_analysis_refresh_schedules_only_once_while_pending():
    scheduled: list[tuple[int, object]] = []
    refresh = DeferredAnalysisRefresh(delay_ms=300)

    first = refresh.schedule(lambda delay, callback: scheduled.append((delay, callback)), lambda: None)
    second = refresh.schedule(lambda delay, callback: scheduled.append((delay, callback)), lambda: None)

    assert first is True
    assert second is False
    assert refresh.pending is True
    assert len(scheduled) == 1
    assert scheduled[0][0] == 300


def test_deferred_analysis_refresh_defers_pending_work_while_playing():
    scheduled: list[tuple[int, object]] = []
    refresh = DeferredAnalysisRefresh(delay_ms=300)
    refresh.schedule(lambda _delay, _callback: None, lambda: None)

    should_run = refresh.should_run(is_playing=True, is_running=False)
    deferred = refresh.defer(lambda delay, callback: scheduled.append((delay, callback)), lambda: None)

    assert should_run is False
    assert deferred is True
    assert refresh.pending is True
    assert scheduled == [(300, scheduled[0][1])]


def test_deferred_analysis_refresh_runs_pending_work_when_idle():
    refresh = DeferredAnalysisRefresh(delay_ms=300)
    refresh.schedule(lambda _delay, _callback: None, lambda: None)

    assert refresh.should_run(is_playing=False, is_running=False) is True
    assert refresh.should_run(is_playing=False, is_running=True) is False
    assert refresh.should_run(is_playing=True, is_running=False) is False


def test_deferred_analysis_refresh_runs_tasks_in_order_and_clears_pending():
    calls: list[str] = []
    refresh = DeferredAnalysisRefresh(delay_ms=300)
    refresh.schedule(lambda _delay, _callback: None, lambda: None)

    refresh.run(
        [
            lambda: calls.append("event_study"),
            lambda: calls.append("dataset_summary"),
            lambda: calls.append("performance_summary"),
        ]
    )

    assert calls == ["event_study", "dataset_summary", "performance_summary"]
    assert refresh.pending is False


def test_deferred_analysis_refresh_clears_pending_when_task_raises():
    refresh = DeferredAnalysisRefresh(delay_ms=300)
    refresh.schedule(lambda _delay, _callback: None, lambda: None)

    with pytest.raises(RuntimeError, match="boom"):
        refresh.run([lambda: (_ for _ in ()).throw(RuntimeError("boom"))])

    assert refresh.pending is False


def test_build_dataset_summary_text_reports_feature_label_separation():
    features = pd.DataFrame(
        [
            {
                "event_id": "evt_1",
                "session_id": "sess_1",
                "pre_ret_20": 0.1,
                "fwd_ret_1": 0.2,
                "mfe_10": 0.3,
            }
        ]
    )

    text, warning = build_dataset_summary_text(features)

    assert warning is None
    assert "当前会话事件特征行数: 1" in text
    assert "特征表行/列:" in text
    assert "标签表行/列:" in text
    assert "已隔离未来/结果字段" in text


def test_build_dataset_summary_text_returns_warning_on_failure():
    def broken_builder(_features):
        raise RuntimeError("dataset boom")

    text, warning = build_dataset_summary_text(pd.DataFrame(), build_ml_datasets_fn=broken_builder)

    assert "机器学习样本摘要生成失败：RuntimeError: dataset boom" == text
    assert warning == text


def test_build_event_study_summary_frame_uses_dataframe_inputs():
    def builder(events, features):
        assert list(events.columns) == ["event_id"]
        assert list(features.columns) == ["event_id", "pre_ret_20"]
        return pd.DataFrame([{"label_tag": "wick", "sample_count": 1}])

    summary, warning = build_event_study_summary_frame(
        [{"event_id": "evt_1"}],
        [{"event_id": "evt_1", "pre_ret_20": 0.1}],
        build_summary_fn=builder,
    )

    assert warning is None
    assert summary.iloc[0]["label_tag"] == "wick"


def test_build_event_study_summary_frame_returns_empty_frame_on_failure():
    def broken_builder(_events, _features):
        raise RuntimeError("study boom")

    summary, warning = build_event_study_summary_frame([], [], build_summary_fn=broken_builder)

    assert summary.empty
    assert warning == "事件研究统计失败：RuntimeError: study boom"


def test_build_performance_summary_text_uses_summary_and_formatter():
    text, warning = build_performance_summary_text(
        trades=[{"trade_id": "trd_1"}],
        equity_rows=[{"sequence_no": 1}],
        initial_equity=10000.0,
        build_summary_fn=lambda trades, equity, initial: {
            "total_trades": len(trades),
            "equity_rows": len(equity),
            "initial_equity": initial,
        },
        format_report_fn=lambda summary: f"trades={summary['total_trades']}, equity={summary['equity_rows']}",
    )

    assert text == "trades=1, equity=1"
    assert warning is None


def test_build_performance_summary_text_returns_warning_on_failure():
    def broken_summary(_trades, _equity, _initial):
        raise RuntimeError("perf boom")

    text, warning = build_performance_summary_text([], [], 10000.0, build_summary_fn=broken_summary)

    assert text == "统计生成失败：RuntimeError: perf boom"
    assert warning == "交易绩效统计生成失败：RuntimeError: perf boom"
