from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from .feature_registry import model_input_features

try:
    from scipy import stats as scipy_stats
except ImportError:  # Optional dependency.
    scipy_stats = None


def _p_value(correlation: float, sample_count: int) -> float:
    if not math.isfinite(correlation) or sample_count < 3 or abs(correlation) >= 1.0:
        return 0.0 if sample_count >= 3 and abs(correlation) >= 1.0 else math.nan
    t_value = abs(correlation) * math.sqrt((sample_count - 2) / max(1e-12, 1.0 - correlation**2))
    return float(math.erfc(t_value / math.sqrt(2.0)))


def _rank_correlation(left: pd.Series, right: pd.Series) -> float:
    left_rank = left.rank(method="average").to_numpy(dtype=float)
    right_rank = right.rank(method="average").to_numpy(dtype=float)
    correlation = float(np.corrcoef(left_rank, right_rank)[0, 1])
    if math.isclose(correlation, 1.0, abs_tol=1e-12):
        return 1.0
    if math.isclose(correlation, -1.0, abs_tol=1e-12):
        return -1.0
    return correlation


def _time_blocks(samples: pd.DataFrame, time_col: str) -> pd.Series:
    if time_col in samples.columns:
        parsed = pd.to_datetime(samples[time_col], errors="coerce")
        if parsed.notna().any():
            return parsed.dt.strftime("%Y-%m")
    groups = min(5, max(1, len(samples) // 10))
    return pd.Series(pd.qcut(np.arange(len(samples)), q=groups, labels=False, duplicates="drop"), index=samples.index).astype(str)


def factor_ic(
    samples: pd.DataFrame,
    factor: str,
    label: str = "fwd_ret_10_side_adj",
    time_col: str = "event_time_bjt",
) -> dict:
    work = samples[[factor, label] + ([time_col] if time_col in samples.columns else [])].copy()
    work[factor] = pd.to_numeric(work[factor], errors="coerce")
    work[label] = pd.to_numeric(work[label], errors="coerce")
    work = work.dropna(subset=[factor, label])
    count = int(len(work))
    if count < 2 or work[factor].nunique() < 2 or work[label].nunique() < 2:
        return {
            "factor": factor,
            "label": label,
            "sample_count": count,
            "pearson_ic": math.nan,
            "spearman_rank_ic": math.nan,
            "p_value": math.nan,
            "ic_by_time_block": "{}",
            "ic_mean_by_block": math.nan,
            "ic_std_by_block": math.nan,
            "ic_positive_ratio": math.nan,
            "stability_score": math.nan,
            "warning": "insufficient variable data",
        }
    pearson = float(work[factor].corr(work[label], method="pearson"))
    spearman = _rank_correlation(work[factor], work[label])
    if scipy_stats is not None:
        try:
            p_value = float(scipy_stats.spearmanr(work[factor], work[label], nan_policy="omit").pvalue)
        except Exception:
            p_value = _p_value(spearman, count)
    else:
        p_value = _p_value(spearman, count)
    work["_block"] = _time_blocks(work, time_col)
    block_values = {}
    for block, group in work.groupby("_block", dropna=False):
        if len(group) >= 2 and group[factor].nunique() > 1 and group[label].nunique() > 1:
            block_values[str(block)] = _rank_correlation(group[factor], group[label])
    block_array = np.asarray(list(block_values.values()), dtype=float)
    block_mean = float(np.mean(block_array)) if len(block_array) else math.nan
    block_std = float(np.std(block_array, ddof=0)) if len(block_array) else math.nan
    positive_ratio = float((block_array > 0).mean()) if len(block_array) else math.nan
    stability = abs(block_mean) / (block_std + 1e-12) if math.isfinite(block_mean) and math.isfinite(block_std) else math.nan
    return {
        "factor": factor,
        "label": label,
        "sample_count": count,
        "pearson_ic": pearson,
        "spearman_rank_ic": spearman,
        "p_value": p_value,
        "ic_by_time_block": json.dumps(block_values, sort_keys=True),
        "ic_mean_by_block": block_mean,
        "ic_std_by_block": block_std,
        "ic_positive_ratio": positive_ratio,
        "stability_score": stability,
        "warning": "exploratory factor test; multiple testing risk",
    }


def build_factor_ic_summary(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    label: str = "fwd_ret_10_side_adj",
    factors: list[str] | None = None,
) -> pd.DataFrame:
    if features.empty or labels.empty or label not in labels.columns:
        return pd.DataFrame()
    samples = features.merge(labels[["event_id", label]], on="event_id", how="inner")
    chosen = factors or [name for name in model_input_features() if name in samples.columns]
    return pd.DataFrame([factor_ic(samples, factor, label) for factor in chosen])
