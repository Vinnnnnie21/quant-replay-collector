from __future__ import annotations

import json
from types import MappingProxyType
from typing import Mapping

from .entry_behavior_model import (
    BehaviorModelTarget,
    BehaviorModelMetrics,
    EntryBehaviorExperimentStatus,
    EntryBehaviorFailure,
    EntryBehaviorModelManifest,
    EntryBehaviorModelMaturity,
    EntryBehaviorModelVersion,
    EntryBehaviorTrainingResult,
    FeatureNormalization,
    FoldRegularizationEvaluation,
    LeaveEpisodeOutSimilarity,
    RegularizationPathSummary,
    ResearchThresholdCandidate,
    StableBehaviorFeature,
    TemporalFoldAudit,
)


def _metrics_to_dict(metrics: BehaviorModelMetrics) -> dict[str, object]:
    return {
        "sample_count": metrics.sample_count,
        "label_counts": list(metrics.label_counts),
        "episode_counts": list(metrics.episode_counts),
        "balanced_log_loss": metrics.balanced_log_loss,
        "brier_score": metrics.brier_score,
        "recall": metrics.recall,
        "precision": metrics.precision,
    }


def _metrics_from_dict(value: Mapping[str, object]) -> BehaviorModelMetrics:
    return BehaviorModelMetrics(
        sample_count=int(value["sample_count"]),
        label_counts=tuple(
            (str(item[0]), int(item[1])) for item in value["label_counts"]
        ),
        episode_counts=tuple(
            (str(item[0]), int(item[1]))
            for item in value["episode_counts"]
        ),
        balanced_log_loss=float(value["balanced_log_loss"]),
        brier_score=float(value["brier_score"]),
        recall=(
            None if value["recall"] is None else float(value["recall"])
        ),
        precision=(
            None
            if value["precision"] is None
            else float(value["precision"])
        ),
    )


def entry_behavior_result_to_json(result: EntryBehaviorTrainingResult) -> str:
    return json.dumps(
        _result_to_dict(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def entry_behavior_model_to_json(model: EntryBehaviorModelVersion) -> str:
    return json.dumps(
        _model_to_dict(model),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def entry_behavior_result_from_json(payload: str) -> EntryBehaviorTrainingResult:
    value = json.loads(str(payload))
    model_value = value.get("model")
    model = _model_from_dict(model_value) if model_value is not None else None
    failure_value = value.get("failure")
    return EntryBehaviorTrainingResult(
        experiment_id=str(value["experiment_id"]),
        setup_version_id=str(value["setup_version_id"]),
        grouping_version_id=str(value["grouping_version_id"]),
        direction=str(value["direction"]),
        status=EntryBehaviorExperimentStatus(value["status"]),
        created_at=str(value["created_at"]),
        failure=(
            EntryBehaviorFailure(
                code=str(failure_value["code"]),
                message_zh=str(failure_value["message_zh"]),
            )
            if failure_value is not None
            else None
        ),
        model=model,
        target=BehaviorModelTarget(
            value.get("target", BehaviorModelTarget.ENTRY_SELECTION.value)
        ),
    )


def entry_behavior_model_from_json(payload: str) -> EntryBehaviorModelVersion:
    return _model_from_dict(json.loads(str(payload)))


def _result_to_dict(result: EntryBehaviorTrainingResult) -> dict[str, object]:
    return {
        "experiment_id": result.experiment_id,
        "setup_version_id": result.setup_version_id,
        "grouping_version_id": result.grouping_version_id,
        "direction": result.direction,
        "status": result.status.value,
        "created_at": result.created_at,
        "target": result.target.value,
        "failure": (
            None
            if result.failure is None
            else {
                "code": result.failure.code,
                "message_zh": result.failure.message_zh,
            }
        ),
        "model": None if result.model is None else _model_to_dict(result.model),
    }


def _model_to_dict(model: EntryBehaviorModelVersion) -> dict[str, object]:
    manifest = model.manifest
    return {
        "model_version_id": model.model_version_id,
        "experiment_id": model.experiment_id,
        "setup_version_id": model.setup_version_id,
        "grouping_version_id": model.grouping_version_id,
        "direction": model.direction,
        "target": model.target.value,
        "maturity": model.maturity.value,
        "intercept": model.intercept,
        "stable_features": [
            {
                "feature_id": item.feature_id,
                "name_zh": item.name_zh,
                "coefficient": item.coefficient,
                "nonzero_fold_count": item.nonzero_fold_count,
                "fold_count": item.fold_count,
                "fold_coefficient_min": item.fold_coefficient_min,
                "fold_coefficient_max": item.fold_coefficient_max,
            }
            for item in model.stable_features
        ],
        "research_threshold": model.research_threshold,
        "applicability_threshold": model.applicability_threshold,
        "created_at": model.created_at,
        "manifest": {
            "formula_version": manifest.formula_version,
            "feature_version": manifest.feature_version,
            "app_version": manifest.app_version,
            "seed": manifest.seed,
            "label_counts": list(manifest.label_counts),
            "sample_ids": list(manifest.sample_ids),
            "episode_ids": list(manifest.episode_ids),
            "data_start_utc_ms": manifest.data_start_utc_ms,
            "data_end_utc_ms": manifest.data_end_utc_ms,
            "feature_limit": manifest.feature_limit,
            "selected_c": manifest.selected_c,
            "l1_ratio": manifest.l1_ratio,
            "normalizations": [
                {
                    "feature_id": item.feature_id,
                    "name_zh": item.name_zh,
                    "median": item.median,
                    "mad": item.mad,
                    "scale": item.scale,
                }
                for item in manifest.normalizations
            ],
            "temporal_folds": [
                {
                    "fold_index": fold.fold_index,
                    "train_episode_ids": list(fold.train_episode_ids),
                    "validation_episode_ids": list(
                        fold.validation_episode_ids
                    ),
                    "train_sample_ids": list(fold.train_sample_ids),
                    "validation_sample_ids": list(
                        fold.validation_sample_ids
                    ),
                    "train_end_utc_ms": fold.train_end_utc_ms,
                    "validation_start_utc_ms": (
                        fold.validation_start_utc_ms
                    ),
                    "validation_end_utc_ms": fold.validation_end_utc_ms,
                    "normalizations": [
                        {
                            "feature_id": item.feature_id,
                            "name_zh": item.name_zh,
                            "median": item.median,
                            "mad": item.mad,
                            "scale": item.scale,
                        }
                        for item in fold.normalizations
                    ],
                    "validation_labels": list(fold.validation_labels),
                    "label_counts": list(fold.label_counts),
                    "class_weights": list(fold.class_weights),
                    "regularization_evaluations": [
                        {
                            "c_value": item.c_value,
                            "balanced_log_loss": item.balanced_log_loss,
                            "nonzero_count": item.nonzero_count,
                            "coefficients": list(item.coefficients),
                            "validation_probabilities": list(
                                item.validation_probabilities
                            ),
                        }
                        for item in fold.regularization_evaluations
                    ],
                }
                for fold in manifest.temporal_folds
            ],
            "regularization_path": [
                {
                    "c_value": item.c_value,
                    "mean_balanced_log_loss": (
                        item.mean_balanced_log_loss
                    ),
                    "standard_error": item.standard_error,
                    "maximum_nonzero_count": item.maximum_nonzero_count,
                }
                for item in manifest.regularization_path
            ],
            "threshold_candidates": [
                {
                    "threshold": item.threshold,
                    "mean_recall": item.mean_recall,
                    "minimum_fold_recall": item.minimum_fold_recall,
                    "mean_precision": item.mean_precision,
                }
                for item in manifest.threshold_candidates
            ],
            "threshold_selection": (
                None
                if manifest.threshold_selection is None
                else {
                    "threshold": manifest.threshold_selection.threshold,
                    "mean_recall": manifest.threshold_selection.mean_recall,
                    "minimum_fold_recall": (
                        manifest.threshold_selection.minimum_fold_recall
                    ),
                    "mean_precision": (
                        manifest.threshold_selection.mean_precision
                    ),
                }
            ),
            "validation_metrics": _metrics_to_dict(
                manifest.validation_metrics
            ),
            "test_episode_ids": list(manifest.test_episode_ids),
            "test_sample_ids": list(manifest.test_sample_ids),
            "test_metrics": _metrics_to_dict(manifest.test_metrics),
            "leave_episode_out_scores": [
                {
                    "decision_event_id": item.decision_event_id,
                    "episode_id": item.episode_id,
                    "reference_episode_ids": list(
                        item.reference_episode_ids
                    ),
                    "similarity": item.similarity,
                }
                for item in manifest.leave_episode_out_scores
            ],
            "dependency_versions": dict(manifest.dependency_versions),
            "label_fingerprint": manifest.label_fingerprint,
            "target": manifest.target.value,
            "positive_label": manifest.positive_label,
            "negative_label": manifest.negative_label,
            "episode_kind": manifest.episode_kind,
        },
    }


def _model_from_dict(value: Mapping[str, object]) -> EntryBehaviorModelVersion:
    manifest_value = value["manifest"]
    if not isinstance(manifest_value, Mapping):
        raise ValueError("entry behavior model manifest must be a mapping")
    normalizations_value = manifest_value["normalizations"]
    stable_value = value["stable_features"]
    return EntryBehaviorModelVersion(
        model_version_id=str(value["model_version_id"]),
        experiment_id=str(value["experiment_id"]),
        setup_version_id=str(value["setup_version_id"]),
        grouping_version_id=str(value["grouping_version_id"]),
        direction=str(value["direction"]),
        maturity=EntryBehaviorModelMaturity(str(value["maturity"])),
        intercept=float(value["intercept"]),
        stable_features=tuple(
            StableBehaviorFeature(
                feature_id=str(item["feature_id"]),
                name_zh=str(item["name_zh"]),
                coefficient=float(item["coefficient"]),
                nonzero_fold_count=int(item["nonzero_fold_count"]),
                fold_count=int(item["fold_count"]),
                fold_coefficient_min=float(
                    item["fold_coefficient_min"]
                ),
                fold_coefficient_max=float(
                    item["fold_coefficient_max"]
                ),
            )
            for item in stable_value
        ),
        research_threshold=(
            None
            if value.get("research_threshold") is None
            else float(value["research_threshold"])
        ),
        applicability_threshold=(
            None
            if value.get("applicability_threshold") is None
            else float(value["applicability_threshold"])
        ),
        created_at=str(value["created_at"]),
        target=BehaviorModelTarget(
            value.get("target", BehaviorModelTarget.ENTRY_SELECTION.value)
        ),
        manifest=EntryBehaviorModelManifest(
            formula_version=str(manifest_value["formula_version"]),
            feature_version=str(manifest_value["feature_version"]),
            app_version=str(manifest_value["app_version"]),
            seed=int(manifest_value["seed"]),
            label_counts=tuple(
                (str(item[0]), int(item[1]))
                for item in manifest_value["label_counts"]
            ),
            sample_ids=tuple(str(item) for item in manifest_value["sample_ids"]),
            episode_ids=tuple(str(item) for item in manifest_value["episode_ids"]),
            data_start_utc_ms=int(manifest_value["data_start_utc_ms"]),
            data_end_utc_ms=int(manifest_value["data_end_utc_ms"]),
            feature_limit=int(manifest_value["feature_limit"]),
            selected_c=float(manifest_value["selected_c"]),
            l1_ratio=float(manifest_value["l1_ratio"]),
            normalizations=tuple(
                FeatureNormalization(
                    feature_id=str(item["feature_id"]),
                    name_zh=str(item["name_zh"]),
                    median=float(item["median"]),
                    mad=float(item["mad"]),
                    scale=float(item["scale"]),
                )
                for item in normalizations_value
            ),
            temporal_folds=tuple(
                TemporalFoldAudit(
                    fold_index=int(fold["fold_index"]),
                    train_episode_ids=tuple(
                        str(item) for item in fold["train_episode_ids"]
                    ),
                    validation_episode_ids=tuple(
                        str(item)
                        for item in fold["validation_episode_ids"]
                    ),
                    train_sample_ids=tuple(
                        str(item) for item in fold["train_sample_ids"]
                    ),
                    validation_sample_ids=tuple(
                        str(item)
                        for item in fold["validation_sample_ids"]
                    ),
                    train_end_utc_ms=int(fold["train_end_utc_ms"]),
                    validation_start_utc_ms=int(
                        fold["validation_start_utc_ms"]
                    ),
                    validation_end_utc_ms=int(
                        fold["validation_end_utc_ms"]
                    ),
                    normalizations=tuple(
                        FeatureNormalization(
                            feature_id=str(item["feature_id"]),
                            name_zh=str(item["name_zh"]),
                            median=float(item["median"]),
                            mad=float(item["mad"]),
                            scale=float(item["scale"]),
                        )
                        for item in fold["normalizations"]
                    ),
                    validation_labels=tuple(
                        int(item) for item in fold["validation_labels"]
                    ),
                    label_counts=tuple(
                        (str(item[0]), int(item[1]))
                        for item in fold["label_counts"]
                    ),
                    class_weights=tuple(
                        (str(item[0]), float(item[1]))
                        for item in fold["class_weights"]
                    ),
                    regularization_evaluations=tuple(
                        FoldRegularizationEvaluation(
                            c_value=float(item["c_value"]),
                            balanced_log_loss=float(
                                item["balanced_log_loss"]
                            ),
                            nonzero_count=int(item["nonzero_count"]),
                            coefficients=tuple(
                                (str(pair[0]), float(pair[1]))
                                for pair in item["coefficients"]
                            ),
                            validation_probabilities=tuple(
                                float(value)
                                for value in item[
                                    "validation_probabilities"
                                ]
                            ),
                        )
                        for item in fold["regularization_evaluations"]
                    ),
                )
                for fold in manifest_value["temporal_folds"]
            ),
            regularization_path=tuple(
                RegularizationPathSummary(
                    c_value=float(item["c_value"]),
                    mean_balanced_log_loss=float(
                        item["mean_balanced_log_loss"]
                    ),
                    standard_error=float(item["standard_error"]),
                    maximum_nonzero_count=int(
                        item["maximum_nonzero_count"]
                    ),
                )
                for item in manifest_value["regularization_path"]
            ),
            threshold_candidates=tuple(
                ResearchThresholdCandidate(
                    threshold=float(item["threshold"]),
                    mean_recall=float(item["mean_recall"]),
                    minimum_fold_recall=float(
                        item["minimum_fold_recall"]
                    ),
                    mean_precision=float(item["mean_precision"]),
                )
                for item in manifest_value["threshold_candidates"]
            ),
            threshold_selection=(
                None
                if manifest_value["threshold_selection"] is None
                else ResearchThresholdCandidate(
                    threshold=float(
                        manifest_value["threshold_selection"]["threshold"]
                    ),
                    mean_recall=float(
                        manifest_value["threshold_selection"]["mean_recall"]
                    ),
                    minimum_fold_recall=float(
                        manifest_value["threshold_selection"][
                            "minimum_fold_recall"
                        ]
                    ),
                    mean_precision=float(
                        manifest_value["threshold_selection"][
                            "mean_precision"
                        ]
                    ),
                )
            ),
            validation_metrics=_metrics_from_dict(
                manifest_value["validation_metrics"]
            ),
            test_episode_ids=tuple(
                str(item) for item in manifest_value["test_episode_ids"]
            ),
            test_sample_ids=tuple(
                str(item) for item in manifest_value["test_sample_ids"]
            ),
            test_metrics=_metrics_from_dict(manifest_value["test_metrics"]),
            leave_episode_out_scores=tuple(
                LeaveEpisodeOutSimilarity(
                    decision_event_id=str(item["decision_event_id"]),
                    episode_id=str(item["episode_id"]),
                    reference_episode_ids=tuple(
                        str(reference)
                        for reference in item["reference_episode_ids"]
                    ),
                    similarity=float(item["similarity"]),
                )
                for item in manifest_value.get(
                    "leave_episode_out_scores",
                    (),
                )
            ),
            dependency_versions=MappingProxyType(
                {
                    str(key): str(version)
                    for key, version in manifest_value[
                        "dependency_versions"
                    ].items()
                }
            ),
            label_fingerprint=str(manifest_value["label_fingerprint"]),
            target=BehaviorModelTarget(
                manifest_value.get(
                    "target",
                    BehaviorModelTarget.ENTRY_SELECTION.value,
                )
            ),
            positive_label=str(
                manifest_value.get("positive_label", "ENTRY")
            ),
            negative_label=str(
                manifest_value.get("negative_label", "REJECT")
            ),
            episode_kind=str(
                manifest_value.get("episode_kind", "MARKET")
            ),
        ),
    )


__all__ = [
    "entry_behavior_model_from_json",
    "entry_behavior_model_to_json",
    "entry_behavior_result_from_json",
    "entry_behavior_result_to_json",
]
