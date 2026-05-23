from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DEFAULT_FEATURE_COLS = [
    "pre_ret_20",
    "pre_max_drawdown_20",
    "pre_volatility_20",
    "pre_down_bar_count_20",
    "event_lower_wick_ratio",
    "event_close_position",
    "event_volume_ratio_20",
    "event_body_ratio",
    "event_range_vs_avg_range_20",
    "capitulation_score",
]

DEFAULT_LABEL_COLS = [
    "fwd_ret_5_side_adj",
    "fwd_ret_10_side_adj",
    "mfe_10",
    "mae_10",
    "label_win_5",
    "label_win_10",
    "label_good_trade_10",
    "label_failed_reversal_10",
]


def _label_stats(series: pd.Series) -> dict[str, Any]:
    if series.dropna().empty:
        return {"label_mean": None, "label_median": None, "win_rate_pct": None, "p25": None, "p75": None}
    if series.dropna().map(lambda x: isinstance(x, (bool, np.bool_))).all():
        numeric = series.astype(float)
        win_rate = float(numeric.mean() * 100.0)
    else:
        numeric = pd.to_numeric(series, errors="coerce")
        win_rate = float((numeric > 0).mean() * 100.0) if numeric.notna().any() else None
    numeric = numeric.dropna()
    return {
        "label_mean": float(numeric.mean()) if len(numeric) else None,
        "label_median": float(numeric.median()) if len(numeric) else None,
        "win_rate_pct": win_rate,
        "p25": float(numeric.quantile(0.25)) if len(numeric) else None,
        "p75": float(numeric.quantile(0.75)) if len(numeric) else None,
    }


def bin_feature_vs_label(df: pd.DataFrame, feature_col: str, label_col: str, n_bins: int = 5, method: str = "quantile") -> pd.DataFrame:
    if df is None or df.empty or feature_col not in df.columns or label_col not in df.columns:
        return pd.DataFrame()
    work = df[[feature_col, label_col]].copy()
    work[feature_col] = pd.to_numeric(work[feature_col], errors="coerce")
    work = work.dropna(subset=[feature_col])
    if len(work) < 2 or work[feature_col].nunique(dropna=True) < 2:
        return pd.DataFrame()
    bins = min(max(int(n_bins), 1), int(work[feature_col].nunique()))
    try:
        if method == "cut":
            work["_bin"] = pd.cut(work[feature_col], bins=bins, duplicates="drop")
        else:
            work["_bin"] = pd.qcut(work[feature_col], q=bins, duplicates="drop")
    except Exception:
        return pd.DataFrame()
    rows = []
    for interval, group in work.groupby("_bin", observed=True):
        if group.empty:
            continue
        stats = _label_stats(group[label_col])
        rows.append(
            {
                "feature": feature_col,
                "label": label_col,
                "bin": str(interval),
                "bin_left": float(interval.left) if hasattr(interval, "left") else None,
                "bin_right": float(interval.right) if hasattr(interval, "right") else None,
                "sample_count": int(len(group)),
                **stats,
                "low_sample_warning": bool(len(group) < 20),
            }
        )
    return pd.DataFrame(rows)


def build_binning_report(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    feature_cols: list[str] | None = None,
    label_cols: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    features = features.copy() if isinstance(features, pd.DataFrame) else pd.DataFrame()
    labels = labels.copy() if isinstance(labels, pd.DataFrame) else pd.DataFrame()
    if features.empty or labels.empty or "event_id" not in features.columns or "event_id" not in labels.columns:
        return {"feature_binning_summary": pd.DataFrame()}
    df = features.merge(labels, on="event_id", how="inner", suffixes=("", "_label"))
    feature_cols = feature_cols or [c for c in DEFAULT_FEATURE_COLS if c in df.columns]
    label_cols = label_cols or [c for c in DEFAULT_LABEL_COLS if c in df.columns]
    frames = []
    for fcol in feature_cols:
        for lcol in label_cols:
            result = bin_feature_vs_label(df, fcol, lcol)
            if not result.empty:
                frames.append(result)
    summary = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return {"feature_binning_summary": summary}

