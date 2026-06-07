from __future__ import annotations

import pandas as pd
import pytest

from backtesting.date_range import BacktestDateRange, slice_backtest_date_range


def _df(times=None):
    if times is None:
        times = pd.date_range("2026-01-01 09:00", periods=10, freq="min", tz="Asia/Shanghai")
    return pd.DataFrame(
        {
            "bar_index": range(len(times)),
            "open_time_bjt": times,
            "open": [100.0] * len(times),
            "high": [101.0] * len(times),
            "low": [99.0] * len(times),
            "close": [100.0] * len(times),
            "volume": [100.0] * len(times),
        }
    )


def test_date_range_filters_on_open_time_with_half_open_end():
    result = slice_backtest_date_range(
        _df(),
        BacktestDateRange("BTCUSDT", "1m", "2026-01-01 09:02+08:00", "2026-01-01 09:05+08:00"),
        minimum_bars=3,
    )

    assert result.status == "ready"
    assert result.data["bar_index"].tolist() == [2, 3, 4]


def test_date_range_rejects_invalid_empty_and_too_short_ranges():
    with pytest.raises(ValueError, match="start"):
        BacktestDateRange("BTCUSDT", "1m", "2026-01-01 09:05", "2026-01-01 09:05").validate()

    gapped = _df(
        [
            pd.Timestamp("2026-01-01 09:00", tz="Asia/Shanghai"),
            pd.Timestamp("2026-01-01 10:00", tz="Asia/Shanghai"),
        ]
    )
    with pytest.raises(ValueError, match="no K-line data"):
        slice_backtest_date_range(
            gapped,
            BacktestDateRange("BTCUSDT", "1m", "2026-01-01 09:20", "2026-01-01 09:40"),
        )

    with pytest.raises(ValueError, match="insufficient bars"):
        slice_backtest_date_range(
            _df(),
            BacktestDateRange("BTCUSDT", "1m", "2026-01-01 09:02", "2026-01-01 09:05"),
            minimum_bars=4,
        )


def test_date_range_reports_when_current_data_does_not_cover_request():
    result = slice_backtest_date_range(
        _df(),
        BacktestDateRange("BTCUSDT", "1m", "2025-12-31 23:00+08:00", "2026-01-01 09:05+08:00"),
    )

    assert result.status == "needs_market_data"
    assert result.data.empty
    assert "does not cover" in result.message


def test_date_range_treats_last_bar_close_boundary_as_covered():
    result = slice_backtest_date_range(
        _df(),
        BacktestDateRange("BTCUSDT", "1m", "2026-01-01 09:07+08:00", "2026-01-01 09:10+08:00"),
        minimum_bars=3,
    )

    assert result.status == "ready"
    assert result.data["bar_index"].tolist() == [7, 8, 9]


def test_date_range_normalizes_naive_bjt_and_timezone_aware_inputs():
    naive = _df(pd.date_range("2026-01-01 09:00", periods=10, freq="min"))
    result = slice_backtest_date_range(
        naive,
        BacktestDateRange(
            "BTCUSDT",
            "1m",
            pd.Timestamp("2026-01-01 01:02", tz="UTC"),
            pd.Timestamp("2026-01-01 01:05", tz="UTC"),
        ),
        minimum_bars=3,
    )

    assert result.status == "ready"
    assert result.data["bar_index"].tolist() == [2, 3, 4]
