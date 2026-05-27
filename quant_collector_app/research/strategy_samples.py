from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Iterable


VALID_SAMPLE_ROLES = frozenset({"USER_ACTION", "NO_ACTION", "CANDIDATE", "CONTROL", "TRAIN", "TEST"})


def validate_sample_role(sample_role: str) -> str:
    value = str(sample_role or "").upper()
    if value not in VALID_SAMPLE_ROLES:
        raise ValueError(f"Unsupported sample_role: {sample_role}")
    return value


def build_strategy_sample_id(experiment_id: str, sample_id: str, sample_role: str) -> str:
    role = validate_sample_role(sample_role)
    payload = "|".join([str(experiment_id), str(sample_id), role])
    return "strat_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def create_strategy_sample(
    *,
    sample_id: str,
    experiment_id: str,
    feature_version: str,
    label_version: str,
    dataset_hash: str,
    sample_role: str,
    profile_id: str | None = None,
    profile_version: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    role = validate_sample_role(sample_role)
    return {
        "strategy_sample_id": build_strategy_sample_id(experiment_id, sample_id, role),
        "sample_id": str(sample_id),
        "experiment_id": str(experiment_id),
        "profile_id": profile_id,
        "profile_version": profile_version,
        "feature_version": str(feature_version),
        "label_version": str(label_version),
        "dataset_hash": str(dataset_hash),
        "sample_role": role,
        "created_at": created_at or datetime.now(UTC).isoformat(timespec="seconds"),
    }


def attach_samples_to_experiment(
    observations: Iterable[dict[str, Any]],
    *,
    experiment_id: str,
    feature_version: str,
    label_version: str,
    dataset_hash: str,
    sample_role: str,
    profile_id: str | None = None,
    profile_version: str | None = None,
    created_at: str | None = None,
) -> list[dict[str, Any]]:
    return [
        create_strategy_sample(
            sample_id=observation["sample_id"],
            experiment_id=experiment_id,
            profile_id=profile_id,
            profile_version=profile_version,
            feature_version=feature_version,
            label_version=label_version,
            dataset_hash=dataset_hash,
            sample_role=sample_role,
            created_at=created_at,
        )
        for observation in observations
    ]


__all__ = [
    "VALID_SAMPLE_ROLES",
    "attach_samples_to_experiment",
    "build_strategy_sample_id",
    "create_strategy_sample",
    "validate_sample_role",
]
