from __future__ import annotations

import math

import pandas as pd

from app_config import EVENT_WINDOW_POST_BARS, EVENT_WINDOW_PRE_BARS
from .types import make_bjt


def compute_price_proxy(row: pd.Series) -> float:
    return float(row["high"] + row["low"]) / 2.0


def build_window_rows(
    df: pd.DataFrame,
    event_idx: int,
    pre_bars: int | None = None,
    post_bars: int | None = None,
):
    pre = EVENT_WINDOW_PRE_BARS if pre_bars is None else int(pre_bars)
    post = EVENT_WINDOW_POST_BARS if post_bars is None else int(post_bars)
    rows = []
    for offset in range(-max(0, pre), max(0, post) + 1):
        index = event_idx + offset
        if 0 <= index < len(df):
            row = df.iloc[index]
            rows.append(
                {
                    "offset": offset,
                    "is_event_bar": 1 if offset == 0 else 0,
                    "bar_index": int(row["bar_index"]),
                    "bar_open_time_bjt": make_bjt(row["open_time_bjt"]).isoformat(timespec="seconds"),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "is_missing_padding": 0,
                }
            )
        else:
            rows.append(
                {
                    "offset": offset,
                    "is_event_bar": 1 if offset == 0 else 0,
                    "bar_index": None,
                    "bar_open_time_bjt": None,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "volume": None,
                    "is_missing_padding": 1,
                }
            )
    return rows


def _safe_return(start: float | None, end: float | None):
    if start is None or end is None or start == 0:
        return math.nan
    return (end / start) - 1.0


def _slice_closes(df: pd.DataFrame, start: int, end: int):
    if start < 0 or end >= len(df) or start > end:
        return None
    return df.iloc[start:end + 1]["close"].astype(float).to_numpy()


def _trailing_run(df: pd.DataFrame, event_idx: int, bullish: bool):
    count = 0
    for index in range(event_idx, -1, -1):
        row = df.iloc[index]
        condition = float(row["close"]) >= float(row["open"]) if bullish else float(row["close"]) < float(row["open"])
        if not condition:
            break
        count += 1
    return count


def build_feature_row(df: pd.DataFrame, event_idx: int, side: str):
    """Build the legacy stored event row.

    This record includes outcome fields for existing exports. Model inputs must
    be built through ``research.factor_library.FeatureFactory``.
    """
    row = df.iloc[event_idx]
    opening, high, low, close, volume = [float(row[key]) for key in ["open", "high", "low", "close", "volume"]]
    price_proxy = compute_price_proxy(row)
    event_range = high - low
    body = abs(close - opening)
    upper = high - max(opening, close)
    lower = min(opening, close) - low
    previous_volume = df.iloc[max(0, event_idx - 5):event_idx]["volume"].astype(float)
    previous_volume_mean = float(previous_volume.mean()) if len(previous_volume) else math.nan
    volume_ratio_5 = (
        volume / previous_volume_mean
        if previous_volume_mean and not math.isnan(previous_volume_mean)
        else math.nan
    )

    def pre_ret(period: int):
        if event_idx - period < 0 or event_idx - 1 < 0:
            return math.nan
        return _safe_return(float(df.iloc[event_idx - period]["close"]), float(df.iloc[event_idx - 1]["close"]))

    def pre_vol(period: int):
        closes = _slice_closes(df, event_idx - period, event_idx - 1)
        if closes is None or len(closes) < 2:
            return math.nan
        changes = pd.Series(closes).pct_change().dropna()
        return float(changes.std(ddof=0)) if len(changes) else math.nan

    previous_ten = df.iloc[max(0, event_idx - 10):event_idx]
    previous_high = float(previous_ten["high"].max()) if len(previous_ten) else math.nan
    previous_low = float(previous_ten["low"].min()) if len(previous_ten) else math.nan

    def forward_return(period: int):
        if event_idx + period >= len(df):
            return math.nan
        return _safe_return(price_proxy, float(df.iloc[event_idx + period]["close"]))

    raw_forward = {period: forward_return(period) for period in (1, 3, 5, 10)}
    multiplier = 1.0 if side == "LONG" else -1.0
    side_forward = {
        period: value * multiplier if not math.isnan(value) else math.nan
        for period, value in raw_forward.items()
    }
    future = df.iloc[event_idx + 1:min(len(df), event_idx + 11)]
    if len(future):
        future_high = float(future["high"].max())
        future_low = float(future["low"].min())
        if side == "LONG":
            mfe_10 = _safe_return(price_proxy, future_high)
            mae_10 = _safe_return(price_proxy, future_low)
        else:
            mfe_10 = (price_proxy - future_low) / price_proxy if price_proxy else math.nan
            mae_10 = (price_proxy - future_high) / price_proxy if price_proxy else math.nan
    else:
        mfe_10 = math.nan
        mae_10 = math.nan
    return {
        "price_proxy": price_proxy,
        "event_body": body,
        "event_upper_wick": upper,
        "event_lower_wick": lower,
        "event_range": event_range,
        "event_volume": volume,
        "event_vol_ratio_5": volume_ratio_5,
        "pre_ret_3": pre_ret(3),
        "pre_ret_5": pre_ret(5),
        "pre_ret_10": pre_ret(10),
        "pre_vol_3": pre_vol(3),
        "pre_vol_5": pre_vol(5),
        "pre_vol_10": pre_vol(10),
        "prev_high10_dist_pct": _safe_return(price_proxy, previous_high),
        "prev_low10_dist_pct": _safe_return(price_proxy, previous_low),
        "bull_run_count": _trailing_run(df, event_idx, bullish=True),
        "bear_run_count": _trailing_run(df, event_idx, bullish=False),
        "event_upper_ratio": upper / event_range if event_range else math.nan,
        "event_lower_ratio": lower / event_range if event_range else math.nan,
        "event_body_ratio": body / event_range if event_range else math.nan,
        "fwd_ret_1": raw_forward[1],
        "fwd_ret_3": raw_forward[3],
        "fwd_ret_5": raw_forward[5],
        "fwd_ret_10": raw_forward[10],
        "fwd_ret_1_side_adj": side_forward[1],
        "fwd_ret_3_side_adj": side_forward[3],
        "fwd_ret_5_side_adj": side_forward[5],
        "fwd_ret_10_side_adj": side_forward[10],
        "mfe_10": mfe_10,
        "mae_10": mae_10,
    }


__all__ = ["build_feature_row", "build_window_rows", "compute_price_proxy"]
