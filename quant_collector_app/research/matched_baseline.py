from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .context_features import FORBIDDEN_CONTEXT_TOKENS


CONTROL_ACTIONS = frozenset({"NO_ACTION", "HOLD"})
CONTROL_SOURCE_TYPES = frozenset({"SCHEDULED_BAR", "AUTO_CANDIDATE", "MATCHED_CONTROL"})
USER_ACTIONS = frozenset({"OPEN_LONG", "OPEN_SHORT", "CLOSE_LONG", "CLOSE_SHORT"})


@dataclass(frozen=True)
class MatchedBaselineSpec:
    numeric_features: tuple[str, ...] = (
        "pre_ret_20",
        "pre_ret_50",
        "realized_vol_20",
        "volume_zscore_20",
    )
    categorical_features: tuple[str, ...] = (
        "volatility_regime",
        "trend_regime",
        "time_session",
    )
    controls_per_sample: int = 3
    min_controls_per_sample: int = 2
    min_user_samples: int = 10
    outcome_metric: str = "fwd_ret"


def _forbidden_name(name: str) -> bool:
    value = str(name).lower()
    return any(token in value for token in FORBIDDEN_CONTEXT_TOKENS)


def _context_column_name(feature_name: str, lookback_bars: Any = None) -> str:
    name = str(feature_name)
    if lookback_bars is None or pd.isna(lookback_bars):
        return name
    window = int(lookback_bars)
    aliases = {
        "pre_simple_ret": "pre_ret",
        "pre_log_ret": "pre_log_ret",
        "realized_vol": "realized_vol",
        "volume_zscore": "volume_zscore",
    }
    return f"{aliases[name]}_{window}" if name in aliases else name


def _wide_context(context_features: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(context_features, pd.DataFrame):
        raise ValueError("context_features must be a pandas DataFrame")
    if "sample_id" not in context_features.columns:
        raise ValueError("context_features requires sample_id")
    if {"feature_name", "feature_value"} <= set(context_features.columns):
        feature_names = context_features["feature_name"].astype(str)
        if feature_names.map(_forbidden_name).any():
            raise ValueError("Matched baseline cannot use future or outcome fields.")
        data = context_features.copy()
        data["_match_feature"] = [
            _context_column_name(name, window)
            for name, window in zip(
                data["feature_name"],
                data.get("lookback_bars", pd.Series([None] * len(data), index=data.index)),
            )
        ]
        return data.pivot_table(
            index="sample_id",
            columns="_match_feature",
            values="feature_value",
            aggfunc="last",
        ).reset_index()
    forbidden = [column for column in context_features.columns if column != "sample_id" and _forbidden_name(column)]
    if forbidden:
        raise ValueError(f"Matched baseline cannot use future or outcome fields: {forbidden}")
    return context_features.copy()


def build_match_pool(observations: pd.DataFrame, context_features: pd.DataFrame) -> pd.DataFrame:
    required = {"sample_id", "symbol", "interval", "user_action", "source_type"}
    if not isinstance(observations, pd.DataFrame) or not required <= set(observations.columns):
        raise ValueError(f"observations requires columns: {sorted(required)}")
    context = _wide_context(context_features)
    return observations.merge(context, on="sample_id", how="inner", validate="one_to_one")


def compute_context_distance(
    user_row: pd.Series | dict[str, Any],
    control_row: pd.Series | dict[str, Any],
    spec: MatchedBaselineSpec | None = None,
) -> float:
    spec = spec or MatchedBaselineSpec()
    user = dict(user_row)
    control = dict(control_row)
    distances: list[float] = []
    for feature in spec.numeric_features:
        if feature not in user or feature not in control:
            continue
        left = pd.to_numeric(pd.Series([user[feature]]), errors="coerce").iloc[0]
        right = pd.to_numeric(pd.Series([control[feature]]), errors="coerce").iloc[0]
        if pd.notna(left) and pd.notna(right):
            distances.append(abs(float(left) - float(right)))
    return float(np.sqrt(np.square(distances).sum())) if distances else float("inf")


def select_matched_controls(
    user_sample_id: str,
    match_pool: pd.DataFrame,
    spec: MatchedBaselineSpec | None = None,
) -> pd.DataFrame:
    spec = spec or MatchedBaselineSpec()
    selected = match_pool[match_pool["sample_id"].astype(str) == str(user_sample_id)]
    if selected.empty:
        raise ValueError(f"Missing user sample in match pool: {user_sample_id}")
    user = selected.iloc[0]
    actions = match_pool["user_action"].astype(str).str.upper()
    sources = match_pool["source_type"].astype(str).str.upper()
    non_user_trade = (
        pd.to_numeric(match_pool["is_user_trade"], errors="coerce").fillna(0).eq(0)
        if "is_user_trade" in match_pool.columns
        else ~actions.isin(USER_ACTIONS)
    )
    eligible_control = actions.isin(CONTROL_ACTIONS) & (
        actions.eq("NO_ACTION") | sources.isin(CONTROL_SOURCE_TYPES)
    )
    candidates = match_pool[
        (match_pool["sample_id"].astype(str) != str(user_sample_id))
        & (match_pool["symbol"] == user["symbol"])
        & (match_pool["interval"] == user["interval"])
        & non_user_trade
        & eligible_control
    ].copy()
    for feature in spec.categorical_features:
        if feature in candidates.columns and feature in user.index and pd.notna(user[feature]):
            candidates = candidates[candidates[feature] == user[feature]]
    if candidates.empty:
        return pd.DataFrame(columns=["user_sample_id", "control_sample_id", "context_distance"])
    candidates["context_distance"] = candidates.apply(
        lambda row: compute_context_distance(user, row, spec),
        axis=1,
    )
    candidates = candidates[np.isfinite(candidates["context_distance"])].sort_values(
        ["context_distance", "sample_id"],
        kind="stable",
    )
    candidates = candidates.head(int(spec.controls_per_sample)).copy()
    candidates.insert(0, "user_sample_id", str(user_sample_id))
    candidates.insert(1, "control_sample_id", candidates["sample_id"].astype(str))
    return candidates.reset_index(drop=True)


def compare_user_vs_controls(
    matches: pd.DataFrame,
    outcome_labels: pd.DataFrame,
    metric: str = "fwd_ret",
    *,
    horizon_bars: int | None = None,
    pricing_basis: str | None = "next_open",
) -> pd.DataFrame:
    columns = ["user_sample_id", "user_value", "control_mean", "effect_size", "control_count"]
    if matches is None or matches.empty:
        return pd.DataFrame(columns=columns)
    required = {"sample_id", metric}
    if not isinstance(outcome_labels, pd.DataFrame) or not required <= set(outcome_labels.columns):
        raise ValueError(f"outcome_labels requires columns: {sorted(required)}")
    values = outcome_labels.copy()
    if horizon_bars is not None and "horizon_bars" in values.columns:
        values = values[values["horizon_bars"] == int(horizon_bars)]
    if pricing_basis is not None and "pricing_basis" in values.columns:
        values = values[values["pricing_basis"] == pricing_basis]
    values[metric] = pd.to_numeric(values[metric], errors="coerce")
    values = values.dropna(subset=[metric]).groupby("sample_id", as_index=False)[metric].mean()
    joined = matches[["user_sample_id", "control_sample_id"]].merge(
        values.rename(columns={"sample_id": "control_sample_id", metric: "control_value"}),
        on="control_sample_id",
        how="inner",
    ).merge(
        values.rename(columns={"sample_id": "user_sample_id", metric: "user_value"}),
        on="user_sample_id",
        how="inner",
    )
    if joined.empty:
        return pd.DataFrame(columns=columns)
    grouped = joined.groupby("user_sample_id", as_index=False).agg(
        user_value=("user_value", "first"),
        control_mean=("control_value", "mean"),
        control_count=("control_sample_id", "nunique"),
    )
    grouped["effect_size"] = grouped["user_value"] - grouped["control_mean"]
    return grouped[columns]


def _valid_effects(comparison: pd.DataFrame) -> np.ndarray:
    if not isinstance(comparison, pd.DataFrame) or "effect_size" not in comparison.columns:
        raise ValueError("comparison requires effect_size")
    return (
        pd.to_numeric(comparison["effect_size"], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .to_numpy(dtype=float)
    )


def bootstrap_effect_ci(
    comparison: pd.DataFrame,
    n_bootstrap: int = 1000,
    random_seed: int | None = None,
    confidence: float = 0.95,
) -> dict[str, Any]:
    effects = _valid_effects(comparison)
    if len(effects) < 2:
        return {
            "effect_size": float(effects.mean()) if len(effects) else None,
            "ci_lower": None,
            "ci_upper": None,
            "warning": "insufficient_sample_for_bootstrap",
        }
    rng = np.random.default_rng(random_seed)
    samples = rng.choice(effects, size=(int(n_bootstrap), len(effects)), replace=True).mean(axis=1)
    alpha = (1.0 - float(confidence)) / 2.0
    return {
        "effect_size": float(effects.mean()),
        "ci_lower": float(np.quantile(samples, alpha)),
        "ci_upper": float(np.quantile(samples, 1.0 - alpha)),
        "warning": None,
    }


def permutation_test_effect(
    comparison: pd.DataFrame,
    n_permutations: int = 1000,
    random_seed: int | None = None,
) -> dict[str, Any]:
    effects = _valid_effects(comparison)
    if len(effects) < 2:
        return {
            "effect_size": float(effects.mean()) if len(effects) else None,
            "p_value": None,
            "warning": "insufficient_sample_for_permutation_test",
        }
    rng = np.random.default_rng(random_seed)
    observed = float(effects.mean())
    signs = rng.choice(np.array([-1.0, 1.0]), size=(int(n_permutations), len(effects)))
    simulated = (signs * effects).mean(axis=1)
    exceedances = int(np.sum(np.abs(simulated) >= abs(observed)))
    return {
        "effect_size": observed,
        "p_value": float((exceedances + 1) / (int(n_permutations) + 1)),
        "warning": None,
    }


def summarize_matched_baseline(
    observations: pd.DataFrame,
    context_features: pd.DataFrame,
    outcome_labels: pd.DataFrame,
    spec: MatchedBaselineSpec | None = None,
    *,
    n_bootstrap: int = 1000,
    n_permutations: int = 1000,
    random_seed: int | None = None,
    horizon_bars: int | None = None,
    pricing_basis: str | None = "next_open",
) -> dict[str, Any]:
    spec = spec or MatchedBaselineSpec()
    pool = build_match_pool(observations, context_features)
    user_rows = pool[
        (pd.to_numeric(pool.get("is_user_trade", 0), errors="coerce").fillna(0) == 1)
        | pool["user_action"].astype(str).str.upper().isin(USER_ACTIONS)
    ]
    user_ids = user_rows["sample_id"].astype(str).drop_duplicates().tolist()
    match_frames: list[pd.DataFrame] = []
    match_counts: dict[str, int] = {}
    for sample_id in user_ids:
        selected = select_matched_controls(sample_id, pool, spec)
        match_counts[sample_id] = int(len(selected))
        if not selected.empty:
            match_frames.append(selected)
    matches = (
        pd.concat(match_frames, ignore_index=True)
        if match_frames
        else pd.DataFrame(columns=["user_sample_id", "control_sample_id", "context_distance"])
    )
    comparison = compare_user_vs_controls(
        matches,
        outcome_labels,
        spec.outcome_metric,
        horizon_bars=horizon_bars,
        pricing_basis=pricing_basis,
    )
    sparse_warning = not user_ids or any(
        count < int(spec.min_controls_per_sample) for count in match_counts.values()
    )
    low_sample_warning = len(user_ids) < int(spec.min_user_samples)
    bootstrap = bootstrap_effect_ci(comparison, n_bootstrap=n_bootstrap, random_seed=random_seed)
    permutation = permutation_test_effect(
        comparison,
        n_permutations=n_permutations,
        random_seed=random_seed,
    )
    warnings: list[str] = []
    if sparse_warning:
        warnings.append("sparse_matches_warning")
    if low_sample_warning:
        warnings.append("low_sample_warning")
    if bootstrap["warning"]:
        warnings.append(str(bootstrap["warning"]))
    if permutation["warning"]:
        warnings.append(str(permutation["warning"]))
    effect_size = (
        float(pd.to_numeric(comparison["effect_size"], errors="coerce").mean())
        if not comparison.empty
        else None
    )
    insufficient = sparse_warning or low_sample_warning or comparison.empty
    return {
        "baseline_type": "matched_context_controls",
        "matching_uses_context_features_only": True,
        "outcome_metric": spec.outcome_metric,
        "user_sample_count": len(user_ids),
        "matched_user_sample_count": int(len(comparison)),
        "match_counts": match_counts,
        "matched_control_ids": (
            matches["control_sample_id"].astype(str).drop_duplicates().tolist() if not matches.empty else []
        ),
        "effect_size": effect_size,
        "bootstrap_ci": bootstrap,
        "permutation_test": permutation,
        "sparse_matches_warning": sparse_warning,
        "low_sample_warning": low_sample_warning,
        "warnings": warnings,
        "conclusion_strength": "insufficient_evidence" if insufficient else "descriptive_statistical_evidence",
        "not_trading_signal": True,
    }


__all__ = [
    "MatchedBaselineSpec",
    "bootstrap_effect_ci",
    "build_match_pool",
    "compare_user_vs_controls",
    "compute_context_distance",
    "permutation_test_effect",
    "select_matched_controls",
    "summarize_matched_baseline",
]
