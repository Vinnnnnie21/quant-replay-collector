"""Read-only multi-timeframe replay context built from timestamp alignment.

This module never creates trades, trade events, or trading signals. Higher
timeframe bars are context for replay review only.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

try:
    from market_data import interval_to_ms
except ImportError:  # pragma: no cover - package import path
    from .market_data import interval_to_ms


_DEFAULT_HIGHER_TIMEFRAMES = {
    "1m": ("5m", "15m"),
    "3m": ("15m", "1h"),
    "5m": ("15m", "1h"),
    "15m": ("1h", "4h"),
    "30m": ("1h", "4h"),
    "1h": ("4h", "1d"),
    "4h": ("1d",),
    "1d": (),
}


def higher_timeframes_for(primary_interval: str) -> tuple[str, ...]:
    return _DEFAULT_HIGHER_TIMEFRAMES.get(str(primary_interval).strip(), ())


def _as_bjt_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("Asia/Shanghai")
    return timestamp.tz_convert("Asia/Shanghai")


def _frame_with_close_time(htf_df: pd.DataFrame, htf_interval: str | None = None) -> pd.DataFrame:
    if not isinstance(htf_df, pd.DataFrame) or htf_df.empty or "open_time_bjt" not in htf_df.columns:
        return pd.DataFrame()
    if {"_open_time", "_close_time"} <= set(htf_df.columns):
        cached_interval = htf_df.attrs.get("_qrc_htf_interval")
        if htf_interval is None or cached_interval == htf_interval:
            return htf_df
    frame = htf_df.copy()
    frame["_open_time"] = frame["open_time_bjt"].map(_as_bjt_timestamp)
    frame = frame.sort_values("_open_time", kind="stable").reset_index(drop=True)
    if htf_interval:
        inferred_delta = pd.Timedelta(milliseconds=interval_to_ms(htf_interval))
    elif len(frame) > 1:
        inferred_delta = frame["_open_time"].diff().dropna().median()
    else:
        inferred_delta = None
    if "close_time_bjt" in frame.columns:
        frame["_close_time"] = frame["close_time_bjt"].map(_as_bjt_timestamp)
        if inferred_delta is not None:
            inferred_close = frame["_open_time"] + inferred_delta
            nearly_inferred = (inferred_close - frame["_close_time"]).between(
                pd.Timedelta(0), pd.Timedelta(milliseconds=1)
            )
            frame.loc[nearly_inferred, "_close_time"] = inferred_close.loc[nearly_inferred]
    elif inferred_delta is not None:
        frame["_close_time"] = frame["_open_time"] + inferred_delta
    else:
        return pd.DataFrame()
    frame.attrs["_qrc_htf_interval"] = htf_interval
    return frame


def normalize_context_frame(htf_df: pd.DataFrame, htf_interval: str | None = None) -> pd.DataFrame:
    """Normalize HTF timestamps once so replay refreshes can reuse the frame."""
    return _frame_with_close_time(htf_df, htf_interval)


def _matched_row(row: pd.Series | None, sync_status: str) -> dict[str, Any]:
    if row is None:
        return {"sync_status": sync_status, "htf_bar_index": None, "row": None}
    return {
        "sync_status": sync_status,
        "htf_bar_index": int(row["bar_index"]) if "bar_index" in row and pd.notna(row["bar_index"]) else int(row.name),
        "htf_open_time_bjt": row["_open_time"],
        "htf_close_time_bjt": row["_close_time"],
        "row": row.drop(labels=["_open_time", "_close_time"], errors="ignore").to_dict(),
    }


def find_context_bar_by_time(
    htf_df: pd.DataFrame,
    current_time_bjt: Any,
    htf_interval: str | None = None,
) -> dict[str, Any]:
    """Locate a containing HTF bar, falling back only to a completed earlier bar."""
    frame = _frame_with_close_time(htf_df, htf_interval)
    if frame.empty:
        return _matched_row(None, "unavailable")
    current_time = _as_bjt_timestamp(current_time_bjt)
    containing = frame[(frame["_open_time"] <= current_time) & (current_time < frame["_close_time"])]
    if not containing.empty:
        return _matched_row(containing.iloc[-1], "contains_cursor")
    completed = frame[frame["_close_time"] <= current_time]
    if not completed.empty:
        return _matched_row(completed.iloc[-1], "latest_completed")
    return _matched_row(None, "unavailable_before_cursor")


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _empty_state(htf_interval: str, sync_status: str, containing_index: int | None = None) -> dict[str, Any]:
    return {
        "htf_interval": htf_interval,
        "sync_status": sync_status,
        "containing_htf_bar_index": containing_index,
        "htf_bar_index": None,
        "htf_open_time_bjt": None,
        "htf_close_time_bjt": None,
        "close": None,
        "available_bars": 0,
        "history_status": "insufficient_history",
        "pre_simple_ret_20": None,
        "realized_vol_20": None,
        "trend_regime": None,
        "volatility_regime": None,
        "distance_to_high": None,
        "distance_to_low": None,
    }


def summarize_htf_state(
    htf_df: pd.DataFrame,
    context_bar_index: int | None,
    htf_interval: str = "",
) -> dict[str, Any]:
    """Summarize only bars at or before a visible completed HTF bar."""
    if context_bar_index is None:
        return _empty_state(htf_interval, "unavailable")
    frame = _frame_with_close_time(htf_df, htf_interval or None)
    if frame.empty:
        return _empty_state(htf_interval, "unavailable")
    indexes = pd.to_numeric(frame.get("bar_index", frame.index), errors="coerce")
    visible = frame[indexes <= int(context_bar_index)].copy()
    if visible.empty:
        return _empty_state(htf_interval, "unavailable_before_cursor")
    last = visible.iloc[-1]
    state = _empty_state(htf_interval, "completed")
    state.update(
        {
            "htf_bar_index": int(last["bar_index"]) if "bar_index" in last else int(last.name),
            "htf_open_time_bjt": last["_open_time"],
            "htf_close_time_bjt": last["_close_time"],
            "close": _finite_float(last.get("close")),
            "available_bars": int(len(visible)),
        }
    )
    if len(visible) < 20:
        return state
    window = visible.tail(20)
    close = pd.to_numeric(window["close"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    high = pd.to_numeric(window.get("high"), errors="coerce").replace([np.inf, -np.inf], np.nan)
    low = pd.to_numeric(window.get("low"), errors="coerce").replace([np.inf, -np.inf], np.nan)
    if close.isna().any() or (close <= 0).any():
        return state
    log_returns = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    simple_return = _finite_float(close.iloc[-1] / close.iloc[0] - 1.0)
    realized_vol = _finite_float(np.sqrt(log_returns.pow(2).sum())) if not log_returns.empty else None
    threshold = max(0.002, (realized_vol or 0.0))
    trend_regime = "uptrend" if (simple_return or 0.0) > threshold else (
        "downtrend" if (simple_return or 0.0) < -threshold else "range"
    )
    full_close = pd.to_numeric(visible["close"], errors="coerce")
    full_log_ret = np.log(full_close / full_close.shift(1)).replace([np.inf, -np.inf], np.nan)
    rolling_vol = np.sqrt(full_log_ret.pow(2).rolling(20, min_periods=20).sum()).dropna()
    baseline = _finite_float(rolling_vol.median()) if not rolling_vol.empty else None
    if realized_vol is None or baseline is None or baseline <= 0:
        volatility_regime = "normal_vol"
    elif realized_vol > baseline * 1.5:
        volatility_regime = "high_vol"
    elif realized_vol < baseline * 0.75:
        volatility_regime = "low_vol"
    else:
        volatility_regime = "normal_vol"
    current_close = close.iloc[-1]
    state.update(
        {
            "history_status": "available",
            "pre_simple_ret_20": simple_return,
            "realized_vol_20": realized_vol,
            "trend_regime": trend_regime,
            "volatility_regime": volatility_regime,
            "distance_to_high": _finite_float(current_close / high.max() - 1.0) if not high.empty else None,
            "distance_to_low": _finite_float(current_close / low.min() - 1.0) if not low.empty else None,
        }
    )
    return state


def build_multi_timeframe_context(
    primary_row: pd.Series | dict[str, Any],
    context_frames: dict[str, pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    """Build display-only HTF state aligned to a primary replay cursor time."""
    if isinstance(primary_row, pd.Series):
        current_time = primary_row.get("open_time_bjt")
    else:
        current_time = primary_row.get("open_time_bjt")
    if current_time is None:
        return {
            interval: _empty_state(interval, "missing_primary_time")
            for interval in context_frames
        }
    aligned: dict[str, dict[str, Any]] = {}
    visible_time = _as_bjt_timestamp(current_time)
    for interval, frame in context_frames.items():
        match = find_context_bar_by_time(frame, visible_time, interval)
        containing_index = match.get("htf_bar_index") if match["sync_status"] == "contains_cursor" else None
        if match["sync_status"] == "contains_cursor":
            normalized = _frame_with_close_time(frame, interval)
            completed = normalized[normalized["_close_time"] <= visible_time]
            visible_index = (
                int(completed.iloc[-1]["bar_index"])
                if not completed.empty and "bar_index" in completed.columns
                else None
            )
            sync_status = "previous_completed_for_no_future"
        else:
            visible_index = match.get("htf_bar_index")
            sync_status = match["sync_status"]
        summary = summarize_htf_state(frame, visible_index, interval)
        summary["sync_status"] = sync_status
        summary["containing_htf_bar_index"] = containing_index
        aligned[interval] = summary
    return aligned


__all__ = [
    "build_multi_timeframe_context",
    "find_context_bar_by_time",
    "higher_timeframes_for",
    "normalize_context_frame",
    "summarize_htf_state",
]
