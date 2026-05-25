from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _values(values: Any) -> np.ndarray:
    series = pd.to_numeric(pd.Series(values, dtype="object"), errors="coerce").dropna()
    return series.to_numpy(dtype=float)


def _empty_result(warning: str) -> dict:
    return {
        "estimate": math.nan,
        "ci_low": math.nan,
        "ci_high": math.nan,
        "sample_count": 0,
        "warning": warning,
    }


def bootstrap_mean_ci(values, n_boot: int = 1000, ci: float = 0.95, random_state: int = 42) -> dict:
    observations = _values(values)
    if not len(observations):
        return _empty_result("empty or all-NaN sample")
    warning = "small sample; interval is unstable" if len(observations) < 30 else ""
    rng = np.random.default_rng(random_state)
    draws = rng.choice(observations, size=(max(1, int(n_boot)), len(observations)), replace=True).mean(axis=1)
    alpha = max(0.0, min(1.0, 1.0 - float(ci))) / 2.0
    low, high = np.quantile(draws, [alpha, 1.0 - alpha])
    return {
        "estimate": float(np.mean(observations)),
        "ci_low": float(low),
        "ci_high": float(high),
        "sample_count": int(len(observations)),
        "warning": warning,
    }


def bootstrap_win_rate_ci(values, n_boot: int = 1000, ci: float = 0.95, random_state: int = 42) -> dict:
    raw = pd.Series(values, dtype="object").dropna()
    if raw.empty:
        return _empty_result("empty or all-NaN sample")
    if pd.api.types.is_bool_dtype(raw):
        binary = raw.astype(float).to_numpy()
    else:
        numeric = pd.to_numeric(raw, errors="coerce").dropna()
        if numeric.empty:
            return _empty_result("empty or all-NaN sample")
        binary = (numeric.to_numpy(dtype=float) > 0).astype(float)
    result = bootstrap_mean_ci(binary, n_boot=n_boot, ci=ci, random_state=random_state)
    result["estimate"] *= 100.0
    result["ci_low"] *= 100.0
    result["ci_high"] *= 100.0
    return result
