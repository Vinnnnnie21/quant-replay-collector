from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

try:
    from ..time_series_analysis.entry_distribution_diagnostics import (
        feature_bin_outcome_summary,
        quantile_feature_binning,
    )
except ImportError:  # pragma: no cover - supports tests importing research as a top-level package.
    from time_series_analysis.entry_distribution_diagnostics import (
        feature_bin_outcome_summary,
        quantile_feature_binning,
    )


FORBIDDEN_RULE_INPUT_TOKENS = (
    "future",
    "fwd",
    "mfe",
    "mae",
    "hit_tp",
    "hit_sl",
    "pnl",
    "profit",
    "win",
)
RULE_ANALYSIS_ROLE = "entry_logic_rule_hypothesis_only"


def _require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required columns: {', '.join(missing)}")


def _validate_feature_cols(feature_cols: list[str]) -> list[str]:
    safe: list[str] = []
    forbidden: list[str] = []
    for feature in feature_cols:
        name = str(feature)
        lowered = name.lower()
        if any(token in lowered for token in FORBIDDEN_RULE_INPUT_TOKENS):
            forbidden.append(name)
        else:
            safe.append(name)
    if forbidden:
        raise ValueError(f"outcome fields are not allowed as rule inputs: {', '.join(forbidden)}")
    return safe


def _labeled_entry_reject(features_df: pd.DataFrame, annotations_df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    if not isinstance(features_df, pd.DataFrame):
        raise ValueError("features_df must be a pandas DataFrame")
    if not isinstance(annotations_df, pd.DataFrame):
        raise ValueError("annotations_df must be a pandas DataFrame")
    _require_columns(features_df, ["observation_id", *feature_cols], "features_df")
    _require_columns(annotations_df, ["observation_id", "human_decision"], "annotations_df")
    merged = features_df[["observation_id", *feature_cols]].merge(
        annotations_df[["observation_id", "human_decision"]],
        on="observation_id",
        how="inner",
    )
    merged["human_decision"] = merged["human_decision"].astype(str).str.upper()
    return merged.loc[merged["human_decision"].isin(["ENTRY", "REJECT"])].reset_index(drop=True)


def _rule_id(feature: str, operator: str, threshold: float) -> str:
    payload = f"{feature}|{operator}|{threshold:.12g}"
    return "entry_rule_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def mine_single_feature_rule_hypotheses(
    features_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    *,
    feature_cols: list[str],
    quantiles: tuple[float, ...] | list[float] = (0.25, 0.5, 0.75),
    min_samples: int = 5,
) -> pd.DataFrame:
    """Mine interpretable ENTRY-vs-REJECT threshold hypotheses, not trading signals."""
    safe_features = _validate_feature_cols(list(feature_cols))
    merged = _labeled_entry_reject(features_df, annotations_df, safe_features)
    if merged.empty:
        return _empty_rules()
    baseline_entry_rate = float((merged["human_decision"] == "ENTRY").mean())
    rows: list[dict[str, Any]] = []
    for feature in safe_features:
        values = pd.to_numeric(merged[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
        clean = values.dropna()
        if clean.empty:
            continue
        thresholds = sorted({float(clean.quantile(float(level))) for level in quantiles})
        for threshold in thresholds:
            for operator, mask in (
                (">=", values >= threshold),
                ("<=", values <= threshold),
            ):
                subset = merged.loc[mask.fillna(False)]
                decisions = subset["human_decision"].astype(str).str.upper()
                entry_count = int((decisions == "ENTRY").sum())
                reject_count = int((decisions == "REJECT").sum())
                sample_count = int(entry_count + reject_count)
                if sample_count < int(min_samples):
                    continue
                entry_rate = float(entry_count / sample_count) if sample_count else None
                rows.append(
                    {
                        "rule_id": _rule_id(feature, operator, threshold),
                        "analysis_role": RULE_ANALYSIS_ROLE,
                        "rule_type": "single_feature_threshold_hypothesis",
                        "feature": feature,
                        "operator": operator,
                        "threshold": threshold,
                        "hypothesis": (
                            f"When {feature} {operator} {threshold:.6g}, manual ENTRY share is "
                            f"{entry_rate:.3f} within labeled ENTRY/REJECT samples."
                        ),
                        "sample_count": sample_count,
                        "entry_count": entry_count,
                        "reject_count": reject_count,
                        "entry_rate": entry_rate,
                        "baseline_entry_rate": baseline_entry_rate,
                        "entry_rate_lift": float(entry_rate - baseline_entry_rate) if entry_rate is not None else None,
                        "sample_warning": f"low_sample: {sample_count} < 20" if sample_count < 20 else None,
                    }
                )
    if not rows:
        return _empty_rules()
    result = pd.DataFrame(rows)
    return result.sort_values(
        ["entry_rate_lift", "entry_rate", "sample_count", "feature", "operator", "threshold"],
        ascending=[False, False, False, True, True, True],
        kind="stable",
    ).reset_index(drop=True)


def _empty_rules() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "rule_id",
            "analysis_role",
            "rule_type",
            "feature",
            "operator",
            "threshold",
            "hypothesis",
            "sample_count",
            "entry_count",
            "reject_count",
            "entry_rate",
            "baseline_entry_rate",
            "entry_rate_lift",
            "sample_warning",
        ]
    )


def build_entry_rule_research_pack(
    features_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    *,
    outcomes_df: pd.DataFrame | None = None,
    feature_cols: list[str],
    outcome_cols: list[str] | None = None,
    quantiles: tuple[float, ...] | list[float] = (0.25, 0.5, 0.75),
    bins: int = 4,
    min_samples: int = 5,
) -> dict[str, Any]:
    safe_features = _validate_feature_cols(list(feature_cols))
    merged = _labeled_entry_reject(features_df, annotations_df, safe_features)
    feature_binning = (
        quantile_feature_binning(merged, "human_decision", safe_features, q=bins)
        if not merged.empty
        else pd.DataFrame()
    )
    rule_hypotheses = mine_single_feature_rule_hypotheses(
        features_df,
        annotations_df,
        feature_cols=safe_features,
        quantiles=tuple(float(value) for value in quantiles),
        min_samples=min_samples,
    )
    posterior = pd.DataFrame()
    if outcomes_df is not None and outcome_cols:
        posterior = feature_bin_outcome_summary(
            features_df,
            annotations_df,
            outcomes_df,
            feature_cols=safe_features,
            outcome_cols=list(outcome_cols),
            q=bins,
        )
    warnings = ["not_trading_signal"]
    if not rule_hypotheses.empty and rule_hypotheses["sample_warning"].notna().any():
        warnings.append("sample_size_warning")
    return {
        "feature_cols": safe_features,
        "feature_binning": feature_binning,
        "rule_hypotheses": rule_hypotheses,
        "posterior_outcome_by_bin": posterior,
        "warnings": warnings,
    }


__all__ = [
    "build_entry_rule_research_pack",
    "mine_single_feature_rule_hypotheses",
]
