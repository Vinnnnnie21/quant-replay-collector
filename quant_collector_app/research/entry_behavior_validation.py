from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .entry_behavior_model import (
    ENTRY_BEHAVIOR_PROFILE,
    BehaviorModelProfile,
    EntryBehaviorSample,
    FeatureNormalization,
)


def episode_temporal_partition(
    samples: Sequence[EntryBehaviorSample],
    *,
    profile: BehaviorModelProfile = ENTRY_BEHAVIOR_PROFILE,
) -> tuple[
    tuple[EntryBehaviorSample, ...],
    tuple[EntryBehaviorSample, ...],
    tuple[
        tuple[
            tuple[EntryBehaviorSample, ...],
            tuple[EntryBehaviorSample, ...],
        ],
        ...,
    ],
]:
    by_episode: dict[str, list[EntryBehaviorSample]] = {}
    for sample in samples:
        by_episode.setdefault(sample.episode_id, []).append(sample)
    episode_ids = tuple(
        sorted(
            by_episode,
            key=lambda episode_id: (
                min(
                    item.decision_cutoff_utc_ms
                    for item in by_episode[episode_id]
                ),
                episode_id,
            ),
        )
    )
    if len(episode_ids) < 5:
        raise ValueError(
            "behavior validation requires at least five episodes"
        )
    test_count = max(1, math.ceil(len(episode_ids) * 0.20))
    development_episode_ids = episode_ids[:-test_count]
    test_episode_ids = set(episode_ids[-test_count:])
    validation_size = len(development_episode_ids) // 4
    if validation_size < 1:
        raise ValueError(
            "behavior validation requires three expanding folds"
        )
    initial_train_size = (
        len(development_episode_ids) - 3 * validation_size
    )
    if initial_train_size < 1:
        raise ValueError(
            "behavior validation requires a non-empty initial train set"
        )
    development = tuple(
        sample
        for sample in samples
        if sample.episode_id not in test_episode_ids
    )
    test = tuple(
        sample
        for sample in samples
        if sample.episode_id in test_episode_ids
    )
    if not development or not test:
        raise ValueError("behavior final test partition is empty")
    if max(
        sample.decision_cutoff_utc_ms for sample in development
    ) >= min(sample.decision_cutoff_utc_ms for sample in test):
        raise ValueError(
            "market episodes interleave across development and final test"
        )
    folds = []
    for fold_index in range(3):
        train_end = initial_train_size + fold_index * validation_size
        validation_end = train_end + validation_size
        train_ids = set(development_episode_ids[:train_end])
        validation_ids = set(
            development_episode_ids[train_end:validation_end]
        )
        train = tuple(
            sample for sample in development if sample.episode_id in train_ids
        )
        validation = tuple(
            sample
            for sample in development
            if sample.episode_id in validation_ids
        )
        if not train or not validation:
            raise ValueError("behavior temporal fold is empty")
        if max(item.decision_cutoff_utc_ms for item in train) >= min(
            item.decision_cutoff_utc_ms for item in validation
        ):
            raise ValueError("market episodes interleave across temporal folds")
        folds.append((train, validation))
    return development, test, tuple(folds)


def normalized_design(
    samples: Sequence[EntryBehaviorSample],
    *,
    max_features: int,
    feature_ids: Sequence[str] | None = None,
    profile: BehaviorModelProfile = ENTRY_BEHAVIOR_PROFILE,
) -> tuple[
    tuple[FeatureNormalization, ...],
    np.ndarray,
    np.ndarray,
]:
    expected_ids = tuple(
        definition.feature_id for definition in profile.feature_definitions
    )
    for sample in samples:
        if tuple(feature.feature_id for feature in sample.features) != expected_ids:
            raise ValueError(
                "behavior sample feature identities are inconsistent"
            )
        if sample.label not in {
            profile.positive_label,
            profile.negative_label,
        }:
            raise ValueError(
                "behavior sample label must match the selected target"
            )
    matrix = np.asarray(
        [[feature.value for feature in sample.features] for sample in samples],
        dtype=float,
    )
    if matrix.ndim != 2 or matrix.shape[1] != len(
        profile.feature_definitions
    ):
        raise ValueError(
            "behavior samples have inconsistent feature vectors"
        )
    if not np.isfinite(matrix).all():
        raise ValueError("behavior samples contain non-finite features")
    labels = np.asarray(
        [
            1 if sample.label == profile.positive_label else 0
            for sample in samples
        ],
        dtype=int,
    )
    available: list[tuple[FeatureNormalization, np.ndarray, float]] = []
    for index, definition in enumerate(profile.feature_definitions):
        raw = matrix[:, index]
        center = float(np.median(raw))
        mad = float(np.median(np.abs(raw - center)))
        if math.isclose(mad, 0.0, abs_tol=1e-15):
            continue
        scale = 1.4826 * mad
        normalization = FeatureNormalization(
            feature_id=definition.feature_id,
            name_zh=definition.name_zh,
            median=center,
            mad=mad,
            scale=scale,
        )
        standardized = np.clip((raw - center) / scale, -5.0, 5.0)
        selection_score = (
            abs(
                float(np.mean(standardized[labels == 1]))
                - float(np.mean(standardized[labels == 0]))
            )
            if set(labels.tolist()) == {0, 1}
            else 0.0
        )
        available.append((normalization, standardized, selection_score))
    if feature_ids is None:
        selected = sorted(
            available,
            key=lambda item: (
                -item[2],
                expected_ids.index(item[0].feature_id),
            ),
        )[: max(0, int(max_features))]
    else:
        by_id = {item[0].feature_id: item for item in available}
        selected = [
            by_id[feature_id]
            for feature_id in feature_ids
            if feature_id in by_id
        ][: max(0, int(max_features))]
    normalizations = tuple(item[0] for item in selected)
    columns = tuple(item[1] for item in selected)
    design = (
        np.column_stack(columns)
        if columns
        else np.empty((len(samples), 0), dtype=float)
    )
    return normalizations, design, labels


def apply_normalizations(
    samples: Sequence[EntryBehaviorSample],
    normalizations: Sequence[FeatureNormalization],
) -> np.ndarray:
    rows = []
    for sample in samples:
        values = {feature.feature_id: feature.value for feature in sample.features}
        row = []
        for normalization in normalizations:
            if normalization.feature_id not in values:
                raise ValueError("behavior validation feature is missing")
            value = float(values[normalization.feature_id])
            if not math.isfinite(value):
                raise ValueError("behavior validation feature is non-finite")
            row.append(
                float(
                    np.clip(
                        (value - normalization.median) / normalization.scale,
                        -5.0,
                        5.0,
                    )
                )
            )
        rows.append(row)
    return np.asarray(rows, dtype=float)


def labels(
    samples: Sequence[EntryBehaviorSample],
    *,
    profile: BehaviorModelProfile = ENTRY_BEHAVIOR_PROFILE,
) -> np.ndarray:
    return np.asarray(
        [
            1 if sample.label == profile.positive_label else 0
            for sample in samples
        ],
        dtype=int,
    )


def label_counts(
    samples: Sequence[EntryBehaviorSample],
    *,
    profile: BehaviorModelProfile = ENTRY_BEHAVIOR_PROFILE,
) -> tuple[tuple[str, int], ...]:
    return tuple(
        (label, sum(sample.label == label for sample in samples))
        for label in (profile.positive_label, profile.negative_label)
    )


def class_weights(labels: np.ndarray) -> dict[int, float]:
    positive = int(np.sum(labels == 1))
    negative = int(np.sum(labels == 0))
    if min(positive, negative) < 1:
        raise ValueError("class-balanced loss requires both labels")
    total = len(labels)
    return {
        0: total / (2 * negative),
        1: total / (2 * positive),
    }


__all__ = [
    "apply_normalizations",
    "class_weights",
    "episode_temporal_partition",
    "label_counts",
    "labels",
    "normalized_design",
]
