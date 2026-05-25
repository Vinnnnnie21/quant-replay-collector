from __future__ import annotations

import hashlib
import itertools
import json
import math
import operator

import pandas as pd

from .bootstrap import bootstrap_mean_ci
from .factor_audit import forbidden_feature_columns
from .feature_registry import feature_registry_frame, model_input_features
from .walk_forward import chronological_train_test_split


OPS = {"<=": operator.le, ">=": operator.ge, "<": operator.lt, ">": operator.gt, "==": operator.eq}
DEFAULT_RULE_FACTORS = [
    "pre_ret_10",
    "lower_wick_atr_ratio",
    "close_position",
    "volume_zscore_20",
    "panic_drop_score",
    "false_breakdown_score",
]


def validate_rule_features(factors: list[str]) -> None:
    blocked = forbidden_feature_columns(factors)
    allowed = set(model_input_features())
    unavailable = [factor for factor in factors if factor not in allowed]
    if blocked or unavailable:
        raise ValueError(f"Rule search received forbidden or unregistered features: {blocked + unavailable}")


def _condition_mask(data: pd.DataFrame, conditions: list[dict]) -> pd.Series:
    mask = pd.Series(True, index=data.index)
    for condition in conditions:
        column, operation, value = condition["column"], condition["op"], condition["value"]
        if column not in data.columns or operation not in OPS:
            return pd.Series(False, index=data.index)
        left = pd.to_numeric(data[column], errors="coerce") if operation != "==" else data[column]
        mask &= OPS[operation](left, value).fillna(False)
    return mask


def _rule_metrics(data: pd.DataFrame, conditions: list[dict], label: str) -> dict:
    values = pd.to_numeric(data[_condition_mask(data, conditions)].get(label), errors="coerce").dropna()
    ci = bootstrap_mean_ci(values)
    positive, negative = values[values > 0], values[values < 0]
    profit_factor = float(positive.sum() / abs(negative.sum())) if len(negative) and negative.sum() != 0 else math.nan
    return {
        "sample_count": int(len(values)),
        "coverage": float(len(values) / max(len(data), 1) * 100.0),
        "mean_return": float(values.mean()) if len(values) else math.nan,
        "median_return": float(values.median()) if len(values) else math.nan,
        "win_rate": float((values > 0).mean() * 100.0) if len(values) else math.nan,
        "profit_factor": profit_factor,
        "bootstrap_ci_low": ci["ci_low"],
        "bootstrap_ci_high": ci["ci_high"],
    }


def _thresholds(train: pd.DataFrame, factors: list[str]) -> list[dict]:
    conditions = []
    for factor in factors:
        values = pd.to_numeric(train[factor], errors="coerce").dropna()
        if len(values) < 2 or values.nunique() < 2:
            continue
        for value in sorted(set(float(x) for x in values.quantile([0.2, 0.4, 0.6, 0.8]).dropna())):
            conditions.append({"column": factor, "op": "<=", "value": value})
            conditions.append({"column": factor, "op": ">=", "value": value})
    return conditions


def _readable(conditions: list[dict], label: str) -> str:
    parts = [f"{item['column']} {item['op']} {item['value']:.6g}" for item in conditions]
    return f"IF {' AND '.join(parts)} THEN {label} positive"


def search_rules(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    label: str = "fwd_ret_10_side_adj",
    factors: list[str] | None = None,
    min_samples: int = 30,
    max_depth: int = 3,
    max_rules: int = 200,
) -> pd.DataFrame:
    if features.empty or labels.empty or label not in labels.columns:
        return pd.DataFrame()
    samples = features.merge(labels[["event_id", label]], on="event_id", how="inner")
    selected = factors or [factor for factor in DEFAULT_RULE_FACTORS if factor in samples.columns]
    validate_rule_features(selected)
    train, test = chronological_train_test_split(samples)
    base_conditions = _thresholds(train, selected)
    candidates = []
    maximum_depth = min(3, max(1, int(max_depth)))
    for depth in range(1, maximum_depth + 1):
        for combination in itertools.combinations(base_conditions, depth):
            columns = [item["column"] for item in combination]
            if len(set(columns)) != len(columns):
                continue
            candidates.append(list(combination))
            if len(candidates) >= max_rules * 20:
                break
        if len(candidates) >= max_rules * 20:
            break
    rows = []
    for conditions in candidates:
        train_metrics = _rule_metrics(train, conditions, label)
        if train_metrics["sample_count"] < int(min_samples):
            continue
        test_metrics = _rule_metrics(test, conditions, label)
        train_score = train_metrics["mean_return"] * math.sqrt(train_metrics["sample_count"]) if math.isfinite(train_metrics["mean_return"]) else math.nan
        test_score = test_metrics["mean_return"] * math.sqrt(test_metrics["sample_count"]) if math.isfinite(test_metrics["mean_return"]) else math.nan
        degradation = (
            (train_score - test_score) / abs(train_score) * 100.0
            if math.isfinite(train_score) and train_score != 0 and math.isfinite(test_score)
            else math.nan
        )
        conditions_json = json.dumps(conditions, ensure_ascii=False, sort_keys=True)
        rule_id = "rule_" + hashlib.sha1(conditions_json.encode("utf-8")).hexdigest()[:12]
        rows.append(
            {
                "rule_id": rule_id,
                "conditions_json": conditions_json,
                "readable_rule": _readable(conditions, label),
                **train_metrics,
                "train_score": train_score,
                "test_sample_count": test_metrics["sample_count"],
                "test_mean_return": test_metrics["mean_return"],
                "test_win_rate": test_metrics["win_rate"],
                "test_score": test_score,
                "degradation_pct": degradation,
                "stability_score": (
                    test_metrics["mean_return"] / train_metrics["mean_return"]
                    if math.isfinite(test_metrics["mean_return"]) and train_metrics["mean_return"] not in (0, math.nan)
                    else math.nan
                ),
                "warning": (
                    "candidate hypothesis only; test sample is small; multiple testing risk"
                    if test_metrics["sample_count"] < min_samples
                    else "candidate hypothesis only; multiple testing risk"
                ),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["train_score", "sample_count"], ascending=[False, False]).head(max_rules).reset_index(drop=True)
