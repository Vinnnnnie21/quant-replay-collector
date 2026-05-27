from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .context_features import FORBIDDEN_CONTEXT_TOKENS


ENTRY_ACTIONS = frozenset({"OPEN_LONG", "OPEN_SHORT"})


def _actions(observations: pd.DataFrame) -> pd.Series:
    if not isinstance(observations, pd.DataFrame) or "user_action" not in observations.columns:
        raise ValueError("observations requires user_action")
    return observations["user_action"].astype(str).str.upper()


def summarize_action_frequency(observations: pd.DataFrame) -> pd.DataFrame:
    actions = _actions(observations)
    columns = ["user_action", "count", "frequency"]
    if actions.empty:
        return pd.DataFrame(columns=columns)
    counts = actions.value_counts(dropna=False).rename_axis("user_action").reset_index(name="count")
    counts["frequency"] = counts["count"] / len(actions)
    return counts[columns]


def compute_behavior_entropy(observations: pd.DataFrame) -> dict[str, Any]:
    frequency = summarize_action_frequency(observations)
    if frequency.empty:
        return {
            "behavior_entropy": None,
            "normalized_entropy": None,
            "sample_count": 0,
            "descriptive_only": True,
        }
    probabilities = frequency["frequency"].to_numpy(dtype=float)
    entropy = float(-sum(value * math.log2(value) for value in probabilities if value > 0))
    maximum = math.log2(len(probabilities)) if len(probabilities) > 1 else 0.0
    return {
        "behavior_entropy": entropy,
        "normalized_entropy": float(entropy / maximum) if maximum else 0.0,
        "sample_count": int(frequency["count"].sum()),
        "descriptive_only": True,
    }


def _profile_field(profile: Any, name: str, default: Any = None) -> Any:
    if isinstance(profile, dict):
        return profile.get(name, default)
    return getattr(profile, name, default)


def _profile_status(profile: Any) -> str:
    if profile is None:
        return "UNDECLARED"
    mode = _profile_field(profile, "mode")
    if mode and str(mode).upper() == "UNDECLARED":
        return "UNDECLARED"
    return str(mode or "DECLARED").upper()


def compute_profile_adherence(observations: pd.DataFrame, profile: Any = None) -> dict[str, Any]:
    status = _profile_status(profile)
    if status == "UNDECLARED":
        return {
            "profile_status": "UNDECLARED",
            "descriptive_only": True,
            "violation_count": None,
            "adherence_rate": None,
            "evaluated_action_count": 0,
            "exit_discipline_evaluated": False,
            "strategy_effectiveness_evaluated": False,
        }
    actions = _actions(observations)
    entries = observations.loc[actions.isin(ENTRY_ACTIONS)].copy()
    entry_actions = actions.loc[entries.index]
    allowed_sides = _profile_field(profile, "allowed_sides")
    allowed_symbols = _profile_field(profile, "allowed_symbols")
    allowed_intervals = _profile_field(profile, "allowed_intervals")
    allowed_sides = {str(side).upper() for side in allowed_sides} if allowed_sides else None
    allowed_symbols = {str(symbol).upper() for symbol in allowed_symbols} if allowed_symbols else None
    allowed_intervals = {str(interval) for interval in allowed_intervals} if allowed_intervals else None
    violations: list[dict[str, Any]] = []
    for index, row in entries.iterrows():
        action = str(entry_actions.loc[index]).upper()
        side = "LONG" if action == "OPEN_LONG" else "SHORT"
        reasons: list[str] = []
        if allowed_sides is not None and side not in allowed_sides:
            reasons.append("side_not_allowed")
        if allowed_symbols is not None and str(row.get("symbol", "")).upper() not in allowed_symbols:
            reasons.append("symbol_not_allowed")
        if allowed_intervals is not None and str(row.get("interval", "")) not in allowed_intervals:
            reasons.append("interval_not_allowed")
        if reasons:
            violations.append({"sample_id": row.get("sample_id"), "reasons": reasons})
    evaluated = len(entries)
    rate = (evaluated - len(violations)) / evaluated if evaluated else None
    return {
        "profile_status": status,
        "descriptive_only": False,
        "violation_count": len(violations),
        "violations": violations,
        "adherence_rate": float(rate) if rate is not None else None,
        "evaluated_action_count": evaluated,
        "exit_discipline_evaluated": False,
        "strategy_effectiveness_evaluated": False,
    }


def _state_features(context_features: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(context_features, pd.DataFrame) or "sample_id" not in context_features.columns:
        raise ValueError("context_features requires sample_id")
    if {"feature_name", "feature_value"} <= set(context_features.columns):
        invalid = context_features["feature_name"].astype(str).str.lower().map(
            lambda name: any(token in name for token in FORBIDDEN_CONTEXT_TOKENS)
        )
        if invalid.any():
            raise ValueError("Behavior state cannot use future or outcome fields.")
        return context_features.pivot_table(
            index="sample_id",
            columns="feature_name",
            values="feature_value",
            aggfunc="last",
        ).reset_index()
    invalid_columns = [
        column
        for column in context_features.columns
        if column != "sample_id"
        and any(token in str(column).lower() for token in FORBIDDEN_CONTEXT_TOKENS)
    ]
    if invalid_columns:
        raise ValueError(f"Behavior state cannot use future or outcome fields: {invalid_columns}")
    return context_features.copy()


def compute_state_action_table(observations: pd.DataFrame, context_features: pd.DataFrame) -> pd.DataFrame:
    _actions(observations)
    states = _state_features(context_features)
    data = observations.merge(states, on="sample_id", how="inner")
    regime_columns = [
        column for column in ("volatility_regime", "trend_regime", "time_session") if column in data.columns
    ]
    if not regime_columns:
        data = data.copy()
        data["state"] = "ALL"
        regime_columns = ["state"]
    table = (
        data.groupby(regime_columns + ["user_action"], dropna=False)
        .size()
        .reset_index(name="count")
    )
    table["frequency_in_state"] = table["count"] / table.groupby(regime_columns)["count"].transform("sum")
    return table


def summarize_behavior_model(
    observations: pd.DataFrame,
    context_features: pd.DataFrame,
    profile: Any = None,
    *,
    min_sample_count: int = 30,
) -> dict[str, Any]:
    frequency = summarize_action_frequency(observations)
    entropy = compute_behavior_entropy(observations)
    state_action = compute_state_action_table(observations, context_features)
    adherence = compute_profile_adherence(observations, profile)
    concentration = (
        float(state_action.groupby([column for column in state_action.columns if column not in {"user_action", "count", "frequency_in_state"}])["frequency_in_state"].max().mean())
        if not state_action.empty
        else None
    )
    sample_count = int(len(observations))
    return {
        "sample_count": sample_count,
        "low_sample_warning": sample_count < int(min_sample_count),
        "action_frequency": frequency.to_dict("records"),
        "state_action_table": state_action.to_dict("records"),
        "state_action_concentration_mean": concentration,
        "behavior_entropy": entropy["behavior_entropy"],
        "normalized_entropy": entropy["normalized_entropy"],
        "profile_adherence": adherence,
        "profile_status": adherence["profile_status"],
        "descriptive_only": adherence["descriptive_only"],
        "violation_count": adherence["violation_count"],
        "adherence_rate": adherence["adherence_rate"],
        "strategy_effectiveness_evaluated": False,
        "interpretation": "Behavior consistency is descriptive and does not establish strategy effectiveness.",
    }


__all__ = [
    "compute_behavior_entropy",
    "compute_profile_adherence",
    "compute_state_action_table",
    "summarize_action_frequency",
    "summarize_behavior_model",
]
