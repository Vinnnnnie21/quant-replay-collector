from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .bootstrap import bootstrap_mean_ci
from .feature_registry import model_input_features


def _monotonicity(means: list[float]) -> float:
    values = pd.Series(means, dtype="float64").dropna()
    if len(values) < 2 or values.nunique() < 2:
        return math.nan
    order = pd.Series(range(len(values)), dtype="float64").rank(method="average")
    ranks = values.reset_index(drop=True).rank(method="average")
    return float(np.corrcoef(order.to_numpy(), ranks.to_numpy())[0, 1])


def bin_factor(
    samples: pd.DataFrame,
    factor: str,
    label: str = "fwd_ret_10_side_adj",
    n_bins: int = 5,
) -> pd.DataFrame:
    if samples.empty or factor not in samples.columns or label not in samples.columns:
        return pd.DataFrame()
    total = len(samples)
    work = samples[[factor, label]].copy()
    work[factor] = pd.to_numeric(work[factor], errors="coerce")
    work[label] = pd.to_numeric(work[label], errors="coerce")
    missing_rate = float(work[factor].isna().mean())
    work = work.dropna(subset=[factor, label])
    unique_count = int(work[factor].nunique())
    if len(work) < 2 or unique_count < 2:
        return pd.DataFrame(
            [{
                "factor": factor,
                "label": label,
                "warning": "insufficient non-missing or unique values for binning",
                "missing_rate": missing_rate,
            }]
        )
    adjusted_bins = min(max(2, int(n_bins)), unique_count, max(2, len(work) // 5))
    warning = ""
    if adjusted_bins < int(n_bins):
        warning = f"bin count reduced from {n_bins} to {adjusted_bins}"
    try:
        work["_bin"] = pd.qcut(work[factor], q=adjusted_bins, duplicates="drop")
    except ValueError:
        work["_bin"] = pd.cut(work[factor], bins=adjusted_bins, duplicates="drop")
    rows = []
    means = []
    for bin_id, (interval, group) in enumerate(work.groupby("_bin", observed=True), start=1):
        values = group[label].dropna()
        ci_result = bootstrap_mean_ci(values)
        mean_value = float(values.mean()) if len(values) else math.nan
        means.append(mean_value)
        rows.append(
            {
                "factor": factor,
                "label": label,
                "bin_id": bin_id,
                "bin_left": float(interval.left),
                "bin_right": float(interval.right),
                "sample_count": int(len(values)),
                "mean_label": mean_value,
                "median_label": float(values.median()) if len(values) else math.nan,
                "win_rate": float((values > 0).mean() * 100.0) if len(values) else math.nan,
                "q25": float(values.quantile(0.25)) if len(values) else math.nan,
                "q75": float(values.quantile(0.75)) if len(values) else math.nan,
                "bootstrap_ci_low": ci_result["ci_low"],
                "bootstrap_ci_high": ci_result["ci_high"],
                "monotonicity_score": math.nan,
                "missing_rate": missing_rate,
                "warning": warning or ci_result["warning"],
                "source_sample_count": total,
            }
        )
    score = _monotonicity(means)
    for row in rows:
        row["monotonicity_score"] = score
    return pd.DataFrame(rows)


def build_factor_binning_summary(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    label: str = "fwd_ret_10_side_adj",
    factors: list[str] | None = None,
    n_bins: int = 5,
) -> pd.DataFrame:
    if features.empty or labels.empty or "event_id" not in features.columns or "event_id" not in labels.columns:
        return pd.DataFrame()
    samples = features.merge(labels[["event_id", label]], on="event_id", how="inner") if label in labels.columns else pd.DataFrame()
    chosen = factors or [name for name in model_input_features() if name in samples.columns]
    frames = [bin_factor(samples, factor, label, n_bins) for factor in chosen]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
