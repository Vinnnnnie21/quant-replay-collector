from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


FORBIDDEN_FEATURE_TOKENS = (
    "buy_signal",
    "sell_signal",
    "trade_signal",
    "future",
    "fwd",
    "mfe",
    "mae",
    "hit_tp",
    "hit_sl",
)
METADATA_COLUMNS = {
    "observation_id",
    "symbol",
    "interval",
    "bar_index",
    "bar_time",
    "decision_timing",
    "uses_next_bar_confirmation",
    "insufficient_history",
}


def _require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required columns: {', '.join(missing)}")


def _validate_feature_cols(feature_cols: list[str]) -> list[str]:
    if not feature_cols:
        raise ValueError("feature_cols must not be empty")
    validated: list[str] = []
    for column in feature_cols:
        normalized = str(column)
        lowered = normalized.lower()
        if any(token in lowered for token in FORBIDDEN_FEATURE_TOKENS):
            raise ValueError(f"Outcome or trading-signal feature is not allowed: {column}")
        validated.append(normalized)
    return validated


def _infer_feature_cols(features_df: pd.DataFrame) -> list[str]:
    inferred: list[str] = []
    for column in features_df.columns:
        normalized = str(column)
        if normalized in METADATA_COLUMNS:
            continue
        lowered = normalized.lower()
        if any(token in lowered for token in FORBIDDEN_FEATURE_TOKENS):
            continue
        numeric = pd.to_numeric(features_df[column], errors="coerce")
        if numeric.notna().any():
            inferred.append(normalized)
    return _validate_feature_cols(inferred)


def _safe_scale(values: pd.Series) -> float:
    q25 = values.quantile(0.25)
    q75 = values.quantile(0.75)
    iqr = float(q75 - q25)
    if np.isfinite(iqr) and iqr > 0:
        return iqr
    std = float(values.std(ddof=0)) if len(values) > 1 else 0.0
    return std if np.isfinite(std) and std > 0 else 1.0


def fit_entry_prototype(
    features_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    feature_cols: list[str],
) -> dict[str, Any]:
    if not isinstance(features_df, pd.DataFrame):
        raise ValueError("features_df must be a pandas DataFrame")
    if not isinstance(annotations_df, pd.DataFrame):
        raise ValueError("annotations_df must be a pandas DataFrame")
    feature_cols = _validate_feature_cols(feature_cols)
    _require_columns(features_df, ["observation_id", *feature_cols], "features_df")
    _require_columns(annotations_df, ["observation_id", "human_decision"], "annotations_df")

    decisions = annotations_df[["observation_id", "human_decision"]].copy()
    decisions["human_decision"] = decisions["human_decision"].astype(str).str.upper()
    merged = features_df.merge(decisions, on="observation_id", how="inner")
    entries = merged[merged["human_decision"] == "ENTRY"].copy()
    if entries.empty:
        raise ValueError("At least one ENTRY annotation is required to fit prototype")

    center: dict[str, float] = {}
    scale: dict[str, float] = {}
    warnings: list[str] = []
    for feature in feature_cols:
        values = pd.to_numeric(entries[feature], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if values.empty:
            center[feature] = 0.0
            scale[feature] = 1.0
            warnings.append(f"feature_has_no_valid_entry_values:{feature}")
            continue
        center[feature] = float(values.median())
        scale[feature] = _safe_scale(values)
        if scale[feature] == 1.0 and values.nunique(dropna=True) <= 1:
            warnings.append(f"constant_entry_feature:{feature}")

    return {
        "method": "entry_prototype_median_iqr",
        "score_name": "human_entry_similarity",
        "feature_cols": list(feature_cols),
        "center": center,
        "scale": scale,
        "entry_count": int(len(entries)),
        "warnings": warnings,
    }


def _prototype_feature_cols(prototype: dict[str, Any]) -> list[str]:
    feature_cols = [str(column) for column in prototype.get("feature_cols", [])]
    if not feature_cols:
        raise ValueError("prototype must contain feature_cols")
    _validate_feature_cols(feature_cols)
    return feature_cols


def _row_feature_distances(row: pd.Series, prototype: dict[str, Any]) -> tuple[dict[str, float], int]:
    center = prototype.get("center") or {}
    scale = prototype.get("scale") or {}
    distances: dict[str, float] = {}
    missing_count = 0
    for feature in _prototype_feature_cols(prototype):
        feature_center = float(center[feature])
        feature_scale = float(scale[feature])
        raw_value = row.get(feature)
        value = pd.to_numeric(pd.Series([raw_value]), errors="coerce").replace([np.inf, -np.inf], np.nan).iloc[0]
        if pd.isna(value):
            value = feature_center
            missing_count += 1
        distances[feature] = abs(float(value) - feature_center) / feature_scale
    return distances, missing_count


def explain_similarity_score(row: pd.Series, prototype: dict[str, Any], top_n_features: int = 3) -> list[dict[str, float | str]]:
    distances, _missing_count = _row_feature_distances(row, prototype)
    center = prototype.get("center") or {}
    scale = prototype.get("scale") or {}
    ranked = sorted(distances.items(), key=lambda item: (item[1], item[0]))
    explanations: list[dict[str, float | str]] = []
    for feature, normalized_distance in ranked[: max(0, int(top_n_features))]:
        raw_value = row.get(feature)
        value = pd.to_numeric(pd.Series([raw_value]), errors="coerce").replace([np.inf, -np.inf], np.nan).iloc[0]
        value = float(center[feature]) if pd.isna(value) else float(value)
        explanations.append(
            {
                "feature": feature,
                "value": value,
                "entry_center": float(center[feature]),
                "scale": float(scale[feature]),
                "normalized_distance": float(normalized_distance),
                "similarity_contribution": float(1.0 / (1.0 + normalized_distance)),
            }
        )
    return explanations


def score_entry_similarity(features_df: pd.DataFrame, prototype: dict[str, Any]) -> pd.DataFrame:
    if not isinstance(features_df, pd.DataFrame):
        raise ValueError("features_df must be a pandas DataFrame")
    feature_cols = _prototype_feature_cols(prototype)
    _require_columns(features_df, ["observation_id", *feature_cols], "features_df")

    rows: list[dict[str, Any]] = []
    for _, row in features_df.iterrows():
        distances, missing_count = _row_feature_distances(row, prototype)
        distance = float(np.sqrt(np.mean([value * value for value in distances.values()])))
        similarity = float(1.0 / (1.0 + distance))
        rows.append(
            {
                "observation_id": str(row["observation_id"]),
                "human_entry_similarity": similarity,
                "setup_confidence": similarity,
                "nearest_entry_pattern": "ENTRY_PROTOTYPE_MEDIAN_IQR",
                "explanation_features": explain_similarity_score(row, prototype, top_n_features=3),
                "missing_feature_count": int(missing_count),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "observation_id",
            "human_entry_similarity",
            "setup_confidence",
            "nearest_entry_pattern",
            "explanation_features",
            "missing_feature_count",
        ],
    )


def rank_unlabeled_candidates(
    features_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    top_k: int,
) -> pd.DataFrame:
    if int(top_k) <= 0:
        return pd.DataFrame(
            columns=[
                "observation_id",
                "human_entry_similarity",
                "setup_confidence",
                "nearest_entry_pattern",
                "explanation_features",
                "missing_feature_count",
            ]
        )
    if not isinstance(features_df, pd.DataFrame):
        raise ValueError("features_df must be a pandas DataFrame")
    if not isinstance(annotations_df, pd.DataFrame):
        raise ValueError("annotations_df must be a pandas DataFrame")
    _require_columns(features_df, ["observation_id"], "features_df")
    _require_columns(annotations_df, ["observation_id", "human_decision"], "annotations_df")

    feature_cols = _infer_feature_cols(features_df)
    prototype = fit_entry_prototype(features_df, annotations_df, feature_cols)
    decisions = annotations_df[["observation_id", "human_decision"]].copy()
    decisions["human_decision"] = decisions["human_decision"].astype(str).str.upper()
    unlabeled_ids = set(decisions.loc[decisions["human_decision"] == "UNLABELED", "observation_id"].astype(str))
    candidates = features_df[features_df["observation_id"].astype(str).isin(unlabeled_ids)].copy()
    if candidates.empty:
        return score_entry_similarity(candidates, prototype)
    candidates["_entry_logic_row_order"] = range(len(candidates))
    scores = score_entry_similarity(candidates.drop(columns=["_entry_logic_row_order"]), prototype)
    scores["_entry_logic_row_order"] = candidates["_entry_logic_row_order"].to_numpy()
    ranked = scores.sort_values("human_entry_similarity", ascending=False, kind="stable").head(int(top_k))
    return ranked.drop(columns=["_entry_logic_row_order"]).reset_index(drop=True)


__all__ = [
    "explain_similarity_score",
    "fit_entry_prototype",
    "rank_unlabeled_candidates",
    "score_entry_similarity",
]
