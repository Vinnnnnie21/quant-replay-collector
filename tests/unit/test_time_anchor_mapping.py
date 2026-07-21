from __future__ import annotations

import pandas as pd

from timeframe_switcher import (
    build_time_centered_xrange,
    capture_time_anchor,
    capture_view_time_span,
    find_bar_index_by_time,
)


def _frame(freq: str, periods: int = 20, close_time: bool = True) -> pd.DataFrame:
    opens = pd.date_range("2026-05-27 10:00:00", periods=periods, freq=freq, tz="Asia/Shanghai")
    frame = pd.DataFrame({"bar_index": range(periods), "open_time_bjt": opens, "close": range(periods)})
    if close_time:
        frame["close_time_bjt"] = opens + pd.to_timedelta(freq)
    return frame


def test_one_minute_anchor_maps_to_containing_five_minute_bar():
    assert find_bar_index_by_time(_frame("5min"), pd.Timestamp("2026-05-27 10:37:00", tz="Asia/Shanghai"), "5m") == 7


def test_anchor_on_fifteen_minute_open_maps_to_new_bar():
    assert find_bar_index_by_time(_frame("15min"), pd.Timestamp("2026-05-27 10:45:00", tz="Asia/Shanghai"), "15m") == 3


def test_anchor_on_close_boundary_maps_to_next_bar():
    assert find_bar_index_by_time(_frame("5min"), pd.Timestamp("2026-05-27 10:10:00", tz="Asia/Shanghai"), "5m") == 2


def test_anchor_before_or_after_available_range_clamps_to_edge():
    frame = _frame("5min", periods=4)

    assert find_bar_index_by_time(frame, pd.Timestamp("2026-05-27 09:00:00", tz="Asia/Shanghai"), "5m") == 0
    assert find_bar_index_by_time(frame, pd.Timestamp("2026-05-27 12:00:00", tz="Asia/Shanghai"), "5m") == 3


def test_close_time_can_be_inferred_from_interval():
    assert find_bar_index_by_time(
        _frame("5min", close_time=False),
        pd.Timestamp("2026-05-27 10:37:00", tz="Asia/Shanghai"),
        "5m",
    ) == 7


def test_anchor_and_view_span_preserve_market_time_not_old_bar_count():
    minute_frame = _frame("1min", periods=121)
    five_minute_frame = _frame("5min", periods=30)

    anchor = capture_time_anchor(minute_frame, 75)
    span_seconds = capture_view_time_span(minute_frame, (45.0, 105.0))
    centered = build_time_centered_xrange(five_minute_frame, 15, span_seconds)

    assert anchor == pd.Timestamp("2026-05-27 11:15:00", tz="Asia/Shanghai")
    assert span_seconds == 3600.0
    assert centered is not None
    assert centered[1] - centered[0] < 20

