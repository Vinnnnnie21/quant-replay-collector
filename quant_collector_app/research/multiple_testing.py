from __future__ import annotations

import math
from typing import Iterable

import pandas as pd


def _valid_p_value(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        return None
    return number


def benjamini_hochberg(p_values: Iterable[float | None], alpha: float = 0.1) -> list[dict]:
    values = list(p_values)
    results = [
        {"p_value": _valid_p_value(value), "q_value": None, "fdr_pass": False, "fdr_status": "unavailable"}
        for value in values
    ]
    valid = [(index, row["p_value"]) for index, row in enumerate(results) if row["p_value"] is not None]
    if not valid:
        return results
    ordered = sorted(valid, key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: list[float] = [1.0] * count
    running = 1.0
    for offset in range(count - 1, -1, -1):
        _index, p_value = ordered[offset]
        rank = offset + 1
        running = min(running, float(p_value) * count / rank)
        adjusted[offset] = min(1.0, running)
    for (original_index, p_value), q_value in zip(ordered, adjusted):
        results[original_index] = {
            "p_value": p_value,
            "q_value": q_value,
            "fdr_pass": bool(q_value <= float(alpha)),
            "fdr_status": "available",
        }
    return results


def multiple_testing_warning(num_rules: int, threshold: int = 20) -> str | None:
    if int(num_rules) > int(threshold):
        return (
            "multiple_testing_warning: many candidate rules were tested; "
            "uncorrected best p-values are not reliable conclusions."
        )
    return None


def add_fdr_results(
    candidate_rules: pd.DataFrame,
    p_value_key: str = "p_value",
    alpha: float = 0.1,
) -> pd.DataFrame:
    result = candidate_rules.copy()
    if result.empty:
        result["q_value"] = pd.Series(dtype=float)
        result["fdr_pass"] = pd.Series(dtype=bool)
        result["fdr_status"] = pd.Series(dtype=str)
        result["multiple_testing_warning"] = pd.Series(dtype=str)
        return result
    values = result[p_value_key].tolist() if p_value_key in result.columns else [None] * len(result)
    adjusted = benjamini_hochberg(values, alpha=alpha)
    result["q_value"] = [row["q_value"] for row in adjusted]
    result["fdr_pass"] = [row["fdr_pass"] for row in adjusted]
    result["fdr_status"] = [row["fdr_status"] for row in adjusted]
    result["multiple_testing_warning"] = multiple_testing_warning(len(result))
    return result


__all__ = [
    "add_fdr_results",
    "benjamini_hochberg",
    "multiple_testing_warning",
]
