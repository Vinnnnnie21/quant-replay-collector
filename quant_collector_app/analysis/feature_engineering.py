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
    "log_ret_1",
    "pre_log_ret_5",
    "pre_log_ret_10",
    "pre_log_ret_20",
    "realized_vol_20",
    "atr_14",
    "range_pct",
    "range_atr_ratio",
    "body_atr_ratio",
    "upper_wick_atr_ratio",
    "lower_wick_atr_ratio",
    "volume_zscore_20",
    "range_zscore_20",
    "close_position",
    "distance_to_prev_high_20",
    "distance_to_prev_low_20",
    "break_prev_high_20",
    "fake_breakout_down",
    "fake_breakout_up",
    "trend_slope_20",
    "volatility_regime",
    "time_of_day_bucket",
]


FEATURE_REGISTRY = {
    "event_id": ("Stable event identifier.", False, False),
    "session_id": ("Replay session identifier.", False, False),
    "trade_id": ("Manual trade identifier.", False, True),
    "event_type": ("Event type recorded by the user.", False, True),
    "side": ("Manual event direction.", False, True),
    "symbol": ("Market symbol.", False, False),
    "interval": ("Bar interval.", False, False),
    "pre_ret_3": ("Simple close return over the preceding 3 bars.", True, False),
    "pre_ret_5": ("Simple close return over the preceding 5 bars.", True, False),
    "pre_ret_10": ("Simple close return over the preceding 10 bars.", True, False),
    "pre_ret_20": ("Simple close return over the preceding 20 bars.", True, False),
    "pre_max_drawdown_20": ("Maximum drawdown in the prior 20 bars.", True, False),
    "pre_volatility_20": ("Standard deviation of prior simple returns.", True, False),
    "pre_down_bar_count_20": ("Count of bearish prior bars.", True, False),
    "pre_bear_ratio_20": ("Share of bearish prior bars.", True, False),
    "pre_consecutive_bear_count": ("Trailing bearish run before the event bar.", True, False),
    "pre_avg_body_20": ("Mean prior candle body size.", True, False),
    "pre_avg_range_20": ("Mean prior candle range.", True, False),
    "pre_avg_volume_20": ("Mean prior volume.", True, False),
    "event_body_pct": ("Event candle body divided by open price.", True, False),
    "event_range_pct": ("Event candle range divided by open price.", True, False),
    "event_body_ratio": ("Event candle body divided by range.", True, False),
    "event_upper_wick_ratio": ("Upper wick divided by event range.", True, False),
    "event_lower_wick_ratio": ("Lower wick divided by event range.", True, False),
    "event_close_position": ("Close location within event range.", True, False),
    "event_is_bullish": ("Event bar closes above its open.", True, False),
    "event_is_bearish": ("Event bar closes below its open.", True, False),
    "event_volume_ratio_20": ("Event volume divided by prior mean volume.", True, False),
    "event_range_vs_avg_range_20": ("Event range divided by prior mean range.", True, False),
    "event_body_vs_avg_body_20": ("Event body divided by prior mean body.", True, False),
    "break_prev_low_20": ("Event low breaks the preceding 20-bar low.", True, False),
    "recover_prev_low_20": ("Event closes back above a broken preceding low.", True, False),
    "distance_to_prev_low_pct": ("Close distance from preceding low.", True, False),
    "pre_ret_20_zscore": ("Prior return divided by prior volatility.", True, False),
    "capitulation_score": ("Explainable composite of historical and event-bar shape measures.", True, False),
    "log_ret_1": ("Event close log return from the immediately preceding close.", True, False),
    "pre_log_ret_5": ("Log return within the preceding 5-bar history.", True, False),
    "pre_log_ret_10": ("Log return within the preceding 10-bar history.", True, False),
    "pre_log_ret_20": ("Log return within the preceding 20-bar history.", True, False),
    "realized_vol_20": ("Standard deviation of preceding log returns.", True, False),
    "atr_14": ("Average true range through the event bar, using up to 14 bars.", True, False),
    "range_pct": ("Event high-low range divided by open.", True, False),
    "range_atr_ratio": ("Event range divided by ATR.", True, False),
    "body_atr_ratio": ("Event body divided by ATR.", True, False),
    "upper_wick_atr_ratio": ("Event upper wick divided by ATR.", True, False),
    "lower_wick_atr_ratio": ("Event lower wick divided by ATR.", True, False),
    "volume_zscore_20": ("Event volume z-score versus preceding volume.", True, False),
    "range_zscore_20": ("Event range z-score versus preceding ranges.", True, False),
    "close_position": ("Alias for event close position within its range.", True, False),
    "distance_to_prev_high_20": ("Close distance from preceding 20-bar high.", True, False),
    "distance_to_prev_low_20": ("Close distance from preceding 20-bar low.", True, False),
    "break_prev_high_20": ("Event high breaks the preceding 20-bar high.", True, False),
    "fake_breakout_down": ("Event breaks prior low then closes back above it.", True, False),
    "fake_breakout_up": ("Event breaks prior high then closes back below it.", True, False),
    "trend_slope_20": ("OLS slope of preceding log close prices.", True, False),
    "volatility_regime": ("Bucket derived from preceding realized volatility.", True, False),
    "time_of_day_bucket": ("Beijing-time trading session bucket of the event bar.", True, False),
}


def feature_registry_frame() -> pd.DataFrame:
    rows = [
        {
            "field": field,
            "description": definition[0],
            "model_input_allowed": definition[1],
            "future_leakage_risk": definition[2],
        }
        for field, definition in FEATURE_REGISTRY.items()
    ]
    return pd.DataFrame(rows)


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


def _pre_log_ret(pre: pd.DataFrame, n: int) -> float:
    subset = pre[pre["offset"] >= -n].sort_values("offset")
    closes = pd.to_numeric(subset["close"], errors="coerce").dropna()
    if len(closes) < 2 or float(closes.iloc[0]) <= 0 or float(closes.iloc[-1]) <= 0:
        return math.nan
    return float(math.log(float(closes.iloc[-1]) / float(closes.iloc[0])))


def _zscore(value: float, history: pd.Series) -> float:
    values = pd.to_numeric(history, errors="coerce").dropna()
    if not math.isfinite(value) or len(values) < 2:
        return math.nan
    std = float(values.std(ddof=0))
    return _safe_div(value - float(values.mean()), std)


def _atr_through_event(group: pd.DataFrame, periods: int = 14) -> float:
    bars = group.sort_values("offset").tail(periods).copy()
    high = pd.to_numeric(bars["high"], errors="coerce")
    low = pd.to_numeric(bars["low"], errors="coerce")
    close = pd.to_numeric(bars["close"], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    return float(true_range.dropna().mean()) if true_range.notna().any() else math.nan


def _trend_slope(pre: pd.DataFrame) -> float:
    close = pd.to_numeric(pre.sort_values("offset")["close"], errors="coerce").dropna()
    close = close[close > 0]
    if len(close) < 2:
        return math.nan
    return float(np.polyfit(np.arange(len(close), dtype=float), np.log(close.to_numpy()), 1)[0])


def _volatility_regime(vol: float) -> str | None:
    if not math.isfinite(vol):
        return None
    if vol < 0.003:
        return "LOW"
    if vol > 0.015:
        return "HIGH"
    return "NORMAL"


def _time_bucket(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    hour = int(parsed.hour)
    if 0 <= hour < 8:
        return "BJT_00_08"
    if hour < 16:
        return "BJT_08_16"
    return "BJT_16_24"


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
        pre_log_returns = np.log(pre_close / pre_close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
        prev_high = float(pre_high.max()) if pre_high.notna().any() else math.nan
        prev_low = float(pre_low.min()) if pre_low.notna().any() else math.nan
        pre_avg_body = float(pre_body.mean()) if pre_body.notna().any() else math.nan
        pre_avg_range = float(pre_range.mean()) if pre_range.notna().any() else math.nan
        pre_avg_volume = float(pre_volume.mean()) if pre_volume.notna().any() else math.nan
        pre_ret_20 = _pre_ret(pre, 20)
        pre_vol = float(pre_returns.std(ddof=0)) if len(pre_returns) else math.nan
        realized_vol = float(pre_log_returns.std(ddof=0)) if len(pre_log_returns) else math.nan
        atr_14 = _atr_through_event(group, 14)
        previous_closes = pd.to_numeric(pre.sort_values("offset").get("close"), errors="coerce").dropna()
        previous_close = float(previous_closes.iloc[-1]) if len(previous_closes) else math.nan
        log_ret_1 = (
            float(math.log(e_close / previous_close))
            if math.isfinite(e_close) and math.isfinite(previous_close) and e_close > 0 and previous_close > 0
            else math.nan
        )
        upper_wick = e_high - max(e_open, e_close) if math.isfinite(e_range) else math.nan
        lower_wick = min(e_open, e_close) - e_low if math.isfinite(e_range) else math.nan

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
            "log_ret_1": log_ret_1,
            "pre_log_ret_5": _pre_log_ret(pre, 5),
            "pre_log_ret_10": _pre_log_ret(pre, 10),
            "pre_log_ret_20": _pre_log_ret(pre, 20),
            "realized_vol_20": realized_vol,
            "atr_14": atr_14,
            "range_pct": _safe_div(e_range, e_open),
            "range_atr_ratio": _safe_div(e_range, atr_14),
            "body_atr_ratio": _safe_div(e_body, atr_14),
            "upper_wick_atr_ratio": _safe_div(upper_wick, atr_14),
            "lower_wick_atr_ratio": _safe_div(lower_wick, atr_14),
            "volume_zscore_20": _zscore(e_volume, pre_volume),
            "range_zscore_20": _zscore(e_range, pre_range),
            "close_position": _safe_div(e_close - e_low, e_range),
            "distance_to_prev_high_20": _ret(prev_high, e_close) if math.isfinite(prev_high) else math.nan,
            "distance_to_prev_low_20": _ret(prev_low, e_close) if math.isfinite(prev_low) else math.nan,
            "break_prev_high_20": bool(e_high > prev_high) if math.isfinite(prev_high) and math.isfinite(e_high) else False,
            "fake_breakout_down": bool(e_low < prev_low and e_close > prev_low) if math.isfinite(prev_low) and math.isfinite(e_low) and math.isfinite(e_close) else False,
            "fake_breakout_up": bool(e_high > prev_high and e_close < prev_high) if math.isfinite(prev_high) and math.isfinite(e_high) and math.isfinite(e_close) else False,
            "trend_slope_20": _trend_slope(pre20),
            "volatility_regime": _volatility_regime(realized_vol),
            "time_of_day_bucket": _time_bucket(event.get("bar_open_time_bjt")),
        }
        row["capitulation_score"] = _score(row)
        meta = event_meta.get(event_id, {})
        for col in ["session_id", "trade_id", "event_type", "side", "symbol", "interval"]:
            row[col] = meta.get(col, event.get(col))
        rows.append(row)

    return pd.DataFrame(rows).reindex(columns=OUTPUT_COLUMNS)
