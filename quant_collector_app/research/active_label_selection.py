from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd


SCORE_COLUMNS = [
    "observation_id",
    "human_entry_similarity",
    "setup_confidence",
    "nearest_entry_pattern",
    "explanation_features",
]
REVIEW_METADATA_COLUMNS = [
    "candidate_source",
    "candidate_reason",
    "setup_bar_index",
    "decision_bar_index",
    "data_version",
    "diversity_bucket",
]
DEFAULT_QUEUE_VERSION = "entry_review_queue_v1"
FORBIDDEN_OUTPUT_TOKENS = (
    "buy_signal",
    "sell_signal",
    "trade_signal",
    "trade_advice",
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


def _unlabeled_scores(scored_df: pd.DataFrame, annotations_df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(scored_df, pd.DataFrame):
        raise ValueError("scored_df must be a pandas DataFrame")
    if not isinstance(annotations_df, pd.DataFrame):
        raise ValueError("annotations_df must be a pandas DataFrame")
    _require_columns(scored_df, ["observation_id", "human_entry_similarity"], "scored_df")
    _require_columns(annotations_df, ["observation_id"], "annotations_df")

    active_ids = _active_annotation_ids(annotations_df)
    decisions_columns = ["observation_id"]
    if "human_decision" in annotations_df.columns:
        decisions_columns.append("human_decision")
    decisions = annotations_df[decisions_columns].copy()
    decisions["observation_id"] = decisions["observation_id"].astype(str)
    if "human_decision" in decisions.columns:
        decisions["human_decision"] = decisions["human_decision"].astype(str).str.upper()
    merged = scored_df.copy()
    merged["observation_id"] = merged["observation_id"].astype(str)
    merged["_entry_review_order"] = range(len(merged))
    merged = merged.merge(decisions, on="observation_id", how="left")
    mask = ~merged["observation_id"].astype(str).isin(active_ids)
    return merged.loc[mask].reset_index(drop=True)


def _active_annotation_ids(annotations_df: pd.DataFrame) -> set[str]:
    if not isinstance(annotations_df, pd.DataFrame) or annotations_df.empty or "observation_id" not in annotations_df.columns:
        return set()
    working = annotations_df.copy()
    if "is_active" in working.columns:
        active = working["is_active"].map(_is_active_value)
        working = working.loc[active]
    return set(working["observation_id"].dropna().astype(str))


def _is_active_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "inactive"}
    if value is None or pd.isna(value):
        return True
    return bool(value)


def _review_id(observation_id: str, mode: str, queue_version: str) -> str:
    payload = "|".join([str(observation_id), str(mode), str(queue_version)])
    return "entry_review_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _review_output(frame: pd.DataFrame, reason: str, mode: str, queue_version: str = DEFAULT_QUEUE_VERSION) -> pd.DataFrame:
    if frame.empty:
        columns = [column for column in [*SCORE_COLUMNS, *REVIEW_METADATA_COLUMNS] if column in frame.columns]
        return pd.DataFrame(columns=["review_id", *columns, "review_reason", "review_mode", "review_queue_version"])
    safe_columns = [column for column in [*SCORE_COLUMNS, *REVIEW_METADATA_COLUMNS] if column in frame.columns]
    output = frame.loc[:, safe_columns].copy()
    output.insert(0, "review_id", [_review_id(observation_id, mode, queue_version) for observation_id in output["observation_id"].astype(str)])
    output["review_reason"] = reason
    output["review_mode"] = mode
    output["review_queue_version"] = str(queue_version)
    lowered = " ".join(output.columns).lower()
    if any(token in lowered for token in FORBIDDEN_OUTPUT_TOKENS):
        raise ValueError("review queue output contains forbidden trading or outcome fields")
    return output.reset_index(drop=True)


def _safe_feature_columns(feature_df: pd.DataFrame) -> list[str]:
    columns: list[str] = []
    for column in feature_df.columns:
        name = str(column)
        lowered = name.lower()
        if name in METADATA_COLUMNS:
            continue
        if any(token in lowered for token in FORBIDDEN_OUTPUT_TOKENS):
            continue
        numeric = pd.to_numeric(feature_df[column], errors="coerce")
        if numeric.notna().any():
            columns.append(name)
    return columns


def _standardized_feature_matrix(frame: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    matrix = frame[feature_cols].apply(pd.to_numeric, errors="coerce")
    medians = matrix.median()
    q25 = matrix.quantile(0.25)
    q75 = matrix.quantile(0.75)
    scale = (q75 - q25).replace(0, np.nan)
    scale = scale.fillna(matrix.std(ddof=0)).replace(0, np.nan).fillna(1.0)
    return (matrix.fillna(medians) - medians) / scale


def select_high_similarity_unlabeled(
    scored_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    top_k: int,
    queue_version: str = DEFAULT_QUEUE_VERSION,
) -> pd.DataFrame:
    candidates = _unlabeled_scores(scored_df, annotations_df)
    if int(top_k) <= 0:
        return _review_output(candidates.iloc[0:0], "high_similarity_to_entry_prototype", "high_similarity", queue_version)
    ranked = _sort_by_score(candidates).head(int(top_k))
    return _review_output(ranked, "high_similarity_to_entry_prototype", "high_similarity", queue_version)


def select_uncertain_candidates(
    scored_df: pd.DataFrame,
    lower: float,
    upper: float,
    top_k: int,
    queue_version: str = DEFAULT_QUEUE_VERSION,
) -> pd.DataFrame:
    if not isinstance(scored_df, pd.DataFrame):
        raise ValueError("scored_df must be a pandas DataFrame")
    _require_columns(scored_df, ["observation_id", "human_entry_similarity"], "scored_df")
    low = float(lower)
    high = float(upper)
    if low > high:
        raise ValueError("lower must be less than or equal to upper")
    working = scored_df.copy()
    working["_entry_review_order"] = range(len(working))
    scores = pd.to_numeric(working["human_entry_similarity"], errors="coerce")
    midpoint = (low + high) / 2.0
    mask = scores.between(low, high, inclusive="both")
    selected = working.loc[mask].copy()
    if selected.empty or int(top_k) <= 0:
        return _review_output(selected.iloc[0:0], "uncertain_similarity_band", "uncertain", queue_version)
    selected["_uncertainty_distance"] = (pd.to_numeric(selected["human_entry_similarity"], errors="coerce") - midpoint).abs()
    ranked = selected.assign(_observation_sort=selected["observation_id"].astype(str)).sort_values(
        ["_uncertainty_distance", "_observation_sort"],
        ascending=[True, True],
        kind="stable",
    ).head(int(top_k))
    return _review_output(ranked, "uncertain_similarity_band", "uncertain", queue_version)


def select_diverse_candidates(
    scored_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    top_k: int,
    queue_version: str = DEFAULT_QUEUE_VERSION,
) -> pd.DataFrame:
    if not isinstance(scored_df, pd.DataFrame):
        raise ValueError("scored_df must be a pandas DataFrame")
    if not isinstance(feature_df, pd.DataFrame):
        raise ValueError("feature_df must be a pandas DataFrame")
    _require_columns(scored_df, ["observation_id", "human_entry_similarity"], "scored_df")
    _require_columns(feature_df, ["observation_id"], "feature_df")
    if int(top_k) <= 0 or scored_df.empty:
        return _review_output(scored_df.iloc[0:0], "diverse_feature_coverage", "diverse", queue_version)

    working = scored_df.copy()
    working["observation_id"] = working["observation_id"].astype(str)
    working["_entry_review_order"] = range(len(working))
    features = feature_df.copy()
    features["observation_id"] = features["observation_id"].astype(str)
    merged = working.merge(features, on="observation_id", how="left", suffixes=("", "_feature"))
    merged = merged.drop_duplicates(subset=["observation_id"], keep="first").reset_index(drop=True)
    feature_cols = [column for column in _safe_feature_columns(features) if column in merged.columns]
    if not feature_cols:
        ranked = _sort_by_score(merged).head(int(top_k))
        return _review_output(ranked, "diverse_feature_coverage", "diverse", queue_version)

    merged["diversity_bucket"] = _diversity_buckets(merged, feature_cols)
    ranked = _sort_by_score(merged)
    selected_rows = []
    used_buckets: set[str] = set()
    for _, row in ranked.iterrows():
        bucket = str(row.get("diversity_bucket"))
        if bucket in used_buckets:
            continue
        selected_rows.append(row)
        used_buckets.add(bucket)
        if len(selected_rows) >= int(top_k):
            break
    if len(selected_rows) < int(top_k):
        selected_ids = {str(row["observation_id"]) for row in selected_rows}
        remaining = ranked.loc[~ranked["observation_id"].astype(str).isin(selected_ids)].copy()
        remaining = _rank_remaining_by_feature_distance(remaining, pd.DataFrame(selected_rows), feature_cols)
        for _, row in remaining.iterrows():
            if str(row["observation_id"]) in selected_ids:
                continue
            selected_rows.append(row)
            if len(selected_rows) >= int(top_k):
                break
    selected = pd.DataFrame(selected_rows)
    return _review_output(selected, "diverse_feature_coverage", "diverse", queue_version)


def _sort_by_score(frame: pd.DataFrame) -> pd.DataFrame:
    working = frame.copy()
    working["_score_sort"] = pd.to_numeric(working["human_entry_similarity"], errors="coerce").fillna(-np.inf)
    working["_observation_sort"] = working["observation_id"].astype(str)
    return working.sort_values(["_score_sort", "_observation_sort"], ascending=[False, True], kind="stable")


def _diversity_buckets(frame: pd.DataFrame, feature_cols: list[str]) -> pd.Series:
    parts: list[pd.Series] = []
    for feature in feature_cols[:3]:
        values = pd.to_numeric(frame[feature], errors="coerce")
        ranks = values.rank(method="first")
        bucket_count = min(2, max(1, int(values.notna().sum())))
        if bucket_count <= 1:
            bucket = pd.Series(["0"] * len(values), index=frame.index)
        else:
            bucket = pd.qcut(ranks, q=bucket_count, labels=False, duplicates="drop").astype("Int64").astype(str)
        parts.append(pd.Series([f"{feature}:{value}" for value in bucket], index=frame.index))
    if not parts:
        return pd.Series(["no_features"] * len(frame), index=frame.index)
    result = parts[0]
    for part in parts[1:]:
        result = result + "|" + part
    return result


def _rank_remaining_by_feature_distance(
    remaining: pd.DataFrame,
    selected: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    if remaining.empty or selected.empty or not feature_cols:
        return _sort_by_score(remaining)
    combined = pd.concat([selected, remaining], ignore_index=True, sort=False)
    matrix = _standardized_feature_matrix(combined, feature_cols)
    selected_matrix = matrix.iloc[: len(selected)]
    remaining_matrix = matrix.iloc[len(selected) :]
    distances = []
    for _, row in remaining_matrix.iterrows():
        delta = selected_matrix.sub(row, axis="columns")
        min_distance = np.sqrt((delta * delta).sum(axis=1)).min()
        distances.append(float(min_distance))
    working = remaining.copy()
    working["_diversity_distance"] = distances
    working["_score_sort"] = pd.to_numeric(working["human_entry_similarity"], errors="coerce").fillna(-np.inf)
    working["_observation_sort"] = working["observation_id"].astype(str)
    return working.sort_values(
        ["_diversity_distance", "_score_sort", "_observation_sort"],
        ascending=[False, False, True],
        kind="stable",
    )


def _fallback_rule_seeded_queue(
    annotations_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    *,
    mode_name: str,
    top_k: int,
    queue_version: str,
) -> pd.DataFrame:
    if not isinstance(feature_df, pd.DataFrame):
        raise ValueError("feature_df must be a pandas DataFrame")
    _require_columns(feature_df, ["observation_id"], "feature_df")
    candidates = feature_df.copy()
    candidates["observation_id"] = candidates["observation_id"].astype(str)
    active_ids = _active_annotation_ids(annotations_df)
    candidates = candidates.loc[~candidates["observation_id"].isin(active_ids)].copy()
    if candidates.empty or int(top_k) <= 0:
        return _review_output(candidates.iloc[0:0], "rule_seeded_unscored_candidate", mode_name, queue_version)
    source_priority = {"rule_seeded": 0, "manual_context": 1, "model_ranked": 2}
    if "candidate_source" not in candidates.columns:
        candidates["candidate_source"] = "rule_seeded"
    candidates["_source_priority"] = candidates["candidate_source"].map(lambda value: source_priority.get(str(value), 99))
    if "decision_bar_index" not in candidates.columns:
        candidates["decision_bar_index"] = np.arange(len(candidates), dtype=int)
    candidates["_decision_sort"] = pd.to_numeric(candidates["decision_bar_index"], errors="coerce").fillna(np.inf)
    candidates["_observation_sort"] = candidates["observation_id"].astype(str)
    ranked = candidates.sort_values(["_source_priority", "_decision_sort", "_observation_sort"], kind="stable").head(int(top_k))
    return _review_output(ranked, "rule_seeded_unscored_candidate", mode_name, queue_version)


def _mode_config(mode: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(mode, dict):
        config = dict(mode)
        config["name"] = str(config.get("name", "high_similarity"))
        return config
    return {"name": str(mode)}


def build_label_review_queue(
    scored_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    feature_df: pd.DataFrame,
    mode: str | dict[str, Any],
) -> pd.DataFrame:
    config = _mode_config(mode)
    mode_name = str(config.get("name", "high_similarity"))
    top_k = int(config.get("top_k", 20))
    queue_version = str(config.get("queue_version", DEFAULT_QUEUE_VERSION))
    if (
        not isinstance(scored_df, pd.DataFrame)
        or scored_df.empty
        or "human_entry_similarity" not in scored_df.columns
    ):
        return _fallback_rule_seeded_queue(
            annotations_df,
            feature_df,
            mode_name=mode_name,
            top_k=top_k,
            queue_version=queue_version,
        )
    if mode_name == "high_similarity":
        return select_high_similarity_unlabeled(scored_df, annotations_df, top_k, queue_version=queue_version)

    unlabeled = _unlabeled_scores(scored_df, annotations_df)
    if mode_name == "uncertain":
        lower = float(config.get("lower", 0.4))
        upper = float(config.get("upper", 0.6))
        return select_uncertain_candidates(unlabeled, lower=lower, upper=upper, top_k=top_k, queue_version=queue_version)
    if mode_name == "diverse":
        return select_diverse_candidates(unlabeled, feature_df, top_k=top_k, queue_version=queue_version)
    raise ValueError(f"Unsupported review queue mode: {mode_name}")


__all__ = [
    "build_label_review_queue",
    "select_diverse_candidates",
    "select_high_similarity_unlabeled",
    "select_uncertain_candidates",
]
