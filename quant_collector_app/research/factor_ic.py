from __future__ import annotations

import json
import math
import re

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


def _infer_horizon_bars(label: str) -> int | None:
    match = re.search(r"(?:^|_)fwd_ret_(\d+)(?:_|$)", str(label))
    if not match:
        return None
    return int(match.group(1))


def _default_block_size(sample_count: int, horizon_bars: int | None = None) -> int:
    sqrt_n = int(math.ceil(math.sqrt(max(1, sample_count))))
    if horizon_bars is not None and horizon_bars > 1:
        return max(sqrt_n, int(horizon_bars))
    return sqrt_n


def _rank_correlation(left: pd.Series, right: pd.Series) -> float:
    left_rank = left.rank(method="average").to_numpy(dtype=float)
    right_rank = right.rank(method="average").to_numpy(dtype=float)
    correlation = float(np.corrcoef(left_rank, right_rank)[0, 1])
    if math.isclose(correlation, 1.0, abs_tol=1e-12):
        return 1.0
    if math.isclose(correlation, -1.0, abs_tol=1e-12):
        return -1.0
    return correlation


def _safe_rank_ic(samples: pd.DataFrame, factor: str, label: str) -> float:
    if len(samples) < 2 or samples[factor].nunique() < 2 or samples[label].nunique() < 2:
        return math.nan
    return _rank_correlation(samples[factor], samples[label])


def _block_bootstrap_ic_ci(
    samples: pd.DataFrame,
    factor: str,
    label: str,
    block_size: int,
    n_bootstrap: int,
    random_seed: int | None,
) -> tuple[float, float, int]:
    if len(samples) < 3 or n_bootstrap <= 0:
        return math.nan, math.nan, 0
    block_size = max(1, min(int(block_size), len(samples)))
    rng = np.random.default_rng(random_seed)
    values: list[float] = []
    starts = np.arange(0, len(samples))
    for _ in range(int(n_bootstrap)):
        pieces = []
        while sum(len(piece) for piece in pieces) < len(samples):
            start = int(rng.choice(starts))
            end = min(len(samples), start + block_size)
            pieces.append(samples.iloc[start:end])
        boot = pd.concat(pieces, ignore_index=True).iloc[: len(samples)]
        ic = _safe_rank_ic(boot, factor, label)
        if math.isfinite(ic):
            values.append(float(ic))
    if not values:
        return math.nan, math.nan, 0
    low, high = np.percentile(np.asarray(values, dtype=float), [2.5, 97.5])
    return float(low), float(high), len(values)


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
    *,
    horizon_bars: int | None = None,
    block_size: int | None = None,
    n_bootstrap: int = 200,
    random_seed: int | None = 0,
    min_time_blocks: int = 3,
) -> dict:
    work = samples[[factor, label] + ([time_col] if time_col in samples.columns else [])].copy()
    work[factor] = pd.to_numeric(work[factor], errors="coerce")
    work[label] = pd.to_numeric(work[label], errors="coerce")
    work = work.dropna(subset=[factor, label])
    count = int(len(work))
    inferred_horizon = horizon_bars if horizon_bars is not None else _infer_horizon_bars(label)
    effective_block_size = block_size or _default_block_size(count, inferred_horizon)
    if count < 2 or work[factor].nunique() < 2 or work[label].nunique() < 2:
        return {
            "factor": factor,
            "label": label,
            "sample_count": count,
            "pearson_ic": math.nan,
            "spearman_rank_ic": math.nan,
            "p_value": math.nan,
            "approximate_p_value": math.nan,
            "p_value_note": "unavailable",
            "ic_bootstrap_ci_low": math.nan,
            "ic_bootstrap_ci_high": math.nan,
            "block_size": effective_block_size,
            "bootstrap_sample_count": 0,
            "ic_by_time_block": "{}",
            "ic_mean_by_block": math.nan,
            "ic_std_by_block": math.nan,
            "ic_positive_ratio": math.nan,
            "stability_score": math.nan,
            "time_block_count": 0,
            "min_block_count_warning": True,
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
    approximate_p_value = p_value
    work = work.sort_values(time_col, kind="stable") if time_col in work.columns else work.reset_index(drop=True)
    ci_low, ci_high, bootstrap_count = _block_bootstrap_ic_ci(
        work.reset_index(drop=True),
        factor,
        label,
        effective_block_size,
        n_bootstrap,
        random_seed,
    )
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
    min_block_warning = len(block_array) < int(min_time_blocks)
    warnings = ["exploratory factor test", "multiple testing risk", "p_value_is_approximate"]
    if inferred_horizon is not None and inferred_horizon > 1:
        warnings.append("overlapping_forward_returns")
    if min_block_warning:
        warnings.append("min_block_count_warning")
    return {
        "factor": factor,
        "label": label,
        "sample_count": count,
        "pearson_ic": pearson,
        "spearman_rank_ic": spearman,
        "p_value": p_value,
        "approximate_p_value": approximate_p_value,
        "p_value_note": "approximate; ignores serial dependence, heteroskedasticity and overlapping forward labels",
        "ic_bootstrap_ci_low": ci_low,
        "ic_bootstrap_ci_high": ci_high,
        "block_size": effective_block_size,
        "bootstrap_sample_count": bootstrap_count,
        "ic_by_time_block": json.dumps(block_values, sort_keys=True),
        "ic_mean_by_block": block_mean,
        "ic_std_by_block": block_std,
        "ic_positive_ratio": positive_ratio,
        "stability_score": stability,
        "time_block_count": int(len(block_array)),
        "min_block_count_warning": bool(min_block_warning),
        "warning": "; ".join(warnings),
    }


def build_factor_ic_summary(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    label: str = "fwd_ret_10_side_adj",
    factors: list[str] | None = None,
    *,
    n_bootstrap: int = 200,
    random_seed: int | None = 0,
) -> pd.DataFrame:
    if features.empty or labels.empty or label not in labels.columns:
        return pd.DataFrame()
    samples = features.merge(labels[["event_id", label]], on="event_id", how="inner")
    chosen = factors or [name for name in model_input_features() if name in samples.columns]
    horizon = _infer_horizon_bars(label)
    return pd.DataFrame(
        [
            factor_ic(
                samples,
                factor,
                label,
                horizon_bars=horizon,
                n_bootstrap=n_bootstrap,
                random_seed=random_seed,
            )
            for factor in chosen
        ]
    )
