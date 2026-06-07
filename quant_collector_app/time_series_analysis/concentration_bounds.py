from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd


DISCLAIMER = (
    "Chebyshev is a distribution-free conservative upper bound. It is not a prediction "
    "probability, not trading advice, and not a trading signal."
)


def _validate_positive_k(k: float) -> float:
    value = float(k)
    if not np.isfinite(value) or value <= 0:
        raise ValueError("k must be a positive finite number")
    return value


def chebyshev_bound(k: float) -> float:
    """Return the two-sided Chebyshev upper bound P(|X - mu| >= k sigma)."""
    value = _validate_positive_k(k)
    return 1.0 / (value * value)


def cantelli_bound(k: float) -> float:
    """Return Cantelli's one-sided downside bound P(X - mu <= -k sigma)."""
    value = _validate_positive_k(k)
    return 1.0 / (1.0 + value * value)


def _clean_returns(returns: Iterable[Any]) -> tuple[pd.Series, list[str]]:
    values = pd.to_numeric(pd.Series(list(returns)), errors="coerce").replace([np.inf, -np.inf], np.nan)
    nan_count = int(values.isna().sum())
    cleaned = values.dropna().astype(float)
    warnings: list[str] = []
    if nan_count:
        warnings.append("nan_values_dropped")
    if len(cleaned) < 2:
        warnings.append("insufficient_sample")
    return cleaned.reset_index(drop=True), warnings


def _return_stats(returns: Iterable[Any]) -> tuple[pd.Series, int, float, float, list[str]]:
    cleaned, warnings = _clean_returns(returns)
    sample_size = int(len(cleaned))
    mean = float(cleaned.mean()) if sample_size else float("nan")
    std = float(cleaned.std(ddof=1)) if sample_size >= 2 else float("nan")
    if sample_size >= 2 and (not np.isfinite(std) or std <= 0.0):
        warnings.append("zero_std")
    return cleaned, sample_size, mean, std, warnings


def empirical_sigma_exceedance(returns: Iterable[Any], k: float) -> float:
    """Return the observed two-sided k-sigma exceedance share for returns."""
    value = _validate_positive_k(k)
    cleaned, sample_size, mean, std, _warnings = _return_stats(returns)
    if sample_size < 2 or not np.isfinite(std) or std <= 0.0:
        return float("nan")
    exceedance = (cleaned - mean).abs() >= value * std
    return float(exceedance.mean())


def _empirical_downside_exceedance(cleaned: pd.Series, mean: float, std: float, k: float) -> float:
    if len(cleaned) < 2 or not np.isfinite(std) or std <= 0.0:
        return float("nan")
    exceedance = cleaned - mean <= -float(k) * std
    return float(exceedance.mean())


def summarize_concentration_bounds(
    returns: Iterable[Any],
    ks: tuple[int | float, ...] = (2, 3, 4, 5),
) -> dict[str, Any]:
    """Summarize conservative concentration bounds for a return series.

    Input must be returns, not prices. The output is a diagnostic only.
    """
    cleaned, sample_size, mean, std, warnings = _return_stats(returns)
    unique_warnings = list(dict.fromkeys(warnings))
    rows: list[dict[str, Any]] = []
    for k in ks:
        value = _validate_positive_k(k)
        row_warnings = list(unique_warnings)
        rows.append(
            {
                "k": value,
                "chebyshev_bound": chebyshev_bound(value),
                "cantelli_downside_bound": cantelli_bound(value),
                "empirical_two_sided_exceedance": empirical_sigma_exceedance(cleaned, value),
                "empirical_downside_exceedance": _empirical_downside_exceedance(cleaned, mean, std, value),
                "sample_size": sample_size,
                "mean": mean,
                "std": std,
                "warnings": row_warnings,
            }
        )
    return {
        "diagnostic_name": "concentration_bounds",
        "input_series": "returns",
        "sample_size": sample_size,
        "mean": mean,
        "std": std,
        "warnings": unique_warnings,
        "disclaimer": DISCLAIMER,
        "rows": rows,
    }


__all__ = [
    "cantelli_bound",
    "chebyshev_bound",
    "empirical_sigma_exceedance",
    "summarize_concentration_bounds",
]
