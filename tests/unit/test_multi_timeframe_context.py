from __future__ import annotations

import pandas as pd

from multi_timeframe import build_multi_timeframe_context, higher_timeframes_for


def _htf_frame(freq: str = "5min", periods: int = 30) -> pd.DataFrame:
    times = pd.date_range("2026-05-27 09:00:00", periods=periods, freq=freq, tz="Asia/Shanghai")
    delta = pd.to_timedelta(freq)
    return pd.DataFrame(
        {
            "bar_index": range(periods),
            "open_time_bjt": times,
            "close_time_bjt": times + delta,
            "open": [100 + index * 0.2 for index in range(periods)],
            "high": [101 + index * 0.2 for index in range(periods)],
            "low": [99 + index * 0.2 for index in range(periods)],
            "close": [100.5 + index * 0.2 for index in range(periods)],
            "volume": [1000 + index for index in range(periods)],
        }
    )


def _primary_row(timestamp: str) -> dict:
    return {"open_time_bjt": pd.Timestamp(timestamp, tz="Asia/Shanghai")}


def test_default_context_intervals_follow_primary_interval():
    assert higher_timeframes_for("1m") == ("5m", "15m")
    assert higher_timeframes_for("5m") == ("15m", "1h")
    assert higher_timeframes_for("15m") == ("1h", "4h")


def test_context_uses_only_completed_htf_bars_when_containing_bar_is_still_open():
    original = _htf_frame()
    changed_future = original.copy()
    changed_future.loc[22:, ["high", "low", "close", "volume"]] = [9000, 0.1, 8000, 999999]
    primary = _primary_row("2026-05-27 10:52:00")

    first = build_multi_timeframe_context(primary, {"5m": original})
    second = build_multi_timeframe_context(primary, {"5m": changed_future})

    assert first["5m"]["containing_htf_bar_index"] == 22
    assert first["5m"]["htf_bar_index"] == 21
    assert first["5m"]["sync_status"] == "previous_completed_for_no_future"
    comparable = ["close", "pre_simple_ret_20", "realized_vol_20", "trend_regime", "volatility_regime"]
    assert {key: first["5m"][key] for key in comparable} == {key: second["5m"][key] for key in comparable}


def test_context_returns_state_summary_for_each_loaded_interval_without_signal_fields():
    result = build_multi_timeframe_context(
        _primary_row("2026-05-27 11:07:00"),
        {"5m": _htf_frame("5min"), "15m": _htf_frame("15min")},
    )

    assert set(result) == {"5m", "15m"}
    assert result["5m"]["htf_interval"] == "5m"
    assert "pre_simple_ret_20" in result["5m"]
    assert "realized_vol_20" in result["5m"]
    assert not {"trading_signal", "fwd_ret", "future_return", "pnl"} & set(result["5m"])


def test_insufficient_htf_history_is_explicit():
    result = build_multi_timeframe_context(
        _primary_row("2026-05-27 09:32:00"),
        {"5m": _htf_frame(periods=8)},
    )

    assert result["5m"]["history_status"] == "insufficient_history"
    assert result["5m"]["available_bars"] < 20
    assert result["5m"]["pre_simple_ret_20"] is None
