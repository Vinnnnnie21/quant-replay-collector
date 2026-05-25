from __future__ import annotations

import math

import pandas as pd

from time_series_analysis.returns import annualized_log_return, annualized_return, build_event_window_return_series, build_return_series, cumulative_log_return, log_return, simple_return, summarize_return_distribution


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


def test_build_return_series_empty_safe():
    out = build_return_series(pd.DataFrame())
    assert out.empty
    assert "simple_return" in out.columns


def test_simple_and_log_return_calculation():
    close = pd.Series([100.0, 101.0, 99.0])
    assert abs(simple_return(close).iloc[1] - 0.01) < 1e-12
    assert abs(log_return(close).iloc[1] - 0.009950330853168092) < 1e-12


def test_annualized_return_distinguishes_log_and_simple_compounding():
    values = pd.Series([0.001, 0.002, -0.0005])
    annual_log = annualized_log_return(values, periods_per_year=12)
    annual_simple = annualized_return(values, periods_per_year=12)
    assert annual_log == values.mean() * 12
    assert abs(annual_simple - math.expm1(annual_log)) < 1e-12
    assert annual_simple != annual_log
    assert abs(annual_simple - annual_log) < 0.001


def test_cumulative_log_return_is_cumulative_sum():
    values = pd.Series([0.01, -0.02, 0.03])
    result = cumulative_log_return(values)
    assert abs(result.iloc[-1] - values.sum()) < 1e-12


def test_annualized_simple_return_is_safe_when_exponential_overflows():
    assert annualized_return(pd.Series([1.0]), periods_per_year=1000) is None


def test_build_return_series_outputs_required_columns():
    out = build_return_series(_klines())
    for col in [
        "simple_return",
        "log_return",
        "rolling_return_20",
        "rolling_volatility_20",
        "realized_volatility_20",
        "close_position",
        "volume_zscore_20",
        "return_zscore_20",
    ]:
        assert col in out.columns


def test_summarize_return_distribution_outputs_autocorr():
    out = build_return_series(_klines())
    summary = summarize_return_distribution(out)
    assert summary["sample_count"] > 0
    assert "autocorr_lag_1" in summary
    assert "squared_return_autocorr_lag_5" in summary


def test_constant_returns_have_no_undefined_autocorrelation():
    summary = summarize_return_distribution(pd.DataFrame({"simple_return": [0.0] * 20}))
    assert summary["autocorr_lag_1"] is None
    assert summary["squared_return_autocorr_lag_1"] is None


def test_event_window_return_series_does_not_cross_windows():
    windows = pd.DataFrame(
        [
            {"event_id": "e1", "offset": 0, "bar_index": 100, "bar_open_time_bjt": "2026-01-01T00:00:00+08:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10},
            {"event_id": "e1", "offset": 1, "bar_index": 101, "bar_open_time_bjt": "2026-01-01T00:01:00+08:00", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 11},
            {"event_id": "e1", "offset": 2, "bar_index": 102, "bar_open_time_bjt": "2026-01-01T00:02:00+08:00", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 12},
            {"event_id": "e2", "offset": 0, "bar_index": 800, "bar_open_time_bjt": "2026-01-02T00:00:00+08:00", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 20},
            {"event_id": "e2", "offset": 1, "bar_index": 801, "bar_open_time_bjt": "2026-01-02T00:01:00+08:00", "open": 200, "high": 202, "low": 199, "close": 202, "volume": 21},
            {"event_id": "e2", "offset": 2, "bar_index": 802, "bar_open_time_bjt": "2026-01-02T00:02:00+08:00", "open": 202, "high": 203, "low": 201, "close": 203, "volume": 22},
        ]
    )
    out = build_event_window_return_series(windows)
    e1 = out[out["event_id"] == "e1"].reset_index(drop=True)
    e2 = out[out["event_id"] == "e2"].reset_index(drop=True)

    assert e1.loc[0, "is_segment_start"] is True or bool(e1.loc[0, "is_segment_start"]) is True
    assert e2.loc[0, "is_segment_start"] is True or bool(e2.loc[0, "is_segment_start"]) is True
    assert pd.isna(e1.loc[0, "simple_return"])
    assert pd.isna(e2.loc[0, "simple_return"])
    assert e2.loc[1, "simple_return"] == 202 / 200 - 1
    assert "source" in out.columns
    assert set(out["source"]) == {"event_windows_only"}
    assert "segment_id" in out.columns
    assert "event_id" in out.columns


def test_event_window_return_series_segments_by_bar_gap_without_event_id():
    windows = pd.DataFrame(
        {
            "bar_index": [1, 2, 10, 11],
            "bar_open_time_bjt": ["a", "b", "c", "d"],
            "open": [10, 11, 20, 21],
            "high": [11, 12, 21, 22],
            "low": [9, 10, 19, 20],
            "close": [10, 11, 20, 22],
            "volume": [1, 1, 1, 1],
        }
    )
    out = build_event_window_return_series(windows)
    row_10 = out[out["bar_index"] == 10].iloc[0]
    assert bool(row_10["is_segment_start"]) is True
    assert pd.isna(row_10["simple_return"])
    assert pd.isna(row_10["rolling_return_5"])
