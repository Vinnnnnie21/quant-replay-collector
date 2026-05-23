from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _clean_labels(df: pd.DataFrame, label_column: str) -> pd.Series:
    if df is None or df.empty or label_column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[label_column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def _safe_float(value) -> float | None:
    try:
        x = float(value)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def build_random_event_baseline(
    features: pd.DataFrame,
    label_column: str = "fwd_ret_10_side_adj",
    condition_columns: list[str] | None = None,
    sample_size: int | None = None,
    n_iter: int = 500,
    random_seed: int = 42,
) -> dict:
    if features is None or features.empty or label_column not in features.columns:
        return {
            "skipped": True,
            "baseline_type": "event_label_resampling",
            "reason": f"missing label_column: {label_column}",
            "label_column": label_column,
            "limitations": ["This baseline resamples existing event labels and is not a true random event baseline."],
        }
    source = features.copy()
    condition_note = None
    if condition_columns:
        missing = [c for c in condition_columns if c not in source.columns]
        if missing:
            return {
                "skipped": True,
                "baseline_type": "event_label_resampling",
                "reason": f"missing condition_columns: {missing}",
                "label_column": label_column,
                "limitations": ["This baseline resamples existing event labels and is not a true random event baseline."],
            }
        source = source.dropna(subset=condition_columns)
    else:
        condition_note = "condition_columns currently not applied"
    labels = _clean_labels(source, label_column)
    if labels.empty:
        return {
            "skipped": True,
            "baseline_type": "event_label_resampling",
            "reason": "no valid label values",
            "label_column": label_column,
            "limitations": ["This baseline resamples existing event labels and is not a true random event baseline."],
        }

    n = len(labels)
    size = int(sample_size or n)
    size = max(1, min(size, n))
    warnings = []
    if size < 30:
        warnings.append("sample size below 30")
    if size == n:
        warnings.append("sample_size equals available labels; baseline dispersion may be near zero.")
    if condition_note:
        warnings.append(condition_note)
    rng = np.random.default_rng(random_seed)
    values = labels.to_numpy(dtype=float)
    means = []
    medians = []
    win_rates = []
    iterations = max(1, int(n_iter))
    for _ in range(iterations):
        sample = rng.choice(values, size=size, replace=False if size <= n else True)
        means.append(float(np.nanmean(sample)))
        medians.append(float(np.nanmedian(sample)))
        win_rates.append(float(np.nanmean(sample > 0) * 100.0))

    means_arr = np.asarray(means, dtype=float)
    return {
        "skipped": False,
        "baseline_type": "event_label_resampling",
        "label_column": label_column,
        "n_iter": iterations,
        "sample_size": size,
        "available_label_count": int(n),
        "baseline_mean_distribution_mean": _safe_float(np.nanmean(means_arr)),
        "baseline_mean_distribution_std": _safe_float(np.nanstd(means_arr, ddof=1)) if len(means_arr) > 1 else 0.0,
        "baseline_median_distribution_mean": _safe_float(np.nanmean(medians)),
        "baseline_win_rate_distribution_mean": _safe_float(np.nanmean(win_rates)),
        "baseline_q05": _safe_float(np.nanquantile(means_arr, 0.05)),
        "baseline_q95": _safe_float(np.nanquantile(means_arr, 0.95)),
        "warning": "; ".join(warnings) if warnings else None,
        "warnings": warnings,
        "limitations": ["This baseline resamples existing event labels and is not a true random event baseline."],
    }


def build_random_bar_baseline(
    kline_df: pd.DataFrame,
    horizon: int = 10,
    side: str = "LONG",
    sample_size: int = 100,
    n_iter: int = 500,
    random_seed: int = 42,
    min_start_index: int = 50,
) -> dict:
    baseline_type = "random_bar_forward_return"
    if kline_df is None or kline_df.empty or "close" not in kline_df.columns:
        return {"skipped": True, "baseline_type": baseline_type, "reason": "missing kline close data"}
    df = kline_df.copy()
    if "bar_index" in df.columns:
        df = df.sort_values("bar_index")
    df = df.reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    h = max(1, int(horizon))
    start = max(0, int(min_start_index))
    max_start = len(close) - h - 1
    if max_start < start:
        return {
            "skipped": True,
            "baseline_type": baseline_type,
            "reason": "not enough kline rows for horizon and min_start_index",
            "horizon": h,
            "available_rows": int(len(close)),
        }
    future = close.shift(-h)
    side_value = str(side or "LONG").upper()
    if side_value == "SHORT":
        forward = close / future - 1.0
    else:
        forward = future / close - 1.0
        side_value = "LONG"
    valid = forward.iloc[start : max_start + 1].dropna()
    if valid.empty:
        return {"skipped": True, "baseline_type": baseline_type, "reason": "no valid forward returns", "horizon": h}
    n = len(valid)
    size = max(1, min(int(sample_size), n))
    warnings = []
    if size == n:
        warnings.append("sample_size equals available random bars; baseline dispersion may be near zero.")
    rng = np.random.default_rng(random_seed)
    values = valid.to_numpy(dtype=float)
    means = []
    win_rates = []
    iterations = max(1, int(n_iter))
    for _ in range(iterations):
        sample = rng.choice(values, size=size, replace=False if size <= n else True)
        means.append(float(np.nanmean(sample)))
        win_rates.append(float(np.nanmean(sample > 0) * 100.0))
    means_arr = np.asarray(means, dtype=float)
    return {
        "skipped": False,
        "baseline_type": baseline_type,
        "side": side_value,
        "horizon": h,
        "n_iter": iterations,
        "sample_size": int(size),
        "available_bar_count": int(n),
        "baseline_mean_distribution_mean": _safe_float(np.nanmean(means_arr)),
        "baseline_mean_distribution_std": _safe_float(np.nanstd(means_arr, ddof=1)) if len(means_arr) > 1 else 0.0,
        "baseline_win_rate_distribution_mean": _safe_float(np.nanmean(win_rates)),
        "baseline_q05": _safe_float(np.nanquantile(means_arr, 0.05)),
        "baseline_q95": _safe_float(np.nanquantile(means_arr, 0.95)),
        "warnings": warnings,
        "limitations": ["Requires full session kline data. Event-window-only sources are not a complete market baseline."],
    }


def compare_events_to_baseline(
    event_labels: pd.DataFrame,
    baseline_result: dict,
    label_column: str = "fwd_ret_10_side_adj",
) -> dict:
    labels = _clean_labels(event_labels, label_column)
    if labels.empty:
        return {
            "event_sample_count": 0,
            "event_mean": None,
            "event_median": None,
            "event_win_rate_pct": None,
            "baseline_mean": baseline_result.get("baseline_mean_distribution_mean"),
            "baseline_q05": baseline_result.get("baseline_q05"),
            "baseline_q95": baseline_result.get("baseline_q95"),
            "event_mean_above_baseline_q95": False,
            "interpretation_warning": "no valid event labels; event label resampling is not a true random market event baseline",
        }
    event_mean = float(labels.mean())
    baseline_q95 = baseline_result.get("baseline_q95")
    return {
        "event_sample_count": int(len(labels)),
        "event_mean": _safe_float(event_mean),
        "event_median": _safe_float(labels.median()),
        "event_win_rate_pct": _safe_float((labels > 0).mean() * 100.0),
        "baseline_mean": baseline_result.get("baseline_mean_distribution_mean"),
        "baseline_q05": baseline_result.get("baseline_q05"),
        "baseline_q95": baseline_q95,
        "event_mean_above_baseline_q95": bool(baseline_q95 is not None and event_mean > float(baseline_q95)),
        "interpretation_warning": "This is event label resampling, not a complete random market event baseline; it is not causal evidence or investment advice.",
    }
