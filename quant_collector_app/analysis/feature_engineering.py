from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_COLUMNS = [
    "event_id",
    "session_id",
    "trade_id",
    "event_type",
    "side",
    "symbol",
    "interval",
    "pre_ret_3",
    "pre_ret_5",
    "pre_ret_10",
    "pre_ret_20",
    "pre_max_drawdown_20",
    "pre_volatility_20",
    "pre_down_bar_count_20",
    "pre_bear_ratio_20",
    "pre_consecutive_bear_count",
    "pre_avg_body_20",
    "pre_avg_range_20",
    "pre_avg_volume_20",
    "event_body_pct",
    "event_range_pct",
    "event_body_ratio",
    "event_upper_wick_ratio",
    "event_lower_wick_ratio",
    "event_close_position",
    "event_is_bullish",
    "event_is_bearish",
    "event_volume_ratio_20",
    "event_range_vs_avg_range_20",
    "event_body_vs_avg_body_20",
    "break_prev_low_20",
    "recover_prev_low_20",
    "distance_to_prev_low_pct",
    "pre_ret_20_zscore",
    "capitulation_score",
]


def _safe_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return math.nan
    return out if math.isfinite(out) else math.nan


def _safe_div(num: float, den: float) -> float:
    if den is None or not math.isfinite(den) or abs(den) < 1e-12:
        return math.nan
    return num / den


def _ret(a: float, b: float) -> float:
    return _safe_div(b - a, a)


def _max_drawdown(values: pd.Series) -> float:
    series = pd.to_numeric(values, errors="coerce").dropna()
    if len(series) < 2:
        return math.nan
    running_max = series.cummax()
    dd = (series / running_max) - 1.0
    return abs(float(dd.min()))


def _pre_ret(pre: pd.DataFrame, n: int) -> float:
    subset = pre[pre["offset"] >= -n].sort_values("offset")
    closes = pd.to_numeric(subset["close"], errors="coerce").dropna()
    if len(closes) < 2:
        return math.nan
    return _ret(float(closes.iloc[0]), float(closes.iloc[-1]))


def _trailing_bear_count(pre: pd.DataFrame) -> int:
    count = 0
    for _, row in pre.sort_values("offset", ascending=False).iterrows():
        if _safe_float(row.get("close")) < _safe_float(row.get("open")):
            count += 1
        else:
            break
    return count


def _norm(value: float, low: float, high: float) -> float:
    if not math.isfinite(value) or high <= low:
        return 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _score(row: dict[str, Any]) -> float:
    components = [
        _norm(-_safe_float(row.get("pre_ret_20")), 0.0, 0.10),
        _norm(_safe_float(row.get("pre_max_drawdown_20")), 0.0, 0.12),
        _norm(_safe_float(row.get("event_volume_ratio_20")), 1.0, 5.0),
        _norm(_safe_float(row.get("event_lower_wick_ratio")), 0.0, 0.70),
        _norm(_safe_float(row.get("event_close_position")), 0.30, 1.0),
    ]
    return float(sum(components) / len(components) * 100.0)


def build_enhanced_event_features(event_windows_long: pd.DataFrame, trade_events: pd.DataFrame) -> pd.DataFrame:
    windows = event_windows_long.copy() if isinstance(event_windows_long, pd.DataFrame) else pd.DataFrame()
    events = trade_events.copy() if isinstance(trade_events, pd.DataFrame) else pd.DataFrame()
    if windows.empty or "event_id" not in windows.columns:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    windows = windows[pd.to_numeric(windows.get("offset"), errors="coerce").fillna(9999) <= 0].copy()
    if windows.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    windows["offset"] = pd.to_numeric(windows["offset"], errors="coerce").astype("Int64")

    event_meta = {}
    if not events.empty and "event_id" in events.columns:
        event_meta = {str(row["event_id"]): row.to_dict() for _, row in events.iterrows()}

    rows: list[dict[str, Any]] = []
    for event_id, group in windows.groupby("event_id", dropna=False):
        event_id = str(event_id)
        group = group.sort_values("offset")
        pre = group[group["offset"] < 0].copy()
        event_rows = group[group["offset"] == 0]
        if event_rows.empty:
            continue
        event = event_rows.iloc[-1]
        pre20 = pre[pre["offset"] >= -20].copy()

        e_open = _safe_float(event.get("open"))
        e_high = _safe_float(event.get("high"))
        e_low = _safe_float(event.get("low"))
        e_close = _safe_float(event.get("close"))
        e_volume = _safe_float(event.get("volume"))
        e_range = e_high - e_low if math.isfinite(e_high) and math.isfinite(e_low) else math.nan
        e_body = abs(e_close - e_open) if math.isfinite(e_close) and math.isfinite(e_open) else math.nan

        pre_open = pd.to_numeric(pre20.get("open"), errors="coerce")
        pre_close = pd.to_numeric(pre20.get("close"), errors="coerce")
        pre_high = pd.to_numeric(pre20.get("high"), errors="coerce")
        pre_low = pd.to_numeric(pre20.get("low"), errors="coerce")
        pre_volume = pd.to_numeric(pre20.get("volume"), errors="coerce")
        pre_body = (pre_close - pre_open).abs()
        pre_range = (pre_high - pre_low).abs()
        pre_returns = pre_close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        prev_low = float(pre_low.min()) if pre_low.notna().any() else math.nan
        pre_avg_body = float(pre_body.mean()) if pre_body.notna().any() else math.nan
        pre_avg_range = float(pre_range.mean()) if pre_range.notna().any() else math.nan
        pre_avg_volume = float(pre_volume.mean()) if pre_volume.notna().any() else math.nan
        pre_ret_20 = _pre_ret(pre, 20)
        pre_vol = float(pre_returns.std(ddof=0)) if len(pre_returns) else math.nan

        row = {
            "event_id": event_id,
            "pre_ret_3": _pre_ret(pre, 3),
            "pre_ret_5": _pre_ret(pre, 5),
            "pre_ret_10": _pre_ret(pre, 10),
            "pre_ret_20": pre_ret_20,
            "pre_max_drawdown_20": _max_drawdown(pre20["close"]) if "close" in pre20 else math.nan,
            "pre_volatility_20": pre_vol,
            "pre_down_bar_count_20": int((pre_close < pre_open).sum()) if len(pre20) else 0,
            "pre_bear_ratio_20": float((pre_close < pre_open).mean()) if len(pre20) else math.nan,
            "pre_consecutive_bear_count": _trailing_bear_count(pre20),
            "pre_avg_body_20": pre_avg_body,
            "pre_avg_range_20": pre_avg_range,
            "pre_avg_volume_20": pre_avg_volume,
            "event_body_pct": _safe_div(e_body, e_open),
            "event_range_pct": _safe_div(e_range, e_open),
            "event_body_ratio": _safe_div(e_body, e_range),
            "event_upper_wick_ratio": _safe_div(e_high - max(e_open, e_close), e_range),
            "event_lower_wick_ratio": _safe_div(min(e_open, e_close) - e_low, e_range),
            "event_close_position": _safe_div(e_close - e_low, e_range),
            "event_is_bullish": bool(e_close > e_open) if math.isfinite(e_close) and math.isfinite(e_open) else False,
            "event_is_bearish": bool(e_close < e_open) if math.isfinite(e_close) and math.isfinite(e_open) else False,
            "event_volume_ratio_20": _safe_div(e_volume, pre_avg_volume),
            "event_range_vs_avg_range_20": _safe_div(e_range, pre_avg_range),
            "event_body_vs_avg_body_20": _safe_div(e_body, pre_avg_body),
            "break_prev_low_20": bool(e_low < prev_low) if math.isfinite(prev_low) and math.isfinite(e_low) else False,
            "recover_prev_low_20": bool(e_low < prev_low and e_close > prev_low) if math.isfinite(prev_low) and math.isfinite(e_low) and math.isfinite(e_close) else False,
            "distance_to_prev_low_pct": _ret(prev_low, e_close) if math.isfinite(prev_low) else math.nan,
            "pre_ret_20_zscore": _safe_div(pre_ret_20, pre_vol),
        }
        row["capitulation_score"] = _score(row)
        meta = event_meta.get(event_id, {})
        for col in ["session_id", "trade_id", "event_type", "side", "symbol", "interval"]:
            row[col] = meta.get(col, event.get(col))
        rows.append(row)

    return pd.DataFrame(rows).reindex(columns=OUTPUT_COLUMNS)

