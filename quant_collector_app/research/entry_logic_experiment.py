
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .active_label_selection import build_label_review_queue
from .entry_experiment_registry import save_experiment_bundle, save_experiment_manifest
from .entry_logic_scoring import fit_entry_prototype, score_entry_similarity
from .pu_entry_learning import build_pu_dataset
from .temporal_validation import (
    SplitResult,
    build_purged_chronological_split,
    chronological_train_val_test_split,
    summarize_split,
)


ALLOWED_HUMAN_DECISIONS = {"ENTRY", "REJECT", "UNCERTAIN", "UNLABELED"}
SUPPORTED_MODEL_TYPES = {"prototype_similarity", "pu_prototype_ranker", "pu_dataset_prototype_ranker"}
DEFAULT_SPLIT_CONFIG = {
    "method": "purged_chronological",
    "train_ratio": 0.5,
    "validation_ratio": 0.25,
    "test_ratio": 0.25,
    "horizon_bars": 1,
    "embargo_bars": 0,
}
DEFAULT_THRESHOLD_QUANTILES = [0.5, 0.6, 0.7, 0.8, 0.9]
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
    "pnl",
    "profit",
    "win",
)
FORBIDDEN_OUTPUT_TOKENS = (
    "buy_signal",
    "sell_signal",
    "trade_signal",
    "future_return",
    "fwd_ret",
    "mfe",
    "mae",
    "hit_tp",
    "hit_sl",
)
FEATURE_METADATA_COLUMNS = (
    "observation_id",
    "symbol",
    "interval",
    "bar_index",
    "decision_bar_index",
    "setup_bar_index",
    "feature_cutoff_bar_index",
    "bar_time",
    "feature_version",
    "data_version",
    "candidate_source",
    "candidate_reason",
)


def run_entry_logic_experiment(
    features_df: pd.DataFrame,
    annotations_df: pd.DataFrame,
    *,
    feature_cols: list[str],
    output_dir: str | Path,
    model_type: str = "prototype_similarity",
    split_config: dict[str, Any] | None = None,
    model_config: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    top_k: int = 10,
    review_queue_config: dict[str, Any] | None = None,
    experiment_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an entry-logic similarity experiment without outcome-label training.

    The runner learns only whether candidates resemble prior human ENTRY
    decisions. It does not predict future return and does not emit trade signals.
    """
    features = _prepare_features(features_df)
    annotations = _normalize_annotations(annotations_df)
    feature_cols = _validate_feature_cols(feature_cols)
    raw_model_config = dict(model_config or {})
    selected_model = str(raw_model_config.get("model_type", model_type))
    if selected_model not in SUPPORTED_MODEL_TYPES:
        raise ValueError(f"Unsupported entry logic model_type: {selected_model}")
    merged_model_config = {**raw_model_config, "model_type": selected_model}
    merged_split_config = _merge_split_config(split_config)
    metadata = dict(metadata or {})
    experiment_config = dict(experiment_config or {})
    warnings: list[str] = []

    labeled_dataset = _build_labeled_dataset(features, annotations, feature_cols)
    warnings.extend(labeled_dataset.attrs.get("warnings", []))
    unlabeled_dataset = _build_unlabeled_dataset(features, annotations, feature_cols)
    dataset = build_pu_dataset(features, annotations, feature_cols)

    split = _build_temporal_split(labeled_dataset, merged_split_config)
    split_summary = summarize_split(split)
    warnings.extend(split_summary.get("warnings", []))

    prototype = _fit_model_on_train(split.train, feature_cols, {**merged_model_config, "model_type": selected_model})
    warnings.extend(str(warning) for warning in prototype.get("warnings", []))

    scored_validation = _score_frame(split.validation, prototype, score_stage="validation")
    threshold_selection = _tune_threshold_on_validation(
        scored_validation,
        split.validation[["observation_id", "human_decision"]].copy(),
        metric=str(merged_model_config.get("threshold_metric", "precision_at_k")),
        candidate_thresholds=merged_model_config.get("candidate_thresholds"),
        top_k=top_k,
    )
    warnings.extend(threshold_selection.get("warnings", []))
    threshold = float(threshold_selection["selected_threshold"])

    scored_test = _score_frame(split.test, prototype, score_stage="test")
    test_metrics = _evaluate_on_test(
        scored_test,
        split.test[["observation_id", "human_decision"]].copy(),
        threshold=threshold,
        top_k=top_k,
    )
    warnings.extend(test_metrics.get("warnings", []))

    scored_unlabeled = _score_frame(unlabeled_dataset, prototype, score_stage="unlabeled")
    blocking_annotations = annotations.loc[annotations["human_decision"].isin(["ENTRY", "REJECT", "UNCERTAIN"])].copy()
    queue_config = _review_queue_config(review_queue_config, merged_model_config, threshold, top_k)
    review_queue = build_label_review_queue(scored_unlabeled, blocking_annotations, unlabeled_dataset, queue_config)
    _reject_forbidden_output_columns(review_queue)

    scores = pd.concat([scored_validation, scored_test, scored_unlabeled], ignore_index=True, sort=False)
    _reject_forbidden_output_columns(scores)

    merged_model_config.update(
        {
            "threshold": threshold,
            "score_name": "human_entry_similarity",
            "uses_outcome_labels": False,
            "unlabeled_as_negative": False,
        }
    )
    metrics = {
        "threshold_selection": threshold_selection,
        "split_summary": split_summary,
        "annotation_counts": _annotation_counts(annotations),
        "labeled_count": int(len(labeled_dataset)),
        "unlabeled_candidate_count": int(len(unlabeled_dataset)),
        **test_metrics,
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scores_path = out_dir / "entry_logic_scores.csv"
    queue_path = out_dir / "entry_review_queue.csv"
    manifest_path = out_dir / "entry_logic_experiment_manifest.json"
    scores.to_csv(scores_path, index=False)
    review_queue.to_csv(queue_path, index=False)

    manifest_config = _manifest_config(
        features=features,
        annotations=annotations,
        feature_cols=feature_cols,
        split_config=merged_split_config,
        model_config=merged_model_config,
        metadata=metadata,
        threshold=threshold,
        warnings=warnings,
    )
    manifest_config["annotation_counts"] = _annotation_counts(annotations)
    legacy_manifest = save_experiment_manifest(
        manifest_path,
        manifest_config,
        metrics,
        {
            "entry_logic_scores": scores_path.name,
            "entry_review_queue": queue_path.name,
        },
    )
    bundle = save_experiment_bundle(
        out_dir,
        manifest_config,
        metrics,
        report_markdown=_experiment_markdown_summary(manifest_config, test_metrics, warnings),
        review_queue=_records(review_queue),
        feature_quality=_feature_quality_summary(features, feature_cols),
        split_summary=split_summary,
        warnings=warnings,
        note=experiment_config.get("note"),
        created_at=legacy_manifest.get("created_at"),
    )
    manifest = bundle["manifest"]

    return {
        "experiment_id": manifest.get("experiment_id"),
        "dataset": dataset,
        "labeled_dataset": labeled_dataset,
        "unlabeled_dataset": unlabeled_dataset,
        "split": split,
        "split_summary": split_summary,
        "prototype": prototype,
        "scores": scores,
        "scored_validation": scored_validation,
        "scored_test": scored_test,
        "scored_unlabeled": scored_unlabeled,
        "threshold": threshold,
        "threshold_selection": threshold_selection,
        "metrics": metrics,
        "test_metrics": test_metrics,
        "review_queue": review_queue,
        "experiment_manifest": manifest,
        "manifest": manifest,
        "manifest_path": str(bundle["manifest_path"]),
        "legacy_manifest_path": str(manifest_path),
        "experiment_dir": str(bundle["experiment_dir"]),
        "warnings": list(dict.fromkeys(warnings)),
        "model_config": merged_model_config,
    }


def _normalize_annotations(annotations: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(annotations, pd.DataFrame):
        raise ValueError("annotations must be a pandas DataFrame")
    missing = [column for column in ("observation_id", "human_decision") if column not in annotations.columns]
    if missing:
        raise ValueError(f"annotations missing required columns: {', '.join(missing)}")
    working = annotations.copy()
    if working["observation_id"].isna().any():
        raise ValueError("observation_id is required in annotations")
    working["observation_id"] = working["observation_id"].astype(str)
    working["human_decision"] = working["human_decision"].astype(str).str.upper()
    unsupported = sorted(set(working["human_decision"]) - ALLOWED_HUMAN_DECISIONS)
    if unsupported:
        raise ValueError(f"Unsupported human_decision: {', '.join(unsupported)}")
    if "is_active" in working.columns:
        working = working.loc[working["is_active"].map(_is_active_value)].copy()
    duplicates = working["observation_id"].duplicated(keep=False)
    if duplicates.any():
        duplicate_ids = sorted(working.loc[duplicates, "observation_id"].unique().tolist())
        raise ValueError(f"multiple active annotations for observation_id: {', '.join(duplicate_ids)}")
    return working.reset_index(drop=True).copy()


def _build_labeled_dataset(
    features: pd.DataFrame,
    annotations: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    feature_cols = _validate_feature_cols(feature_cols)
    _require_columns(features, ["observation_id", *feature_cols], "features")
    normalized = _normalize_annotations(annotations)
    decisions = normalized[["observation_id", "human_decision"]].copy()
    merged = features.merge(decisions, on="observation_id", how="inner")
    labeled = merged.loc[merged["human_decision"].isin(["ENTRY", "REJECT"])].copy()
    if not (labeled["human_decision"] == "ENTRY").any():
        raise ValueError("At least one ENTRY annotation is required for entry logic experiment")
    warnings: list[str] = []
    if not (labeled["human_decision"] == "REJECT").any():
        warnings.append("no_reject_labels")
    keep_cols = _ordered_unique(
        [
            "observation_id",
            "human_decision",
            "symbol",
            "interval",
            "bar_index",
            "decision_bar_index",
            "setup_bar_index",
            "feature_cutoff_bar_index",
            "bar_time",
            "feature_version",
            "data_version",
            "candidate_source",
            "candidate_reason",
            *feature_cols,
        ]
    )
    output = labeled[[column for column in keep_cols if column in labeled.columns]].reset_index(drop=True).copy()
    output.attrs["warnings"] = warnings
    return output


def _build_unlabeled_dataset(
    features: pd.DataFrame,
    annotations: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    feature_cols = _validate_feature_cols(feature_cols)
    _require_columns(features, ["observation_id", *feature_cols], "features")
    normalized = _normalize_annotations(annotations)
    blocking_ids = set(
        normalized.loc[normalized["human_decision"].isin(["ENTRY", "REJECT", "UNCERTAIN"]), "observation_id"].astype(str)
    )
    candidates = features.loc[~features["observation_id"].astype(str).isin(blocking_ids)].copy()
    keep_cols = _ordered_unique(
        [
            "observation_id",
            "symbol",
            "interval",
            "bar_index",
            "decision_bar_index",
            "setup_bar_index",
            "feature_cutoff_bar_index",
            "bar_time",
            "feature_version",
            "data_version",
            "candidate_source",
            "candidate_reason",
            *feature_cols,
        ]
    )
    return candidates[[column for column in keep_cols if column in candidates.columns]].reset_index(drop=True).copy()


def _build_temporal_split(labeled_df: pd.DataFrame, split_config: dict[str, Any]) -> SplitResult:
    if not isinstance(labeled_df, pd.DataFrame):
        raise ValueError("labeled_df must be a pandas DataFrame")
    if len(labeled_df) < 3:
        raise ValueError("entry logic temporal split requires at least 3 labeled ENTRY/REJECT samples")
    config = _merge_split_config(split_config)
    method = str(config.get("method", "purged_chronological"))
    train_ratio = float(config.get("train_ratio", DEFAULT_SPLIT_CONFIG["train_ratio"]))
    validation_ratio = float(config.get("validation_ratio", config.get("val_ratio", DEFAULT_SPLIT_CONFIG["validation_ratio"])))
    test_ratio = float(config.get("test_ratio", DEFAULT_SPLIT_CONFIG["test_ratio"]))
    if method == "purged_chronological":
        return build_purged_chronological_split(
            labeled_df,
            train_ratio=train_ratio,
            validation_ratio=validation_ratio,
            test_ratio=test_ratio,
            horizon_bars=int(config.get("horizon_bars", DEFAULT_SPLIT_CONFIG["horizon_bars"])),
            embargo_bars=int(config.get("embargo_bars", DEFAULT_SPLIT_CONFIG["embargo_bars"])),
            episode_gap_bars=config.get("episode_gap_bars"),
        )
    if method == "chronological":
        legacy = chronological_train_val_test_split(labeled_df, train_ratio, validation_ratio, test_ratio)
        train = legacy["train"].reset_index(drop=True).copy()
        validation = legacy["val"].reset_index(drop=True).copy()
        test = legacy["test"].reset_index(drop=True).copy()
        warnings = ["chronological_split_without_purge"]
        summary = {
            "split_method": "chronological",
            "original_count": int(len(labeled_df)),
            "train_count": int(len(train)),
            "validation_count": int(len(validation)),
            "val_count": int(len(validation)),
            "test_count": int(len(test)),
            "purged_count": 0,
            "embargoed_count": 0,
            "episode_leakage_count": 0,
            "horizon_bars": None,
            "embargo_bars": 0,
            "warnings": warnings,
        }
        return SplitResult(train=train, validation=validation, test=test, summary=summary, warnings=warnings)
    raise ValueError(f"Unsupported entry logic split method: {method}")


def _fit_model_on_train(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    model_config: dict[str, Any],
) -> dict[str, Any]:
    if train_df.empty:
        raise ValueError("train split is empty")
    feature_cols = _validate_feature_cols(feature_cols)
    model_type = str(model_config.get("model_type", "prototype_similarity"))
    if model_type not in SUPPORTED_MODEL_TYPES:
        raise ValueError(f"Unsupported entry logic model_type: {model_type}")
    train_annotations = train_df[["observation_id", "human_decision"]].copy()
    train_features = train_df.drop(columns=["human_decision"])
    prototype = fit_entry_prototype(train_features, train_annotations, feature_cols)
    prototype["model_type"] = model_type
    prototype["trained_on_split"] = "train"
    prototype["reject_used_for_prototype_center"] = False
    prototype["uses_outcome_labels"] = False
    if model_type in {"pu_prototype_ranker", "pu_dataset_prototype_ranker"}:
        pu_dataset = build_pu_dataset(train_features, train_annotations, feature_cols)
        prototype["pu_dataset_role_counts"] = {
            str(role): int(count) for role, count in pu_dataset["pu_role"].value_counts().sort_index().items()
        }
    return prototype


def _tune_threshold_on_validation(
    validation_scores: pd.DataFrame,
    validation_annotations: pd.DataFrame,
    metric: str = "precision_at_k",
    candidate_thresholds: list[float] | None = None,
    *,
    top_k: int = 10,
) -> dict[str, Any]:
    evaluated = _evaluated_rows(validation_scores, validation_annotations)
    warnings: list[str] = []
    if evaluated.empty:
        warnings.append("empty_validation_labels")
        return {
            "selected_on": "validation",
            "test_used_for_threshold": False,
            "selected_threshold": 0.5,
            "threshold": 0.5,
            "validation_metric": None,
            "validation_precision_at_k": None,
            "validation_recall_on_entry": None,
            "validation_reject_rate_above_threshold": None,
            "candidate_thresholds": [],
            "warnings": warnings,
        }
    entry_count = int((evaluated["human_decision"] == "ENTRY").sum())
    reject_count = int((evaluated["human_decision"] == "REJECT").sum())
    if entry_count == 0:
        warnings.append("validation_has_no_entry_labels")
    if reject_count == 0:
        warnings.append("validation_has_no_reject_labels")
    thresholds = _candidate_thresholds(evaluated["human_entry_similarity"], candidate_thresholds)
    best_threshold = thresholds[0]
    best_metrics = _validation_threshold_metrics(evaluated, best_threshold, top_k=top_k)
    best_key = _validation_sort_key(best_metrics, metric, best_threshold)
    for threshold in thresholds[1:]:
        metrics = _validation_threshold_metrics(evaluated, threshold, top_k=top_k)
        sort_key = _validation_sort_key(metrics, metric, threshold)
        if sort_key > best_key:
            best_threshold = threshold
            best_metrics = metrics
            best_key = sort_key
    validation_metric = best_metrics.get(f"validation_{metric}")
    if validation_metric is None and metric == "precision_at_k":
        validation_metric = best_metrics.get("validation_precision_at_k")
    return {
        "selected_on": "validation",
        "test_used_for_threshold": False,
        "selected_threshold": float(best_threshold),
        "threshold": float(best_threshold),
        "validation_metric": _none_or_float(validation_metric),
        "validation_precision_at_k": best_metrics["validation_precision_at_k"],
        "validation_recall_on_entry": best_metrics["validation_recall_on_entry"],
        "validation_reject_rate_above_threshold": best_metrics["validation_reject_rate_above_threshold"],
        "candidate_thresholds": [float(value) for value in thresholds],
        "validation_entry_count": entry_count,
        "validation_reject_count": reject_count,
        "warnings": warnings,
    }


def _evaluate_on_test(
    test_scores: pd.DataFrame,
    test_annotations: pd.DataFrame,
    threshold: float,
    top_k: int,
) -> dict[str, Any]:
    evaluated = _evaluated_rows(test_scores, test_annotations)
    warnings: list[str] = []
    if evaluated.empty:
        warnings.append("empty_test_labels")
        return {
            "threshold": float(threshold),
            "test_precision_at_k": None,
            "test_recall_on_entry": None,
            "test_reject_rate_in_top_k": None,
            "test_entry_count": 0,
            "test_reject_count": 0,
            "score_distribution": _score_distribution(evaluated),
            "calibration_by_decile": _calibration_by_decile(evaluated),
            "score_summary_by_decision": {},
            "warnings": warnings,
        }
    metrics = _test_threshold_metrics(evaluated, threshold, top_k=top_k)
    entry_count = int((evaluated["human_decision"] == "ENTRY").sum())
    reject_count = int((evaluated["human_decision"] == "REJECT").sum())
    if entry_count == 0:
        warnings.append("test_has_no_entry_labels")
    if reject_count == 0:
        warnings.append("test_has_no_reject_labels")
    return {
        "threshold": float(threshold),
        "test_precision_at_k": metrics["test_precision_at_k"],
        "test_recall_on_entry": metrics["test_recall_on_entry"],
        "test_reject_rate_in_top_k": metrics["test_reject_rate_in_top_k"],
        "test_entry_count": entry_count,
        "test_reject_count": reject_count,
        "score_distribution": _score_distribution(evaluated),
        "calibration_by_decile": _calibration_by_decile(evaluated),
        "score_summary_by_decision": _score_summary_by_decision(evaluated),
        "warnings": warnings,
    }


def _validation_threshold_metrics(evaluated: pd.DataFrame, threshold: float, *, top_k: int) -> dict[str, float | None]:
    ranked = _rank_scores(evaluated)
    cutoff = max(0, min(int(top_k), len(ranked)))
    top = ranked.head(cutoff)
    entry_total = int((ranked["human_decision"] == "ENTRY").sum())
    reject_total = int((ranked["human_decision"] == "REJECT").sum())
    above = ranked["human_entry_similarity"] >= float(threshold)
    precision = float((top["human_decision"] == "ENTRY").sum() / cutoff) if cutoff else None
    recall = float(((ranked["human_decision"] == "ENTRY") & above).sum() / entry_total) if entry_total else None
    reject_rate = float(((ranked["human_decision"] == "REJECT") & above).sum() / reject_total) if reject_total else None
    return {
        "validation_precision_at_k": precision,
        "validation_recall_on_entry": recall,
        "validation_reject_rate_above_threshold": reject_rate,
    }


def _test_threshold_metrics(evaluated: pd.DataFrame, threshold: float, *, top_k: int) -> dict[str, float | None]:
    ranked = _rank_scores(evaluated)
    cutoff = max(0, min(int(top_k), len(ranked)))
    top = ranked.head(cutoff)
    entry_total = int((ranked["human_decision"] == "ENTRY").sum())
    reject_total = int((ranked["human_decision"] == "REJECT").sum())
    above = ranked["human_entry_similarity"] >= float(threshold)
    precision = float((top["human_decision"] == "ENTRY").sum() / cutoff) if cutoff else None
    recall = float(((ranked["human_decision"] == "ENTRY") & above).sum() / entry_total) if entry_total else None
    reject_rate_top = float((top["human_decision"] == "REJECT").sum() / cutoff) if reject_total and cutoff else None
    return {
        "test_precision_at_k": precision,
        "test_recall_on_entry": recall,
        "test_reject_rate_in_top_k": reject_rate_top,
    }


def _candidate_thresholds(scores: pd.Series, candidate_thresholds: list[float] | None) -> list[float]:
    clean = pd.to_numeric(scores, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if candidate_thresholds is not None:
        candidates = [float(value) for value in candidate_thresholds]
    elif clean.empty:
        candidates = [0.5]
    else:
        candidates = [float(clean.quantile(q)) for q in DEFAULT_THRESHOLD_QUANTILES]
    candidates = [value for value in candidates if np.isfinite(value)]
    if not candidates:
        candidates = [0.5]
    return sorted(set(candidates), reverse=True)


def _validation_sort_key(metrics: dict[str, float | None], metric: str, threshold: float) -> tuple[float, float, float, float]:
    primary = metrics.get(f"validation_{metric}")
    if primary is None and metric == "precision_at_k":
        primary = metrics.get("validation_precision_at_k")
    reject_rate = metrics.get("validation_reject_rate_above_threshold")
    return (
        _metric_value(primary),
        _metric_value(metrics.get("validation_recall_on_entry")),
        -_metric_value(reject_rate, none_value=0.0),
        float(threshold),
    )


def _evaluated_rows(scores: pd.DataFrame, annotations: pd.DataFrame) -> pd.DataFrame:
    if scores.empty:
        return pd.DataFrame(columns=["observation_id", "human_entry_similarity", "human_decision"])
    _require_columns(scores, ["observation_id", "human_entry_similarity"], "scores")
    _require_columns(annotations, ["observation_id", "human_decision"], "annotations")
    scored = scores[["observation_id", "human_entry_similarity"]].copy()
    scored["observation_id"] = scored["observation_id"].astype(str)
    scored["human_entry_similarity"] = pd.to_numeric(scored["human_entry_similarity"], errors="coerce")
    decisions = annotations[["observation_id", "human_decision"]].copy()
    decisions["observation_id"] = decisions["observation_id"].astype(str)
    decisions["human_decision"] = decisions["human_decision"].astype(str).str.upper()
    evaluated = scored.merge(decisions, on="observation_id", how="inner")
    evaluated = evaluated.loc[evaluated["human_decision"].isin(["ENTRY", "REJECT"])].copy()
    return evaluated.dropna(subset=["human_entry_similarity"]).reset_index(drop=True)


def _rank_scores(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    working = frame.copy()
    working["_observation_sort"] = working["observation_id"].astype(str)
    return working.sort_values(["human_entry_similarity", "_observation_sort"], ascending=[False, True], kind="stable")


def _prepare_features(features_df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(features_df, pd.DataFrame):
        raise ValueError("features_df must be a pandas DataFrame")
    if "observation_id" not in features_df.columns:
        raise ValueError("features_df missing required columns: observation_id")
    if "decision_bar_index" not in features_df.columns and "bar_index" not in features_df.columns:
        raise ValueError("features_df must contain decision_bar_index or bar_index")
    features = features_df.copy()
    features["observation_id"] = features["observation_id"].astype(str)
    if features["observation_id"].duplicated().any():
        duplicates = sorted(features.loc[features["observation_id"].duplicated(keep=False), "observation_id"].unique().tolist())
        raise ValueError(f"features_df contains duplicate observation_id: {', '.join(duplicates)}")
    if "decision_bar_index" not in features.columns:
        features["decision_bar_index"] = pd.to_numeric(features["bar_index"], errors="coerce").astype(int)
    bar_col = "decision_bar_index" if "decision_bar_index" in features.columns else "bar_index"
    features["_entry_logic_input_order"] = range(len(features))
    sort_columns = [bar_col]
    if "bar_time" in features.columns:
        sort_columns.append("bar_time")
    sort_columns.append("_entry_logic_input_order")
    features = features.sort_values(sort_columns, kind="stable")
    return features.drop(columns=["_entry_logic_input_order"]).reset_index(drop=True)


def _score_frame(frame: pd.DataFrame, prototype: dict[str, Any], *, score_stage: str) -> pd.DataFrame:
    scores = score_entry_similarity(frame, prototype)
    if "entry_logic_score" not in scores.columns:
        scores.insert(1, "entry_logic_score", scores["human_entry_similarity"])
    scores = _attach_score_metadata(scores, frame)
    scores["score_stage"] = str(score_stage)
    _reject_forbidden_output_columns(scores)
    return scores.reset_index(drop=True).copy()


def _attach_score_metadata(scores: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    metadata_cols = [column for column in FEATURE_METADATA_COLUMNS if column in features.columns and column != "observation_id"]
    if not metadata_cols:
        return scores.copy()
    metadata = features[["observation_id", *metadata_cols]].copy()
    metadata["observation_id"] = metadata["observation_id"].astype(str)
    output = scores.copy()
    output["observation_id"] = output["observation_id"].astype(str)
    return output.merge(metadata, on="observation_id", how="left")


def _review_queue_config(
    review_queue_config: dict[str, Any] | None,
    model_config: dict[str, Any],
    threshold: float,
    top_k: int,
) -> dict[str, Any]:
    config = dict(review_queue_config or {})
    config.setdefault("name", "high_similarity")
    config.setdefault("top_k", int(top_k))
    config.setdefault("queue_version", _queue_version(model_config, threshold))
    return config


def _merge_split_config(split_config: dict[str, Any] | None) -> dict[str, Any]:
    provided = dict(split_config or {})
    config = dict(DEFAULT_SPLIT_CONFIG)
    config.update(provided)
    if "validation_ratio" not in provided and "val_ratio" in provided:
        config["validation_ratio"] = provided["val_ratio"]
    config.setdefault("val_ratio", config.get("validation_ratio"))
    return config


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


def _require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{name} missing required columns: {', '.join(missing)}")


def _is_active_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "inactive"}
    if value is None or pd.isna(value):
        return True
    return bool(value)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _metric_value(value: Any, *, none_value: float = -1.0) -> float:
    if value is None:
        return none_value
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return none_value
    return numeric if np.isfinite(numeric) else none_value


def _none_or_float(value: Any) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    return numeric if np.isfinite(numeric) else None


def _score_distribution(frame: pd.DataFrame) -> dict[str, float | int | None]:
    values = pd.to_numeric(frame.get("human_entry_similarity"), errors="coerce").dropna()
    if values.empty:
        return {"count": 0, "min": None, "q25": None, "median": None, "q75": None, "max": None}
    return {
        "count": int(len(values)),
        "min": float(values.min()),
        "q25": float(values.quantile(0.25)),
        "median": float(values.median()),
        "q75": float(values.quantile(0.75)),
        "max": float(values.max()),
    }


def _calibration_by_decile(frame: pd.DataFrame) -> list[dict[str, float | int | None]]:
    if frame.empty:
        return []
    working = frame.copy()
    working["human_entry_similarity"] = pd.to_numeric(working["human_entry_similarity"], errors="coerce")
    working = working.dropna(subset=["human_entry_similarity"])
    if working.empty:
        return []
    bucket_count = min(10, len(working))
    ranks = working["human_entry_similarity"].rank(method="first", ascending=True)
    working["score_decile"] = pd.qcut(ranks, q=bucket_count, labels=False, duplicates="drop")
    rows: list[dict[str, float | int | None]] = []
    for decile, group in working.sort_values("score_decile").groupby("score_decile", sort=True):
        count = int(len(group))
        entry_count = int((group["human_decision"] == "ENTRY").sum())
        rows.append(
            {
                "decile": int(decile) + 1 if pd.notna(decile) else None,
                "count": count,
                "entry_count": entry_count,
                "entry_rate": float(entry_count / count) if count else None,
                "score_min": float(group["human_entry_similarity"].min()),
                "score_max": float(group["human_entry_similarity"].max()),
            }
        )
    return rows


def _score_summary_by_decision(frame: pd.DataFrame) -> dict[str, dict[str, float | int | None]]:
    if frame.empty:
        return {}
    result: dict[str, dict[str, float | int | None]] = {}
    for decision, group in frame.groupby("human_decision", sort=True):
        result[str(decision)] = _score_distribution(group)
    return result


def _annotation_counts(annotations: pd.DataFrame) -> dict[str, int]:
    if annotations.empty or "human_decision" not in annotations.columns:
        return {decision: 0 for decision in sorted(ALLOWED_HUMAN_DECISIONS)}
    counts = annotations["human_decision"].astype(str).str.upper().value_counts()
    return {decision: int(counts.get(decision, 0)) for decision in ("ENTRY", "REJECT", "UNCERTAIN", "UNLABELED")}


def _feature_quality_summary(features: pd.DataFrame, feature_cols: list[str]) -> dict[str, Any]:
    present = [feature for feature in feature_cols if feature in features.columns]
    nan_ratio = {}
    constant_cols = []
    forbidden = []
    for feature in present:
        lowered = str(feature).lower()
        if any(token in lowered for token in FORBIDDEN_FEATURE_TOKENS):
            forbidden.append(feature)
        values = pd.to_numeric(features[feature], errors="coerce")
        nan_ratio[feature] = float(values.isna().mean()) if len(values) else 0.0
        if values.dropna().nunique() <= 1:
            constant_cols.append(feature)
    bar_col = "decision_bar_index" if "decision_bar_index" in features.columns else "bar_index"
    feature_timing = _feature_timing_metadata(features, {})
    return {
        "row_count": int(len(features)),
        "feature_count": int(len(present)),
        "nan_ratio_by_col": nan_ratio,
        "constant_feature_cols": constant_cols,
        "forbidden_fields_detected": forbidden,
        "min_bar_index": int(pd.to_numeric(features[bar_col], errors="coerce").min()) if not features.empty else None,
        "max_bar_index": int(pd.to_numeric(features[bar_col], errors="coerce").max()) if not features.empty else None,
        "feature_timing_policy": feature_timing["feature_timing_policy"],
        "allow_confirmation_bar": feature_timing["allow_confirmation_bar"],
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    clean = frame.replace({np.nan: None})
    return clean.to_dict(orient="records")


def _experiment_markdown_summary(config: dict[str, Any], test_metrics: dict[str, Any], warnings: list[str]) -> str:
    lines = [
        "# Entry Logic Experiment",
        "",
        "This experiment learns human ENTRY similarity. It is not a trading signal and does not predict future returns.",
        "",
        f"- experiment_id: {config.get('experiment_id') or 'pending'}",
        f"- model_type: {config.get('model_type')}",
        f"- split_method: {config.get('split_method')}",
        f"- feature_version: {config.get('feature_version')}",
        f"- annotation_version: {config.get('annotation_version')}",
        f"- label_version: {config.get('label_version')}",
        f"- threshold: {config.get('threshold')}",
        f"- test_precision_at_k: {test_metrics.get('test_precision_at_k')}",
        f"- test_recall_on_entry: {test_metrics.get('test_recall_on_entry')}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("- none")
    return "\n".join(lines) + "\n"


def _manifest_config(
    *,
    features: pd.DataFrame,
    annotations: pd.DataFrame,
    feature_cols: list[str],
    split_config: dict[str, Any],
    model_config: dict[str, Any],
    metadata: dict[str, Any],
    threshold: float,
    warnings: list[str],
) -> dict[str, Any]:
    feature_version = _first_available(
        metadata.get("feature_version"),
        _first_non_null(features, "feature_version"),
        features.attrs.get("feature_version"),
        "unknown",
    )
    annotation_version = _first_available(
        metadata.get("annotation_version"),
        _first_non_null(annotations, "annotation_version"),
        "unknown",
    )
    feature_timing = _feature_timing_metadata(features, metadata)
    return {
        "app_version": metadata.get("app_version", "unknown"),
        "symbol": _first_available(metadata.get("symbol"), _first_non_null(features, "symbol"), "unknown"),
        "interval": _first_available(metadata.get("interval"), _first_non_null(features, "interval"), "unknown"),
        "data_start": _first_available(metadata.get("data_start"), _min_value(features, "bar_time")),
        "data_end": _first_available(metadata.get("data_end"), _max_value(features, "bar_time")),
        "annotation_version": annotation_version,
        "feature_version": feature_version,
        "feature_timing_policy": feature_timing["feature_timing_policy"],
        "allow_confirmation_bar": feature_timing["allow_confirmation_bar"],
        "feature_cols": list(feature_cols),
        "split_method": split_config.get("method"),
        "embargo_bars": split_config.get("embargo_bars", 0),
        "model_type": model_config.get("model_type"),
        "model_params": dict(model_config),
        "warnings": list(dict.fromkeys(warnings)),
        "data_hash": _first_available(metadata.get("data_hash"), features.attrs.get("data_hash")),
        "data_version": _first_available(metadata.get("data_version"), features.attrs.get("data_version"), _first_non_null(features, "data_version")),
        "label_version": metadata.get("label_version"),
        "split_config": dict(split_config),
        "model_config": dict(model_config),
        "threshold": float(threshold),
    }


def _feature_timing_metadata(features: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
    quality = features.attrs.get("feature_quality_report", {}) if isinstance(features, pd.DataFrame) else {}
    spec = features.attrs.get("feature_spec", {}) if isinstance(features, pd.DataFrame) else {}
    allow_confirmation = _first_available(
        metadata.get("allow_confirmation_bar"),
        spec.get("allow_confirmation_bar") if isinstance(spec, dict) else None,
        quality.get("allow_confirmation_bar") if isinstance(quality, dict) else None,
    )
    policy = _first_available(
        metadata.get("feature_timing_policy"),
        spec.get("feature_timing_policy") if isinstance(spec, dict) else None,
    )
    if policy is None:
        observed_policy = quality.get("feature_timing_policy") if isinstance(quality, dict) else None
        if isinstance(observed_policy, str) and "," not in observed_policy:
            policy = observed_policy
        elif allow_confirmation is not None:
            policy = "confirmation_bar_included" if bool(allow_confirmation) else "setup_bar_only"
        else:
            policy = observed_policy
    return {
        "feature_timing_policy": policy,
        "allow_confirmation_bar": bool(allow_confirmation) if allow_confirmation is not None else None,
    }

def _first_available(*values: Any) -> Any:
    for value in values:
        if value is not None and not (isinstance(value, float) and np.isnan(value)):
            return value
    return None


def _first_non_null(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame.columns:
        return None
    values = frame[column].dropna()
    if values.empty:
        return None
    return values.iloc[0]


def _min_value(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame.columns or frame.empty:
        return None
    return frame[column].min()


def _max_value(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame.columns or frame.empty:
        return None
    return frame[column].max()


def _queue_version(model_config: dict[str, Any], threshold: float) -> str:
    return f"entry_logic_experiment_{model_config.get('model_type')}_{threshold:.12g}"


def _reject_forbidden_output_columns(frame: pd.DataFrame) -> None:
    lowered = " ".join(str(column).lower() for column in frame.columns)
    if any(token in lowered for token in FORBIDDEN_OUTPUT_TOKENS):
        raise ValueError("entry logic experiment output contains forbidden fields")


__all__ = [
    "run_entry_logic_experiment",
    "_normalize_annotations",
    "_build_labeled_dataset",
    "_build_unlabeled_dataset",
    "_build_temporal_split",
    "_fit_model_on_train",
    "_tune_threshold_on_validation",
    "_evaluate_on_test",
]

