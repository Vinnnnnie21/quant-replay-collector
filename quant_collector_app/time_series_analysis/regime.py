from __future__ import annotations

import pandas as pd
import numpy as np


REGIME_COLUMNS = [
    "bar_index",
    "volatility_regime",
    "trend_regime",
    "drawdown_pct",
    "rolling_max_close_50",
    "distance_to_rolling_high_50_pct",
    "rolling_return_50",
    "rolling_volatility_50",
    "trend_threshold",
    "regime_label",
]


def _empty_regime() -> pd.DataFrame:
    return pd.DataFrame(columns=REGIME_COLUMNS)


def build_regime_features(
    returns_df: pd.DataFrame,
    window: int = 50,
    vol_multiplier: float = 1.5,
    min_abs_threshold: float = 0.02,
) -> pd.DataFrame:
    if returns_df is None or returns_df.empty or "close" not in returns_df.columns:
        return _empty_regime()
    df = returns_df.copy().sort_values("bar_index").reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    ret = pd.to_numeric(df.get("simple_return"), errors="coerce")
    window = max(2, int(window))
    vol_col = f"rolling_volatility_{window}"
    vol50 = pd.to_numeric(df.get(vol_col, df.get("rolling_volatility_50")), errors="coerce")
    rolling_return_50 = close / close.shift(window) - 1.0
    rolling_max = close.rolling(window, min_periods=1).max()
    distance = close / rolling_max.replace(0, np.nan) - 1.0
    drawdown = close / close.cummax().replace(0, np.nan) - 1.0

    vol_source = vol50.fillna(ret.rolling(window, min_periods=2).std())
    clean_vol = vol_source.replace([np.inf, -np.inf], np.nan).dropna()
    if clean_vol.empty or clean_vol.nunique() <= 1:
        q25 = q75 = q90 = None
    else:
        q25, q75, q90 = clean_vol.quantile([0.25, 0.75, 0.90]).tolist()

    def vol_label(value):
        if pd.isna(value):
            return "normal_vol"
        if q25 is None:
            return "normal_vol"
        if value <= q25:
            return "low_vol"
        if value >= q90:
            return "extreme_vol"
        if value >= q75:
            return "high_vol"
        return "normal_vol"

    threshold = (float(vol_multiplier) * vol_source.abs() * np.sqrt(window)).fillna(float(min_abs_threshold)).clip(lower=float(min_abs_threshold))
    trend = np.where(rolling_return_50 > threshold, "uptrend", np.where(rolling_return_50 < -threshold, "downtrend", "range"))

    out = pd.DataFrame(
        {
            "bar_index": df["bar_index"],
            "volatility_regime": [vol_label(v) for v in vol_source],
            "trend_regime": trend,
            "drawdown_pct": drawdown * 100.0,
            "rolling_max_close_50": rolling_max,
            "distance_to_rolling_high_50_pct": distance * 100.0,
            "rolling_return_50": rolling_return_50,
            "rolling_volatility_50": vol_source,
            "trend_threshold": threshold,
        }
    )
    out["regime_label"] = out["volatility_regime"].astype(str) + "_" + out["trend_regime"].astype(str)
    return out[REGIME_COLUMNS]


def summarize_regime_distribution(regime_df: pd.DataFrame) -> dict:
    if regime_df is None or regime_df.empty:
        return {"sample_count": 0, "volatility_regime": {}, "trend_regime": {}, "regime_label": {}}
    total = max(1, len(regime_df))

    def counts(column: str) -> dict:
        if column not in regime_df.columns:
            return {}
        vc = regime_df[column].fillna("unknown").value_counts()
        return {str(k): {"count": int(v), "pct": float(v / total * 100.0)} for k, v in vc.items()}

    return {
        "sample_count": int(len(regime_df)),
        "volatility_regime": counts("volatility_regime"),
        "trend_regime": counts("trend_regime"),
        "regime_label": counts("regime_label"),
    }
