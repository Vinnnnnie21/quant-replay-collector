from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _clean(values) -> pd.Series:
    return pd.to_numeric(pd.Series(values), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def skewness(values) -> float | None:
    clean = _clean(values)
    return float(clean.skew()) if len(clean) >= 3 else None


def excess_kurtosis(values) -> float | None:
    clean = _clean(values)
    return float(clean.kurt()) if len(clean) >= 4 else None


def jarque_bera_test(values) -> dict:
    clean = _clean(values)
    count = int(len(clean))
    if count < 4:
        return {
            "statistic": None,
            "p_value": None,
            "p_value_method": "unavailable",
            "normality_rejected": False,
            "warning": "insufficient sample for Jarque-Bera test",
        }
    skew = float(clean.skew())
    kurt = float(clean.kurt())
    statistic = float(count / 6.0 * (skew * skew + kurt * kurt / 4.0))
    # JB asymptotically follows chi-square with two degrees of freedom.
    # For df=2 the chi-square survival function has the closed form exp(-x / 2).
    p_value = math.exp(-statistic / 2.0)
    return {
        "statistic": statistic,
        "p_value": p_value,
        "p_value_method": "chi_square_df2_closed_form",
        "normality_rejected": bool(p_value < 0.05),
        "warning": None,
    }


def quantile_summary(values) -> dict:
    clean = _clean(values)
    if clean.empty:
        return {key: None for key in ("q01", "q05", "q25", "q75", "q95", "q99")}
    return {f"q{int(level * 100):02d}": float(clean.quantile(level)) for level in (0.01, 0.05, 0.25, 0.75, 0.95, 0.99)}


def tail_summary(values) -> dict:
    clean = _clean(values)
    if clean.empty:
        return {"left_tail_mean_5pct": None, "right_tail_mean_5pct": None, "tail_asymmetry": None}
    q05 = clean.quantile(0.05)
    q95 = clean.quantile(0.95)
    left = float(clean[clean <= q05].mean())
    right = float(clean[clean >= q95].mean())
    return {"left_tail_mean_5pct": left, "right_tail_mean_5pct": right, "tail_asymmetry": abs(left) / right if right > 0 else None}


def descriptive_stats(values) -> dict:
    clean = _clean(values)
    if clean.empty:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "std": None,
            "skewness": None,
            "excess_kurtosis": None,
            "min": None,
            "max": None,
            **quantile_summary(clean),
            **jarque_bera_test(clean),
            "heavy_tail_warning": False,
        }
    kurt = excess_kurtosis(clean)
    jb = jarque_bera_test(clean)
    return {
        "n": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "std": float(clean.std(ddof=1)) if len(clean) > 1 else 0.0,
        "skewness": skewness(clean),
        "excess_kurtosis": kurt,
        "min": float(clean.min()),
        "max": float(clean.max()),
        **quantile_summary(clean),
        "jb_statistic": jb["statistic"],
        "jb_p_value": jb["p_value"],
        "jb_p_value_method": jb["p_value_method"],
        "normality_rejected": jb["normality_rejected"],
        "heavy_tail_warning": bool(kurt is not None and kurt > 1.0),
        **tail_summary(clean),
    }


def normality_warning(values) -> str | None:
    result = descriptive_stats(values)
    if result["normality_rejected"] or result["heavy_tail_warning"]:
        return "return distribution departs from normality or displays heavy-tail behavior"
    return None
