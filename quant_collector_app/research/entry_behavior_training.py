from __future__ import annotations

import math
import platform
import warnings
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

import joblib
import numpy as np
import scipy
import sklearn
import threadpoolctl
from sklearn.linear_model import LogisticRegression
from sklearn.exceptions import ConvergenceWarning

from .entry_behavior_model import (
    ENTRY_BEHAVIOR_C_GRID,
    ENTRY_BEHAVIOR_FORMULA_VERSION,
    ENTRY_BEHAVIOR_L1_RATIO,
    ENTRY_BEHAVIOR_PROFILE,
    BehaviorModelProfile,
    BehaviorModelTarget,
    BehaviorModelMetrics,
    EntryBehaviorExperimentStatus,
    EntryBehaviorFailure,
    EntryBehaviorModelManifest,
    EntryBehaviorModelMaturity,
    EntryBehaviorModelVersion,
    EntryBehaviorSample,
    EntryBehaviorTrainingRequest,
    EntryBehaviorTrainingResult,
    FeatureNormalization,
    FoldRegularizationEvaluation,
    LeaveEpisodeOutSimilarity,
    RegularizationPathSummary,
    ResearchThresholdCandidate,
    StableBehaviorFeature,
    TemporalFoldAudit,
    entry_behavior_label_fingerprint,
    behavior_model_profile,
)
from .entry_behavior_validation import (
    apply_normalizations,
    class_weights,
    episode_temporal_partition,
    label_counts as count_labels,
    labels as encode_labels,
    normalized_design,
)


class EntryBehaviorNumericalError(RuntimeError):
    pass


def fit_behavior_model(
    samples: Sequence[EntryBehaviorSample],
    *,
    request: EntryBehaviorTrainingRequest,
    app_version: str,
    experiment_id: str,
    model_version_id: str,
    created_at: str,
    cancelled: Callable[[], bool] | None = None,
    leave_episode_out_scores: Sequence[LeaveEpisodeOutSimilarity] = (),
) -> EntryBehaviorTrainingResult:
    profile = behavior_model_profile(request.target)
    ordered = tuple(
        sorted(
            samples,
            key=lambda item: (
                item.decision_cutoff_utc_ms,
                item.decision_event_id,
            ),
        )
    )
    label_counts = tuple(
        (label, sum(sample.label == label for sample in ordered))
        for label in (profile.positive_label, profile.negative_label)
    )
    if min(count for _label, count in label_counts) < 30:
        return _failed_result(
            request,
            experiment_id=experiment_id,
            created_at=created_at,
            code="INSUFFICIENT_LABELS",
            message_zh=profile.insufficient_labels_message_zh,
        )
    _raise_if_cancelled(cancelled)
    development, test, fold_pairs = episode_temporal_partition(
        ordered,
        profile=profile,
    )
    feature_limit = min(
        12,
        min(count for _label, count in label_counts) // 5,
    )
    try:
        temporal_folds = tuple(
            _fit_temporal_fold(
                index,
                train,
                validation,
                feature_limit,
                profile=profile,
                seed=request.seed,
                cancelled=cancelled,
            )
            for index, (train, validation) in enumerate(fold_pairs)
        )
    except EntryBehaviorNumericalError:
        return _numerical_failure(request, experiment_id, created_at)
    regularization_path = _summarize_regularization_path(temporal_folds)
    selected_c = _select_one_standard_error_c(
        regularization_path,
        feature_limit=feature_limit,
    )
    stable_across_folds = _stable_features_across_folds(
        temporal_folds,
        selected_c=selected_c,
        feature_limit=feature_limit,
        profile=profile,
    )
    threshold_candidates = _research_threshold_candidates(
        temporal_folds,
        selected_c=selected_c,
    )
    threshold_selection = _select_research_threshold(
        threshold_candidates
    )
    validation_samples = tuple(
        sample for _train, validation in fold_pairs for sample in validation
    )
    validation_probabilities = np.asarray(
        [
            probability
            for fold in temporal_folds
            for probability in next(
                item
                for item in fold.regularization_evaluations
                if item.c_value == selected_c
            ).validation_probabilities
        ],
        dtype=float,
    )
    validation_metrics = _model_metrics(
        validation_samples,
        validation_probabilities,
        profile=profile,
        threshold=(
            None
            if threshold_selection is None
            else threshold_selection.threshold
        ),
    )
    if not stable_across_folds:
        return _failed_result(
            request,
            experiment_id=experiment_id,
            created_at=created_at,
            code="NO_STABLE_FEATURES",
            message_zh="扩展窗口中没有符号一致的稳定指标。",
        )
    stable_ids = tuple(item[0] for item in stable_across_folds)
    normalizations, design, full_labels = normalized_design(
        development,
        max_features=feature_limit,
        feature_ids=stable_ids,
        profile=profile,
    )
    n = len(full_labels)
    positives = int(full_labels.sum())
    negatives = n - positives
    try:
        model = _fit_logistic_model(
            design,
            full_labels,
            c_value=selected_c,
            class_weight={
                0: n / (2 * negatives),
                1: n / (2 * positives),
            },
            seed=request.seed,
        )
    except EntryBehaviorNumericalError:
        return _numerical_failure(request, experiment_id, created_at)
    _raise_if_cancelled(cancelled)
    fold_stability = {
        feature_id: (
            nonzero_count,
            fold_count,
            coefficient_min,
            coefficient_max,
        )
        for (
            feature_id,
            _name_zh,
            nonzero_count,
            fold_count,
            _magnitude,
            coefficient_min,
            coefficient_max,
        )
        in stable_across_folds
    }
    stable = tuple(
        StableBehaviorFeature(
            feature_id=normalization.feature_id,
            name_zh=normalization.name_zh,
            coefficient=float(coefficient),
            nonzero_fold_count=fold_stability[normalization.feature_id][0],
            fold_count=fold_stability[normalization.feature_id][1],
            fold_coefficient_min=fold_stability[
                normalization.feature_id
            ][2],
            fold_coefficient_max=fold_stability[
                normalization.feature_id
            ][3],
        )
        for normalization, coefficient in zip(
            normalizations,
            model.coef_[0],
            strict=True,
        )
        if not math.isclose(float(coefficient), 0.0, abs_tol=1e-12)
    )
    if not stable:
        return _failed_result(
            request,
            experiment_id=experiment_id,
            created_at=created_at,
            code="NO_STABLE_FEATURES",
            message_zh="扩展窗口中没有符号一致的稳定指标。",
        )
    test_probabilities = model.predict_proba(
        apply_normalizations(test, normalizations)
    )[:, 1]
    test_metrics = _model_metrics(
        test,
        test_probabilities,
        profile=profile,
        threshold=(
            None
            if threshold_selection is None
            else threshold_selection.threshold
        ),
    )
    applicability_scores = tuple(leave_episode_out_scores)
    if any(
        not isinstance(item, LeaveEpisodeOutSimilarity)
        for item in applicability_scores
    ):
        raise ValueError(
            "leave-episode-out scores must use the audited domain type"
        )
    if len(
        {item.decision_event_id for item in applicability_scores}
    ) != len(applicability_scores):
        raise ValueError("leave-episode-out sample identities must be unique")
    applicability_threshold = (
        float(
            np.quantile(
                [item.similarity for item in applicability_scores],
                0.10,
                method="linear",
            )
        )
        if len({item.episode_id for item in applicability_scores}) >= 10
        else None
    )
    test_label_counts = dict(test_metrics.label_counts)
    test_episode_counts = dict(test_metrics.episode_counts)
    maturity = (
        EntryBehaviorModelMaturity.FORMAL
        if min(test_label_counts.values()) >= 10
        and min(test_episode_counts.values()) >= 5
        and applicability_threshold is not None
        else EntryBehaviorModelMaturity.EXPLORATORY
    )
    manifest = EntryBehaviorModelManifest(
        formula_version=ENTRY_BEHAVIOR_FORMULA_VERSION,
        feature_version=profile.feature_version,
        app_version=str(app_version),
        seed=request.seed,
        label_counts=label_counts,
        sample_ids=tuple(sample.decision_event_id for sample in ordered),
        episode_ids=tuple(dict.fromkeys(sample.episode_id for sample in ordered)),
        data_start_utc_ms=ordered[0].decision_cutoff_utc_ms,
        data_end_utc_ms=ordered[-1].decision_cutoff_utc_ms,
        feature_limit=feature_limit,
        selected_c=selected_c,
        l1_ratio=ENTRY_BEHAVIOR_L1_RATIO,
        normalizations=tuple(normalizations),
        temporal_folds=temporal_folds,
        regularization_path=regularization_path,
        threshold_candidates=threshold_candidates,
        threshold_selection=threshold_selection,
        validation_metrics=validation_metrics,
        test_episode_ids=tuple(
            dict.fromkeys(sample.episode_id for sample in test)
        ),
        test_sample_ids=tuple(
            sample.decision_event_id for sample in test
        ),
        test_metrics=test_metrics,
        leave_episode_out_scores=applicability_scores,
        dependency_versions=MappingProxyType(_dependency_versions()),
        label_fingerprint=_label_fingerprint(ordered),
        target=profile.target,
        positive_label=profile.positive_label,
        negative_label=profile.negative_label,
        episode_kind=profile.episode_kind,
    )
    version = EntryBehaviorModelVersion(
        model_version_id=model_version_id,
        experiment_id=experiment_id,
        setup_version_id=request.setup_version_id,
        grouping_version_id=request.grouping_version_id,
        direction=request.direction,
        maturity=maturity,
        intercept=float(model.intercept_[0]),
        stable_features=stable,
        research_threshold=(
            None
            if threshold_selection is None
            else threshold_selection.threshold
        ),
        applicability_threshold=applicability_threshold,
        created_at=created_at,
        manifest=manifest,
        target=profile.target,
    )
    return EntryBehaviorTrainingResult(
        experiment_id=experiment_id,
        setup_version_id=request.setup_version_id,
        grouping_version_id=request.grouping_version_id,
        direction=request.direction,
        status=EntryBehaviorExperimentStatus.COMPLETED,
        created_at=created_at,
        failure=None,
        model=version,
        target=profile.target,
    )


def fit_entry_behavior_model(
    samples: Sequence[EntryBehaviorSample],
    *,
    request: EntryBehaviorTrainingRequest,
    app_version: str,
    experiment_id: str,
    model_version_id: str,
    created_at: str,
    cancelled: Callable[[], bool] | None = None,
    leave_episode_out_scores: Sequence[LeaveEpisodeOutSimilarity] = (),
) -> EntryBehaviorTrainingResult:
    if request.target is not BehaviorModelTarget.ENTRY_SELECTION:
        raise ValueError("entry behavior adapter only accepts the entry target")
    return fit_behavior_model(
        samples,
        request=request,
        app_version=app_version,
        experiment_id=experiment_id,
        model_version_id=model_version_id,
        created_at=created_at,
        cancelled=cancelled,
        leave_episode_out_scores=leave_episode_out_scores,
    )


def failed_entry_behavior_training_result(
    request: EntryBehaviorTrainingRequest,
    *,
    experiment_id: str,
    created_at: str,
    code: str,
    message_zh: str,
) -> EntryBehaviorTrainingResult:
    return _failed_result(
        request,
        experiment_id=experiment_id,
        created_at=created_at,
        code=str(code),
        message_zh=str(message_zh),
    )


def _failed_result(
    request: EntryBehaviorTrainingRequest,
    *,
    experiment_id: str,
    created_at: str,
    code: str,
    message_zh: str,
) -> EntryBehaviorTrainingResult:
    return EntryBehaviorTrainingResult(
        experiment_id=experiment_id,
        setup_version_id=request.setup_version_id,
        grouping_version_id=request.grouping_version_id,
        direction=request.direction,
        status=EntryBehaviorExperimentStatus.FAILED,
        created_at=created_at,
        failure=EntryBehaviorFailure(code=code, message_zh=message_zh),
        model=None,
        target=request.target,
    )


def _numerical_failure(
    request: EntryBehaviorTrainingRequest,
    experiment_id: str,
    created_at: str,
) -> EntryBehaviorTrainingResult:
    return _failed_result(
        request,
        experiment_id=experiment_id,
        created_at=created_at,
        code="NUMERICAL_FAILURE",
        message_zh="求解器未稳定收敛，本次实验未发布模型。",
    )


def _fit_temporal_fold(
    fold_index: int,
    train: tuple[EntryBehaviorSample, ...],
    validation: tuple[EntryBehaviorSample, ...],
    feature_limit: int,
    *,
    profile: BehaviorModelProfile,
    seed: int,
    cancelled: Callable[[], bool] | None,
) -> TemporalFoldAudit:
    fold_label_counts = count_labels(train, profile=profile)
    if min(count for _label, count in fold_label_counts) < 1:
        raise ValueError("each training fold requires both labels")
    validation_counts = count_labels(validation, profile=profile)
    if min(count for _label, count in validation_counts) < 1:
        raise ValueError("each validation fold requires both labels")
    fold_feature_limit = min(
        int(feature_limit),
        min(count for _label, count in fold_label_counts) // 5,
    )
    if fold_feature_limit < 1:
        raise ValueError("training fold is too small for one behavior feature")
    normalizations, train_design, train_labels = normalized_design(
        train,
        max_features=fold_feature_limit,
        profile=profile,
    )
    validation_design = apply_normalizations(validation, normalizations)
    validation_labels = encode_labels(validation, profile=profile)
    weights = class_weights(train_labels)
    evaluations = []
    for c_value in ENTRY_BEHAVIOR_C_GRID:
        _raise_if_cancelled(cancelled)
        if not normalizations:
            probabilities = np.full(len(validation), 0.5, dtype=float)
            evaluations.append(
                FoldRegularizationEvaluation(
                    c_value=c_value,
                    balanced_log_loss=_balanced_log_loss(
                        validation_labels,
                        probabilities,
                    ),
                    nonzero_count=0,
                    coefficients=(),
                    validation_probabilities=tuple(
                        float(value) for value in probabilities
                    ),
                )
            )
            continue
        model = _fit_logistic_model(
            train_design,
            train_labels,
            c_value=c_value,
            class_weight=weights,
            seed=seed,
        )
        probabilities = model.predict_proba(validation_design)[:, 1]
        coefficients = tuple(
            (normalization.feature_id, float(coefficient))
            for normalization, coefficient in zip(
                normalizations,
                model.coef_[0],
                strict=True,
            )
        )
        evaluations.append(
            FoldRegularizationEvaluation(
                c_value=c_value,
                balanced_log_loss=_balanced_log_loss(
                    validation_labels,
                    probabilities,
                ),
                nonzero_count=sum(
                    not math.isclose(coefficient, 0.0, abs_tol=1e-12)
                    for _feature_id, coefficient in coefficients
                ),
                coefficients=coefficients,
                validation_probabilities=tuple(
                    float(value) for value in probabilities
                ),
            )
        )
    return TemporalFoldAudit(
        fold_index=fold_index,
        train_episode_ids=tuple(
            dict.fromkeys(sample.episode_id for sample in train)
        ),
        validation_episode_ids=tuple(
            dict.fromkeys(sample.episode_id for sample in validation)
        ),
        train_sample_ids=tuple(
            sample.decision_event_id for sample in train
        ),
        validation_sample_ids=tuple(
            sample.decision_event_id for sample in validation
        ),
        train_end_utc_ms=max(
            sample.decision_cutoff_utc_ms for sample in train
        ),
        validation_start_utc_ms=min(
            sample.decision_cutoff_utc_ms for sample in validation
        ),
        validation_end_utc_ms=max(
            sample.decision_cutoff_utc_ms for sample in validation
        ),
        normalizations=normalizations,
        validation_labels=tuple(
            int(value) for value in validation_labels
        ),
        label_counts=fold_label_counts,
        class_weights=(
            (profile.positive_label, weights[1]),
            (profile.negative_label, weights[0]),
        ),
        regularization_evaluations=tuple(evaluations),
    )


def _fit_logistic_model(
    design: np.ndarray,
    labels: np.ndarray,
    *,
    c_value: float,
    class_weight: Mapping[int, float],
    seed: int,
) -> LogisticRegression:
    model = LogisticRegression(
        C=float(c_value),
        solver="saga",
        l1_ratio=ENTRY_BEHAVIOR_L1_RATIO,
        class_weight=dict(class_weight),
        random_state=int(seed),
        max_iter=10_000,
        tol=1e-8,
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            model.fit(design, labels)
    except ConvergenceWarning as exc:
        raise EntryBehaviorNumericalError(
            "elastic-net logistic regression did not converge"
        ) from exc
    if not np.isfinite(model.coef_).all() or not np.isfinite(
        model.intercept_
    ).all():
        raise EntryBehaviorNumericalError(
            "elastic-net logistic regression returned non-finite coefficients"
        )
    return model


def _balanced_log_loss(
    labels: np.ndarray,
    probabilities: np.ndarray,
) -> float:
    clipped = np.clip(np.asarray(probabilities, dtype=float), 1e-15, 1 - 1e-15)
    positive = labels == 1
    negative = labels == 0
    if not positive.any() or not negative.any():
        raise ValueError("balanced log loss requires both validation labels")
    positive_loss = -float(np.mean(np.log(clipped[positive])))
    negative_loss = -float(np.mean(np.log1p(-clipped[negative])))
    return 0.5 * (positive_loss + negative_loss)


def _model_metrics(
    samples: Sequence[EntryBehaviorSample],
    probabilities: np.ndarray,
    *,
    profile: BehaviorModelProfile,
    threshold: float | None,
) -> BehaviorModelMetrics:
    encoded_labels = encode_labels(samples, profile=profile)
    probabilities = np.asarray(probabilities, dtype=float)
    if probabilities.shape != encoded_labels.shape or not np.isfinite(
        probabilities
    ).all():
        raise ValueError("entry behavior probabilities are invalid")
    episode_counts = tuple(
        (
            label,
            len(
                {
                    sample.episode_id
                    for sample in samples
                    if sample.label == label
                }
            ),
        )
        for label in (profile.positive_label, profile.negative_label)
    )
    recall: float | None = None
    precision: float | None = None
    if threshold is not None:
        predicted = probabilities >= threshold
        positives = encoded_labels == 1
        true_positive = int(np.sum(predicted & positives))
        recall = true_positive / int(np.sum(positives))
        predicted_count = int(np.sum(predicted))
        precision = (
            true_positive / predicted_count if predicted_count else 0.0
        )
    return BehaviorModelMetrics(
        sample_count=len(samples),
        label_counts=count_labels(samples, profile=profile),
        episode_counts=episode_counts,
        balanced_log_loss=_balanced_log_loss(encoded_labels, probabilities),
        brier_score=float(np.mean((probabilities - encoded_labels) ** 2)),
        recall=recall,
        precision=precision,
    )


def _summarize_regularization_path(
    folds: Sequence[TemporalFoldAudit],
) -> tuple[RegularizationPathSummary, ...]:
    summaries = []
    for c_value in ENTRY_BEHAVIOR_C_GRID:
        evaluations = tuple(
            next(
                item
                for item in fold.regularization_evaluations
                if item.c_value == c_value
            )
            for fold in folds
        )
        losses = np.asarray(
            [item.balanced_log_loss for item in evaluations],
            dtype=float,
        )
        summaries.append(
            RegularizationPathSummary(
                c_value=c_value,
                mean_balanced_log_loss=float(np.mean(losses)),
                standard_error=(
                    float(np.std(losses, ddof=1) / math.sqrt(len(losses)))
                    if len(losses) > 1
                    else 0.0
                ),
                maximum_nonzero_count=max(
                    item.nonzero_count for item in evaluations
                ),
            )
        )
    return tuple(summaries)


def _select_one_standard_error_c(
    path: Sequence[RegularizationPathSummary],
    *,
    feature_limit: int,
) -> float:
    best = min(
        path,
        key=lambda item: (item.mean_balanced_log_loss, item.c_value),
    )
    candidates = tuple(
        item
        for item in path
        if item.mean_balanced_log_loss
        <= best.mean_balanced_log_loss + best.standard_error
        and item.maximum_nonzero_count <= feature_limit
    )
    if not candidates:
        raise ValueError("no regularization candidate satisfies the feature limit")
    return min(
        candidates,
        key=lambda item: (
            item.c_value,
            item.maximum_nonzero_count,
        ),
    ).c_value


def _stable_features_across_folds(
    folds: Sequence[TemporalFoldAudit],
    *,
    selected_c: float,
    feature_limit: int,
    profile: BehaviorModelProfile = ENTRY_BEHAVIOR_PROFILE,
) -> tuple[tuple[str, str, int, int, float, float, float], ...]:
    coefficients: dict[str, list[float]] = {}
    for fold in folds:
        evaluation = next(
            item
            for item in fold.regularization_evaluations
            if item.c_value == selected_c
        )
        for feature_id, coefficient in evaluation.coefficients:
            if not math.isclose(coefficient, 0.0, abs_tol=1e-12):
                coefficients.setdefault(feature_id, []).append(coefficient)
    names = {
        definition.feature_id: definition.name_zh
        for definition in profile.feature_definitions
    }
    required = math.ceil(len(folds) * 2 / 3)
    stable = []
    for feature_id, values in coefficients.items():
        signs = {1 if value > 0 else -1 for value in values}
        if len(values) < required or len(signs) != 1:
            continue
        stable.append(
            (
                feature_id,
                names[feature_id],
                len(values),
                len(folds),
                float(np.median(np.abs(np.asarray(values, dtype=float)))),
                float(min(values)),
                float(max(values)),
            )
        )
    return tuple(
        sorted(
            stable,
            key=lambda item: (-item[2], -item[4], item[0]),
        )[:feature_limit]
    )


def _research_threshold_candidates(
    folds: Sequence[TemporalFoldAudit],
    *,
    selected_c: float,
) -> tuple[ResearchThresholdCandidate, ...]:
    selected_evaluations = tuple(
        next(
            item
            for item in fold.regularization_evaluations
            if item.c_value == selected_c
        )
        for fold in folds
    )
    thresholds = sorted(
        {
            probability
            for evaluation in selected_evaluations
            for probability in evaluation.validation_probabilities
        }
    )
    candidates = []
    for threshold in thresholds:
        recalls = []
        precisions = []
        for fold, evaluation in zip(
            folds,
            selected_evaluations,
            strict=True,
        ):
            labels = np.asarray(fold.validation_labels, dtype=int)
            probabilities = np.asarray(
                evaluation.validation_probabilities,
                dtype=float,
            )
            predicted = probabilities >= threshold
            positives = labels == 1
            true_positive = int(np.sum(predicted & positives))
            recalls.append(true_positive / int(np.sum(positives)))
            predicted_count = int(np.sum(predicted))
            precisions.append(
                true_positive / predicted_count if predicted_count else 0.0
            )
        candidates.append(
            ResearchThresholdCandidate(
                threshold=float(threshold),
                mean_recall=float(np.mean(recalls)),
                minimum_fold_recall=float(min(recalls)),
                mean_precision=float(np.mean(precisions)),
            )
        )
    return tuple(candidates)


def _select_research_threshold(
    candidates: Sequence[ResearchThresholdCandidate],
) -> ResearchThresholdCandidate | None:
    eligible = tuple(
        item
        for item in candidates
        if item.mean_recall >= 0.80
        and item.minimum_fold_recall >= 0.70
    )
    if not eligible:
        return None
    best_precision = max(item.mean_precision for item in eligible)
    precision_ties = tuple(
        item
        for item in eligible
        if math.isclose(
            item.mean_precision,
            best_precision,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    )
    return max(precision_ties, key=lambda item: item.threshold)


def _dependency_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scikit-learn": sklearn.__version__,
        "joblib": joblib.__version__,
        "threadpoolctl": threadpoolctl.__version__,
    }


def _label_fingerprint(samples: Sequence[EntryBehaviorSample]) -> str:
    return entry_behavior_label_fingerprint(
        tuple(
            (
                sample.decision_event_id,
                sample.episode_id,
                sample.decision_cutoff_utc_ms,
                sample.label,
            )
            for sample in samples
        )
    )


def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise InterruptedError("behavior-model training cancelled")


__all__ = [
    "EntryBehaviorNumericalError",
    "failed_behavior_training_result",
    "failed_entry_behavior_training_result",
    "fit_behavior_model",
    "fit_entry_behavior_model",
]


# The persisted entry name remains available for v1.6 compatibility.  New
# entry and exit callers share this target-aware result constructor.
failed_behavior_training_result = failed_entry_behavior_training_result
