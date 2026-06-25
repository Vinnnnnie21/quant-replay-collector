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
PU_OUTPUT_COLUMNS = [
    "observation_id",
    "human_decision",
    "pu_role",
    "pu_label",
]


def _require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required columns: {', '.join(missing)}")


def _validate_feature_cols(feature_cols: list[str]) -> list[str]:
    if not feature_cols:
        raise ValueError("feature_cols must not be empty")
    validated: list[str] = []
    for column in feature_cols:
        name = str(column)
        lowered = name.lower()
        if any(token in lowered for token in FORBIDDEN_FEATURE_TOKENS):
            raise ValueError(f"Outcome or trading-signal feature is not allowed: {column}")
        validated.append(name)
    return validated


def _decision_to_role(decision: str) -> str:
    normalized = str(decision).upper()
    if normalized == "ENTRY":
        return "positive"
    if normalized == "UNLABELED":
        return "unlabeled"
    if normalized == "REJECT":
        return "holdout_reject"
    if normalized == "UNCERTAIN":
        return "holdout_uncertain"
    return "unlabeled"


def build_pu_dataset(
    features_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    if not isinstance(features_df, pd.DataFrame):
        raise ValueError("features_df must be a pandas DataFrame")
    if not isinstance(annotations_df, pd.DataFrame):
        raise ValueError("annotations_df must be a pandas DataFrame")
    feature_cols = _validate_feature_cols(feature_cols)
    _require_columns(features_df, ["observation_id", *feature_cols], "features_df")
    _require_columns(annotations_df, ["observation_id", "human_decision"], "annotations_df")

    features = features_df[["observation_id", *feature_cols]].copy()
    features["observation_id"] = features["observation_id"].astype(str)
    decisions = annotations_df[["observation_id", "human_decision"]].copy()
    decisions["observation_id"] = decisions["observation_id"].astype(str)
    decisions["human_decision"] = decisions["human_decision"].astype(str).str.upper()

    dataset = features.merge(decisions, on="observation_id", how="left")
    dataset["human_decision"] = dataset["human_decision"].fillna("UNLABELED")
    dataset["pu_role"] = dataset["human_decision"].map(_decision_to_role)
    dataset["pu_label"] = np.where(dataset["pu_role"] == "positive", 1.0, np.nan)
    if not (dataset["pu_role"] == "positive").any():
        raise ValueError("At least one ENTRY annotation is required for PU learning")

    return dataset[[*PU_OUTPUT_COLUMNS, *feature_cols]].reset_index(drop=True)


def estimate_positive_prior_basic(pu_dataset: pd.DataFrame) -> dict[str, float | int | str]:
    if not isinstance(pu_dataset, pd.DataFrame):
        raise ValueError("pu_dataset must be a pandas DataFrame")
    _require_columns(pu_dataset, ["pu_role"], "pu_dataset")
    positive_count = int((pu_dataset["pu_role"] == "positive").sum())
    unlabeled_count = int((pu_dataset["pu_role"] == "unlabeled").sum())
    holdout_reject_count = int((pu_dataset["pu_role"] == "holdout_reject").sum())
    denominator = positive_count + unlabeled_count
    prior = float(positive_count / denominator) if denominator else 0.0
    return {
        "method": "entry_over_entry_plus_unlabeled",
        "positive_count": positive_count,
        "unlabeled_count": unlabeled_count,
        "holdout_reject_count": holdout_reject_count,
        "positive_prior": prior,
    }


def _safe_scale(values: pd.Series) -> float:
    q25 = values.quantile(0.25)
    q75 = values.quantile(0.75)
    iqr = float(q75 - q25)
    if np.isfinite(iqr) and iqr > 0:
        return iqr
    std = float(values.std(ddof=0)) if len(values) > 1 else 0.0
    return std if np.isfinite(std) and std > 0 else 1.0


def _positive_prototype(pu_dataset: pd.DataFrame, feature_cols: list[str]) -> dict[str, dict[str, float]]:
    positives = pu_dataset[pu_dataset["pu_role"] == "positive"].copy()
    if positives.empty:
        raise ValueError("At least one positive ENTRY row is required for PU scoring")
    center: dict[str, float] = {}
    scale: dict[str, float] = {}
    for feature in _validate_feature_cols(feature_cols):
        values = pd.to_numeric(positives[feature], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if values.empty:
            center[feature] = 0.0
            scale[feature] = 1.0
        else:
            center[feature] = float(values.median())
            scale[feature] = _safe_scale(values)
    return {"center": center, "scale": scale}


def _similarity(row: pd.Series, prototype: dict[str, dict[str, float]], feature_cols: list[str]) -> float:
    distances: list[float] = []
    for feature in feature_cols:
        center = float(prototype["center"][feature])
        scale = float(prototype["scale"][feature])
        value = pd.to_numeric(pd.Series([row.get(feature)]), errors="coerce").replace([np.inf, -np.inf], np.nan).iloc[0]
        if pd.isna(value):
            value = center
        distances.append(((float(value) - center) / scale) ** 2)
    distance = float(np.sqrt(np.mean(distances))) if distances else 0.0
    return float(1.0 / (1.0 + distance))


def score_unlabeled_by_positive_density(
    pu_dataset: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    if not isinstance(pu_dataset, pd.DataFrame):
        raise ValueError("pu_dataset must be a pandas DataFrame")
    feature_cols = _validate_feature_cols(feature_cols)
    _require_columns(pu_dataset, ["observation_id", "pu_role", *feature_cols], "pu_dataset")
    prototype = _positive_prototype(pu_dataset, feature_cols)
    unlabeled = pu_dataset[pu_dataset["pu_role"] == "unlabeled"].copy()
    rows: list[dict[str, Any]] = []
    for _, row in unlabeled.iterrows():
        score = _similarity(row, prototype, feature_cols)
        rows.append(
            {
                "observation_id": str(row["observation_id"]),
                "pu_entry_score": score,
                "human_entry_similarity": score,
                "pu_method": "positive_median_iqr_density",
            }
        )
    return pd.DataFrame(
        rows,
        columns=["observation_id", "pu_entry_score", "human_entry_similarity", "pu_method"],
    )


def evaluate_pu_ranking_with_labeled_holdout(
    scored_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    k: int = 10,
) -> dict[str, float | int | bool | str | None]:
    if not isinstance(scored_df, pd.DataFrame):
        raise ValueError("scored_df must be a pandas DataFrame")
    if not isinstance(annotations_df, pd.DataFrame):
        raise ValueError("annotations_df must be a pandas DataFrame")
    score_col = "pu_entry_score" if "pu_entry_score" in scored_df.columns else "human_entry_similarity"
    _require_columns(scored_df, ["observation_id", score_col], "scored_df")
    _require_columns(annotations_df, ["observation_id", "human_decision"], "annotations_df")

    scores = scored_df[["observation_id", score_col]].copy()
    scores["observation_id"] = scores["observation_id"].astype(str)
    scores[score_col] = pd.to_numeric(scores[score_col], errors="coerce")
    decisions = annotations_df[["observation_id", "human_decision"]].copy()
    decisions["observation_id"] = decisions["observation_id"].astype(str)
    decisions["human_decision"] = decisions["human_decision"].astype(str).str.upper()
    evaluated = scores.merge(decisions, on="observation_id", how="inner")
    evaluated = evaluated[evaluated["human_decision"].isin(["ENTRY", "REJECT"])].dropna(subset=[score_col])
    if evaluated.empty:
        return {
            "method": "labeled_holdout_ranking",
            "evaluated_count": 0,
            "manual_entry_count": 0,
            "k": int(k),
            "precision_at_k": None,
            "recall_on_manual_entries": None,
            "reject_treated_as_negative_training_sample": False,
        }

    ranked = evaluated.sort_values(score_col, ascending=False, kind="stable")
    cutoff = max(0, min(int(k), len(ranked)))
    top = ranked.head(cutoff)
    manual_entry_count = int((ranked["human_decision"] == "ENTRY").sum())
    top_entry_count = int((top["human_decision"] == "ENTRY").sum())
    precision = float(top_entry_count / cutoff) if cutoff else None
    recall = float(top_entry_count / manual_entry_count) if manual_entry_count else None
    return {
        "method": "labeled_holdout_ranking",
        "evaluated_count": int(len(ranked)),
        "manual_entry_count": manual_entry_count,
        "k": cutoff,
        "precision_at_k": precision,
        "recall_on_manual_entries": recall,
        "reject_treated_as_negative_training_sample": False,
    }


__all__ = [
    "build_pu_dataset",
    "estimate_positive_prior_basic",
    "evaluate_pu_ranking_with_labeled_holdout",
    "score_unlabeled_by_positive_density",
]
