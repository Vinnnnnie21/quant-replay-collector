from __future__ import annotations

import pandas as pd

from multi_timeframe import find_context_bar_by_time


def _htf_frame(freq: str, periods: int = 4) -> pd.DataFrame:
    open_times = pd.date_range("2026-05-27 09:00:00", periods=periods, freq=freq, tz="Asia/Shanghai")
    delta = pd.to_timedelta(freq)
    return pd.DataFrame(
        {
            "bar_index": range(periods),
            "open_time_bjt": open_times,
            "close_time_bjt": open_times + delta,
            "close": [100.0 + index for index in range(periods)],
        }
    )


def test_current_minute_matches_containing_five_minute_bar():
    match = find_context_bar_by_time(_htf_frame("5min"), pd.Timestamp("2026-05-27 09:07:00", tz="Asia/Shanghai"))

    assert match["sync_status"] == "contains_cursor"
    assert match["htf_bar_index"] == 1


def test_current_minute_matches_containing_fifteen_minute_bar():
    match = find_context_bar_by_time(_htf_frame("15min"), pd.Timestamp("2026-05-27 09:17:00", tz="Asia/Shanghai"))

    assert match["sync_status"] == "contains_cursor"
    assert match["htf_bar_index"] == 1


def test_open_boundary_matches_new_htf_bar_and_close_boundary_moves_forward():
    frame = _htf_frame("5min")

    at_open = find_context_bar_by_time(frame, pd.Timestamp("2026-05-27 09:05:00", tz="Asia/Shanghai"))
    at_close = find_context_bar_by_time(frame, pd.Timestamp("2026-05-27 09:10:00", tz="Asia/Shanghai"))

    assert at_open["htf_bar_index"] == 1
    assert at_close["htf_bar_index"] == 2


def test_no_available_htf_bar_returns_sync_status_instead_of_error():
    match = find_context_bar_by_time(_htf_frame("5min"), pd.Timestamp("2026-05-27 08:59:00", tz="Asia/Shanghai"))

    assert match["sync_status"] == "unavailable_before_cursor"
    assert match["htf_bar_index"] is None
