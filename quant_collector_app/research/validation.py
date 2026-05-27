from __future__ import annotations

import math
from typing import Any

import pandas as pd


def purged_embargo_split(
    samples: pd.DataFrame,
    time_col: str,
    train_ratio: float,
    purge_bars: int,
    embargo_bars: int,
) -> dict[str, Any]:
    if not isinstance(samples, pd.DataFrame):
        raise ValueError("samples must be a pandas DataFrame")
    if time_col not in samples.columns:
        raise ValueError(f"Missing time column: {time_col}")
    ordered = samples.copy()
    ordered["_validation_time"] = pd.to_datetime(ordered[time_col], errors="coerce")
    ordered = ordered.sort_values("_validation_time", kind="stable").drop(columns="_validation_time").reset_index(drop=True)
    count = len(ordered)
    split_at = min(count, max(0, int(count * float(train_ratio))))
    purge = max(0, int(purge_bars))
    embargo = max(0, int(embargo_bars))
    train_end = max(0, split_at - purge)
    test_start = min(count, split_at + embargo)
    train = ordered.iloc[:train_end].copy()
    purged = ordered.iloc[train_end:split_at].copy()
    embargoed = ordered.iloc[split_at:test_start].copy()
    test = ordered.iloc[test_start:].copy()
    warning = "insufficient_samples_after_purge_embargo" if train.empty or test.empty else None
    return {
        "train": train,
        "test": test,
        "purged": purged,
        "embargoed": embargoed,
        "warning": warning,
        "split_spec": {
            "method": "purged_chronological_split",
            "time_col": time_col,
            "train_ratio": float(train_ratio),
            "purge_bars": purge,
            "embargo_bars": embargo,
            "n_total": count,
            "n_train": len(train),
            "n_test": len(test),
            "n_purged": len(purged),
            "n_embargoed": len(embargoed),
        },
    }


def minimum_sample_gate(n_samples: int | None, min_samples: int) -> dict[str, Any]:
    if n_samples is None:
        return {"passed": False, "status": "unavailable", "warning": "sample_count_unavailable"}
    count = int(n_samples)
    minimum = int(min_samples)
    if count < minimum:
        return {
            "passed": False,
            "status": "rejected_low_sample",
            "warning": f"low_sample: {count} < {minimum}",
        }
    return {"passed": True, "status": "passed", "warning": None}


def _finite_metric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def oos_degradation_gate(
    insample_metric: float | None,
    oos_metric: float | None,
    max_degradation_ratio: float,
) -> dict[str, Any]:
    insample = _finite_metric(insample_metric)
    oos = _finite_metric(oos_metric)
    if insample is None or oos is None or insample == 0:
        return {
            "passed": False,
            "status": "unavailable",
            "degradation_ratio": None,
            "warning": "metric_unavailable",
        }
    ratio = (insample - oos) / abs(insample)
    passed = ratio <= float(max_degradation_ratio)
    return {
        "passed": passed,
        "status": "passed" if passed else "rejected_oos_degradation",
        "degradation_ratio": float(ratio),
        "warning": None if passed else "oos_degradation_exceeds_limit",
    }


def validate_candidate_rule(
    *,
    n_train: int | None,
    n_test: int | None,
    insample_metric: float | None,
    oos_metric: float | None,
    fdr_pass: bool | None,
    q_value: float | None,
    min_samples: int,
    max_degradation_ratio: float,
) -> dict[str, Any]:
    warnings: list[str] = []
    train_gate = minimum_sample_gate(n_train, min_samples)
    test_gate = minimum_sample_gate(n_test, min_samples)
    degradation_gate = oos_degradation_gate(insample_metric, oos_metric, max_degradation_ratio)
    for gate in (train_gate, test_gate, degradation_gate):
        if gate.get("warning"):
            warnings.append(str(gate["warning"]))
    if n_train is None or n_test is None:
        status = "unavailable"
    elif not train_gate["passed"] or not test_gate["passed"]:
        status = "rejected_low_sample"
    elif degradation_gate["status"] == "unavailable":
        status = "unavailable"
    elif fdr_pass is None or q_value is None:
        warnings.append("fdr_unavailable")
        status = "unavailable"
    elif not bool(fdr_pass):
        warnings.append("fdr_not_passed")
        status = "rejected_fdr"
    elif not degradation_gate["passed"]:
        status = "rejected_oos_degradation"
    else:
        status = "validated_candidate"
    return {
        "validation_status": status,
        "validation_warnings": warnings,
        "n_train": n_train,
        "n_test": n_test,
        "insample_metric": _finite_metric(insample_metric),
        "oos_metric": _finite_metric(oos_metric),
        "degradation_ratio": degradation_gate["degradation_ratio"],
        "q_value": q_value,
        "fdr_pass": fdr_pass,
        "minimum_sample_gate": {"train": train_gate, "test": test_gate},
        "oos_degradation_gate": degradation_gate,
    }


def summarize_rule_validation(validations: pd.DataFrame | list[dict[str, Any]]) -> dict[str, Any]:
    frame = validations if isinstance(validations, pd.DataFrame) else pd.DataFrame(validations)
    if frame.empty or "validation_status" not in frame.columns:
        return {"total_rules": 0, "status_counts": {}, "validated_candidate_count": 0}
    counts = {str(key): int(value) for key, value in frame["validation_status"].value_counts().items()}
    return {
        "total_rules": int(len(frame)),
        "status_counts": counts,
        "validated_candidate_count": counts.get("validated_candidate", 0),
        "exploratory_only": counts.get("validated_candidate", 0) == 0,
    }


__all__ = [
    "minimum_sample_gate",
    "oos_degradation_gate",
    "purged_embargo_split",
    "summarize_rule_validation",
    "validate_candidate_rule",
]
