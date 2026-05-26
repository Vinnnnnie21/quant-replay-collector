"""OHLCV-based Kline Liquidity Impact Proxy diagnostics.

This module constructs a Kline Liquidity Impact Proxy from historical OHLCV
bars. It cannot replace order-book data, trade-level data, bid-ask spread
observations, or real market-depth measurements. The output is intended for
historical market-state diagnosis, replay context, and event-study features;
it is not a trading signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}
PROXY_NUMERIC_COLUMNS = [
    "log_return",
    "range_log",
    "quote_volume",
    "range_vol_base",
    "volume_base",
    "vol_ratio",
    "volume_ratio",
    "impact_score",
    "impact_median",
    "impact_mad",
    "impact_z",
]


def classify_liquidity_state(row: pd.Series) -> str:
    """Classify a row after its rolling proxy statistics are available."""
    needed = ["vol_ratio", "volume_ratio", "impact_z"]
    if any(pd.isna(row.get(column)) for column in needed):
        return "UNKNOWN"
    if row["impact_z"] > 2 and row["volume_ratio"] < 0.8:
        return "LOW_LIQUIDITY_SHOCK"
    if row["impact_z"] > 2 and row["volume_ratio"] >= 1.5:
        return "EVENT_REPRICING"
    if row["impact_z"] < -1 and row["volume_ratio"] >= 1.5:
        return "ABSORPTION"
    if row["volume_ratio"] < 0.5 and row["vol_ratio"] < 0.8:
        return "QUIET_THIN_MARKET"
    return "NORMAL_LIQUIDITY"


def compute_liquidity_proxy(
    df: pd.DataFrame,
    window: int = 50,
    state_window: int = 100,
    eps: float = 1e-12,
) -> pd.DataFrame:
    """Return a copy of OHLCV bars enriched with liquidity impact proxies."""
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"missing required OHLCV columns: {sorted(missing)}")

    out = df.copy()
    window = max(1, int(window))
    state_window = max(1, int(state_window))
    eps = max(float(eps), np.finfo(float).eps)

    for column in REQUIRED_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    valid_close = out["close"].where(out["close"] > 0)
    valid_high = out["high"].where(out["high"] > 0)
    valid_low = out["low"].where(out["low"] > 0)
    valid_price_bar = valid_close.notna() & valid_high.notna() & valid_low.notna()

    out["log_return"] = np.log(valid_close / valid_close.shift(1))
    out["range_log"] = np.log(valid_high / valid_low).where(valid_price_bar)

    if "quote_volume" in out.columns:
        out["quote_volume"] = pd.to_numeric(out["quote_volume"], errors="coerce")
    else:
        out["quote_volume"] = out["volume"] * valid_close
    valid_quote_volume = out["quote_volume"].where((out["quote_volume"] > 0) & valid_price_bar)

    out["range_vol_base"] = out["range_log"].rolling(window, min_periods=window).median()
    out["volume_base"] = valid_quote_volume.rolling(window, min_periods=window).median()
    out["vol_ratio"] = out["range_log"] / (out["range_vol_base"] + eps)
    out["volume_ratio"] = valid_quote_volume / (out["volume_base"] + eps)
    out["impact_score"] = out["vol_ratio"] / (out["volume_ratio"] + eps)

    out["impact_median"] = out["impact_score"].rolling(state_window, min_periods=state_window).median()
    impact_deviation = (out["impact_score"] - out["impact_median"]).abs()
    out["impact_mad"] = impact_deviation.rolling(state_window, min_periods=state_window).median()
    out["impact_z"] = (out["impact_score"] - out["impact_median"]) / (1.4826 * out["impact_mad"] + eps)

    out[PROXY_NUMERIC_COLUMNS] = out[PROXY_NUMERIC_COLUMNS].replace([np.inf, -np.inf], np.nan)
    out["liquidity_state"] = out.apply(classify_liquidity_state, axis=1)
    return out


def summarize_liquidity_proxy(result_df: pd.DataFrame) -> dict:
    """Summarize computed proxy states without treating them as observations of depth."""
    if result_df is None or result_df.empty:
        return {
            "total_rows": 0,
            "valid_rows": 0,
            "state_counts": {},
            "low_liquidity_shock_count": 0,
            "event_repricing_count": 0,
            "absorption_count": 0,
            "mean_impact_score": None,
            "median_impact_score": None,
        }

    states = result_df.get("liquidity_state", pd.Series("UNKNOWN", index=result_df.index)).fillna("UNKNOWN").astype(str)
    counts = {str(key): int(value) for key, value in states.value_counts().items()}
    scores = pd.to_numeric(result_df.get("impact_score"), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "total_rows": int(len(result_df)),
        "valid_rows": int(states.ne("UNKNOWN").sum()),
        "state_counts": counts,
        "low_liquidity_shock_count": counts.get("LOW_LIQUIDITY_SHOCK", 0),
        "event_repricing_count": counts.get("EVENT_REPRICING", 0),
        "absorption_count": counts.get("ABSORPTION", 0),
        "mean_impact_score": float(scores.mean()) if not scores.empty else None,
        "median_impact_score": float(scores.median()) if not scores.empty else None,
    }
