from __future__ import annotations

import pandas as pd

from time_series_analysis.baseline import build_random_bar_baseline, build_random_event_baseline, compare_events_to_baseline


def test_random_baseline_missing_label_skipped():
    result = build_random_event_baseline(pd.DataFrame({"x": [1, 2, 3]}), label_column="missing")
    assert result["skipped"] is True
    assert "missing label_column" in result["reason"]


def test_random_baseline_generates_distribution():
    df = pd.DataFrame({"fwd_ret_10_side_adj": [0.01, -0.02, 0.03, 0.0, 0.02] * 10})
    result = build_random_event_baseline(df, sample_size=10, n_iter=20, random_seed=1)
    assert result["skipped"] is False
    assert result["baseline_type"] == "event_label_resampling"
    assert result["sample_size"] == 10
    assert "baseline_q05" in result
    comparison = compare_events_to_baseline(df, result)
    assert comparison["event_sample_count"] == len(df)
    assert "event_mean_above_baseline_q95" in comparison
    assert "event label resampling" in comparison["interpretation_warning"]


def test_event_label_resampling_equal_sample_size_warns():
    df = pd.DataFrame({"fwd_ret_10_side_adj": [0.01, -0.02, 0.03]})
    result = build_random_event_baseline(df, sample_size=3, n_iter=5, random_seed=1)
    assert "sample_size equals available labels" in result["warning"]


def _klines(n=80):
    return pd.DataFrame(
        {
            "bar_index": range(n),
            "open_time_bjt": pd.date_range("2026-01-01", periods=n, freq="min").astype(str),
            "open": [100 + i * 0.1 for i in range(n)],
            "high": [101 + i * 0.1 for i in range(n)],
            "low": [99 + i * 0.1 for i in range(n)],
            "close": [100 + i * 0.2 for i in range(n)],
            "volume": [10 + (i % 5) for i in range(n)],
        }
    )


def test_random_bar_baseline_generates_result():
    result = build_random_bar_baseline(_klines(), horizon=5, sample_size=10, n_iter=20, min_start_index=10)
    assert result["skipped"] is False
    assert result["baseline_type"] == "random_bar_forward_return"
    assert result["sample_size"] == 10


def test_random_bar_baseline_skips_when_kline_too_short():
    result = build_random_bar_baseline(_klines(12), horizon=10, min_start_index=10)
    assert result["skipped"] is True
