"""Timestamp-based helpers for switching the displayed replay timeframe."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from market_data import interval_to_ms


def normalize_bjt_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("Asia/Shanghai")
    return timestamp.tz_convert("Asia/Shanghai")


def _normalized_times(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty or "open_time_bjt" not in df.columns:
        return pd.DataFrame()
    frame = df.copy().reset_index(drop=True)
    frame["_open_time"] = frame["open_time_bjt"].map(normalize_bjt_timestamp)
    frame = frame.dropna(subset=["_open_time"]).sort_values("_open_time", kind="stable").reset_index(drop=True)
    if frame.empty:
        return frame
    if "close_time_bjt" in frame.columns:
        frame["_close_time"] = frame["close_time_bjt"].map(normalize_bjt_timestamp)
    else:
        frame["_close_time"] = frame["_open_time"] + pd.Timedelta(milliseconds=interval_to_ms(interval))
    missing_close = frame["_close_time"].isna()
    if missing_close.any():
        frame.loc[missing_close, "_close_time"] = (
            frame.loc[missing_close, "_open_time"] + pd.Timedelta(milliseconds=interval_to_ms(interval))
        )
    return frame


def find_bar_index_by_time(df: pd.DataFrame, anchor_time_bjt: Any, interval: str) -> int:
    """Return the displayed positional index that contains or precedes an anchor time."""
    frame = _normalized_times(df, interval)
    if frame.empty:
        return 0
    anchor = normalize_bjt_timestamp(anchor_time_bjt)
    if anchor is None:
        return 0
    containing = frame[(frame["_open_time"] <= anchor) & (anchor < frame["_close_time"])]
    if not containing.empty:
        return int(containing.index[-1])
    prior = frame[frame["_open_time"] <= anchor]
    if not prior.empty:
        return int(prior.index[-1])
    return 0


def capture_time_anchor(df: pd.DataFrame, cursor: int) -> pd.Timestamp | None:
    if not isinstance(df, pd.DataFrame) or df.empty or "open_time_bjt" not in df.columns:
        return None
    index = max(0, min(int(cursor), len(df) - 1))
    return normalize_bjt_timestamp(df.iloc[index]["open_time_bjt"])


def capture_view_time_span(df: pd.DataFrame, manual_xrange: tuple[float, float] | None) -> float | None:
    if not isinstance(df, pd.DataFrame) or df.empty or not manual_xrange or "open_time_bjt" not in df.columns:
        return None
    try:
        x0, x1 = float(manual_xrange[0]), float(manual_xrange[1])
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(x0) and np.isfinite(x1) and x1 > x0):
        return None
    start = max(0, min(int(np.floor(x0)), len(df) - 1))
    end = max(0, min(int(np.ceil(x1)), len(df) - 1))
    if end <= start:
        return None
    start_time = normalize_bjt_timestamp(df.iloc[start]["open_time_bjt"])
    end_time = normalize_bjt_timestamp(df.iloc[end]["open_time_bjt"])
    if start_time is None or end_time is None:
        return None
    seconds = float((end_time - start_time).total_seconds())
    return seconds if seconds > 0 else None


def build_time_centered_xrange(
    df: pd.DataFrame,
    center_index: int,
    span_seconds: float | None,
) -> tuple[float, float] | None:
    if not isinstance(df, pd.DataFrame) or df.empty or span_seconds is None or span_seconds <= 0:
        return None
    center = max(0, min(int(center_index), len(df) - 1))
    center_time = normalize_bjt_timestamp(df.iloc[center].get("open_time_bjt"))
    if center_time is None:
        return None
    times = df["open_time_bjt"].map(normalize_bjt_timestamp)
    if times.isna().any():
        return None
    half_span = pd.Timedelta(seconds=float(span_seconds) / 2.0)
    left_target = center_time - half_span
    right_target = center_time + half_span
    left = int(times.searchsorted(left_target, side="left"))
    right = int(times.searchsorted(right_target, side="right")) - 1
    left = max(0, min(left, len(df) - 1))
    right = max(left + 1, min(right, len(df) - 1))
    if right <= left:
        right = min(len(df) - 1, left + 1)
    return float(left), float(right)


__all__ = [
    "build_time_centered_xrange",
    "capture_time_anchor",
    "capture_view_time_span",
    "find_bar_index_by_time",
    "normalize_bjt_timestamp",
]
