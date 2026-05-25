from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .factor_audit import assert_feature_safe
from .feature_registry import feature_registry_frame


METADATA_COLUMNS = [
    "event_id",
    "session_id",
    "trade_id",
    "event_type",
    "side",
    "symbol",
    "interval",
    "event_time_bjt",
]


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _divide(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or abs(denominator) < 1e-12:
        return math.nan
    return numerator / denominator


def _simple_return(start: float, end: float) -> float:
    return _divide(end - start, start)


def _window_return(pre: pd.DataFrame, size: int, logarithmic: bool = False) -> float:
    values = pd.to_numeric(pre.tail(size)["close"], errors="coerce").dropna()
    if len(values) < size:
        return math.nan
    start, end = float(values.iloc[0]), float(values.iloc[-1])
    if logarithmic:
        return float(math.log(end / start)) if start > 0 and end > 0 else math.nan
    return _simple_return(start, end)


def _zscore(value: float, history: pd.Series) -> float:
    values = pd.to_numeric(history, errors="coerce").dropna()
    if not math.isfinite(value) or len(values) < 2:
        return math.nan
    deviation = float(values.std(ddof=0))
    return _divide(value - float(values.mean()), deviation)


def _true_ranges(bars: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(bars["high"], errors="coerce")
    low = pd.to_numeric(bars["low"], errors="coerce")
    close = pd.to_numeric(bars["close"], errors="coerce")
    previous_close = close.shift(1)
    return pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)


def _realized_vol(pre: pd.DataFrame, size: int) -> float:
    closes = pd.to_numeric(pre.tail(size)["close"], errors="coerce").dropna()
    if len(closes) < size:
        return math.nan
    log_returns = np.log(closes / closes.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    return float(log_returns.std(ddof=0)) if len(log_returns) else math.nan


def _run_length(pre: pd.DataFrame, up: bool) -> int:
    length = 0
    for _, row in pre.sort_values("offset", ascending=False).iterrows():
        open_price, close_price = _number(row.get("open")), _number(row.get("close"))
        match = close_price > open_price if up else close_price < open_price
        if not match:
            break
        length += 1
    return length


def _slope(pre: pd.DataFrame) -> float:
    closes = pd.to_numeric(pre.tail(20)["close"], errors="coerce").dropna()
    closes = closes[closes > 0]
    if len(closes) < 2:
        return math.nan
    return float(np.polyfit(np.arange(len(closes), dtype=float), np.log(closes.to_numpy()), 1)[0])


def _bounded(value: float, scale: float = 1.0) -> float:
    if not math.isfinite(value):
        return math.nan
    return max(0.0, min(1.0, value / scale))


def _mean_score(values: list[float]) -> float:
    valid = [value for value in values if math.isfinite(value)]
    return float(np.mean(valid) * 100.0) if valid else math.nan


def _time_features(value: Any) -> tuple[float, float, str | None]:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return math.nan, math.nan, None
    hour = int(timestamp.hour)
    session = "BJT_00_08" if hour < 8 else ("BJT_08_16" if hour < 16 else "BJT_16_24")
    return float(hour), float(timestamp.dayofweek), session


def _regime(volatility: float) -> str | None:
    if not math.isfinite(volatility):
        return None
    if volatility < 0.003:
        return "LOW"
    if volatility > 0.015:
        return "HIGH"
    return "NORMAL"


def _trend_regime(slope: float) -> str | None:
    if not math.isfinite(slope):
        return None
    if slope < -0.001:
        return "DOWN"
    if slope > 0.001:
        return "UP"
    return "FLAT"


def _premium_features(premium: pd.DataFrame, event_time: Any) -> dict[str, float]:
    empty = {
        "premium_avg_pct": math.nan,
        "premium_change_3": math.nan,
        "premium_zscore_50": math.nan,
        "premium_spread": math.nan,
    }
    cutoff = pd.to_datetime(event_time, errors="coerce", utc=True)
    if premium.empty or "sample_time_bjt" not in premium.columns or pd.isna(cutoff):
        return empty
    values = premium.copy()
    values["_time"] = pd.to_datetime(values["sample_time_bjt"], errors="coerce", utc=True)
    values = values[values["_time"].notna() & (values["_time"] <= cutoff)].sort_values("_time")
    if values.empty:
        return empty
    avg_column = "avg_premium_pct" if "avg_premium_pct" in values.columns else "premium_pct"
    avg = pd.to_numeric(values.get(avg_column), errors="coerce").dropna()
    if avg.empty:
        return empty
    latest = float(avg.iloc[-1])
    change = float(avg.iloc[-1] - avg.iloc[-3]) if len(avg) >= 3 else math.nan
    zscore = _zscore(latest, avg.tail(50))
    sell = _number(values.iloc[-1].get("sell_premium_pct"))
    buy = _number(values.iloc[-1].get("buy_premium_pct"))
    return {
        "premium_avg_pct": latest,
        "premium_change_3": change,
        "premium_zscore_50": zscore,
        "premium_spread": sell - buy if math.isfinite(sell) and math.isfinite(buy) else math.nan,
    }


class FeatureFactory:
    def build(
        self,
        event_windows: pd.DataFrame,
        trade_events: pd.DataFrame | None = None,
        premium_history: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        windows = event_windows.copy() if isinstance(event_windows, pd.DataFrame) else pd.DataFrame()
        events = trade_events.copy() if isinstance(trade_events, pd.DataFrame) else pd.DataFrame()
        premium = premium_history.copy() if isinstance(premium_history, pd.DataFrame) else pd.DataFrame()
        factor_names = feature_registry_frame()["feature_name"].tolist()
        if windows.empty or "event_id" not in windows.columns:
            return pd.DataFrame(columns=[*METADATA_COLUMNS, *factor_names])
        event_map = {}
        if not events.empty and "event_id" in events.columns:
            event_map = {str(row["event_id"]): row.to_dict() for _, row in events.iterrows()}
        rows = []
        for event_id, input_group in windows.groupby("event_id", dropna=False):
            event_id = str(event_id)
            group = input_group.copy()
            group["offset"] = pd.to_numeric(group["offset"], errors="coerce")
            visible = group[group["offset"] <= 0].sort_values("offset")
            event_rows = visible[visible["offset"] == 0]
            if event_rows.empty:
                continue
            event = event_rows.iloc[-1]
            pre = visible[visible["offset"] < 0].copy()
            meta = event_map.get(event_id, {})
            event_time = meta.get("bar_open_time_bjt") or event.get("bar_open_time_bjt")
            open_price = _number(event.get("open"))
            high = _number(event.get("high"))
            low = _number(event.get("low"))
            close = _number(event.get("close"))
            volume = _number(event.get("volume"))
            candle_range = high - low if math.isfinite(high) and math.isfinite(low) else math.nan
            body = abs(close - open_price) if math.isfinite(close) and math.isfinite(open_price) else math.nan
            upper_wick = high - max(open_price, close) if math.isfinite(candle_range) else math.nan
            lower_wick = min(open_price, close) - low if math.isfinite(candle_range) else math.nan
            pre20 = pre.tail(20)
            prev_high = pd.to_numeric(pre20.get("high"), errors="coerce").max()
            prev_low = pd.to_numeric(pre20.get("low"), errors="coerce").min()
            prev_high = _number(prev_high)
            prev_low = _number(prev_low)
            previous_close_values = pd.to_numeric(pre.get("close"), errors="coerce").dropna()
            previous_close = float(previous_close_values.iloc[-1]) if len(previous_close_values) else math.nan
            all_true_ranges = _true_ranges(visible)
            true_range = float(all_true_ranges.iloc[-1]) if len(all_true_ranges) else math.nan
            atr_14 = float(all_true_ranges.tail(14).mean()) if all_true_ranges.tail(14).notna().any() else math.nan
            realized_vol_20 = _realized_vol(pre, 20)
            slope = _slope(pre)
            volume_ratio_5 = _divide(volume, float(pd.to_numeric(pre.tail(5).get("volume"), errors="coerce").mean()))
            volume_ratio_20 = _divide(volume, float(pd.to_numeric(pre20.get("volume"), errors="coerce").mean()))
            quote_volume = close * volume if math.isfinite(close) and math.isfinite(volume) else math.nan
            prior_quote_volume = pd.to_numeric(pre20.get("close"), errors="coerce") * pd.to_numeric(pre20.get("volume"), errors="coerce")
            close_position = _divide(close - low, candle_range)
            breaks_high = bool(math.isfinite(prev_high) and math.isfinite(high) and high > prev_high)
            breaks_low = bool(math.isfinite(prev_low) and math.isfinite(low) and low < prev_low)
            reclaims_low = bool(breaks_low and math.isfinite(close) and close > prev_low)
            rejects_high = bool(breaks_high and math.isfinite(close) and close < prev_high)
            hour, weekday, session = _time_features(event_time)
            row = {
                "event_id": event_id,
                "session_id": meta.get("session_id"),
                "trade_id": meta.get("trade_id"),
                "event_type": meta.get("event_type"),
                "side": meta.get("side"),
                "symbol": meta.get("symbol"),
                "interval": meta.get("interval"),
                "event_time_bjt": event_time,
                "body_pct": _divide(body, open_price),
                "body_to_range": _divide(body, candle_range),
                "upper_wick_ratio": _divide(upper_wick, candle_range),
                "lower_wick_ratio": _divide(lower_wick, candle_range),
                "upper_wick_atr_ratio": _divide(upper_wick, atr_14),
                "lower_wick_atr_ratio": _divide(lower_wick, atr_14),
                "close_position": close_position,
                "range_pct": _divide(candle_range, open_price),
                "range_atr_ratio": _divide(candle_range, atr_14),
                "body_atr_ratio": _divide(body, atr_14),
                "log_ret_1": float(math.log(close / previous_close)) if close > 0 and previous_close > 0 else math.nan,
                "pre_ret_3": _window_return(pre, 3),
                "pre_ret_5": _window_return(pre, 5),
                "pre_ret_10": _window_return(pre, 10),
                "pre_ret_20": _window_return(pre, 20),
                "pre_log_ret_5": _window_return(pre, 5, logarithmic=True),
                "pre_log_ret_10": _window_return(pre, 10, logarithmic=True),
                "down_run_length": float(_run_length(pre, up=False)),
                "up_run_length": float(_run_length(pre, up=True)),
                "trend_slope_20": slope,
                "distance_to_prev_high_20": _simple_return(prev_high, close),
                "distance_to_prev_low_20": _simple_return(prev_low, close),
                "break_prev_high_20": float(breaks_high),
                "break_prev_low_20": float(breaks_low),
                "reclaim_prev_low_20": float(reclaims_low),
                "reject_prev_high_20": float(rejects_high),
                "break_depth": _divide(prev_low - low, prev_low) if breaks_low else 0.0,
                "reclaim_strength": _divide(close - prev_low, prev_low) if reclaims_low else 0.0,
                "true_range": true_range,
                "atr_14": atr_14,
                "realized_vol_20": realized_vol_20,
                "realized_vol_50": _realized_vol(pre, 50),
                "volatility_regime": _regime(realized_vol_20),
                "range_zscore_20": _zscore(candle_range, pd.to_numeric(pre20.get("high"), errors="coerce") - pd.to_numeric(pre20.get("low"), errors="coerce")),
                "volume_ratio_5": volume_ratio_5,
                "volume_ratio_20": volume_ratio_20,
                "volume_zscore_20": _zscore(volume, pre20.get("volume")),
                "quote_volume_proxy": quote_volume,
                "quote_volume_zscore_20": _zscore(quote_volume, prior_quote_volume),
                "volume_climax_score": _mean_score([_bounded(volume_ratio_20, 3), _bounded(_divide(candle_range, atr_14), 3)]),
                "volume_absorption_score": _mean_score([_bounded(volume_ratio_20, 3), float(reclaims_low), close_position]),
                "volume_dump_score": _mean_score([_bounded(-_window_return(pre, 10), 0.05), _bounded(volume_ratio_20, 3)]),
                "reversal_candle_score": _mean_score([_divide(lower_wick, candle_range), close_position, _divide(body, candle_range)]),
                "panic_drop_score": _mean_score([_bounded(-_window_return(pre, 10), 0.05), _bounded(_divide(candle_range, atr_14), 3), _bounded(volume_ratio_20, 3)]),
                "false_breakdown_score": _mean_score([float(breaks_low), float(reclaims_low), close_position]),
                "fake_breakout_score": _mean_score([float(breaks_high), float(rejects_high), 1.0 - close_position if math.isfinite(close_position) else math.nan]),
                "hour_of_day": hour,
                "day_of_week": weekday,
                "time_session": session,
                "trend_regime": _trend_regime(slope),
                **_premium_features(premium, event_time),
            }
            rows.append(row)
        result = pd.DataFrame(rows).reindex(columns=[*METADATA_COLUMNS, *factor_names])
        assert_feature_safe(result)
        return result
