from __future__ import annotations

import pandas as pd
import pytest

from research.experiment_tracker import create_manifest
from research.strategy_samples import (
    attach_samples_to_experiment,
    create_strategy_sample,
    validate_sample_role,
)
from storage import StorageManager


def test_strategy_samples_bind_reproducibility_metadata_and_persist(tmp_path):
    storage = StorageManager(tmp_path / "samples.db")
    row = create_strategy_sample(
        sample_id="obs_1",
        experiment_id="exp_1",
        profile_id="profile_1",
        profile_version="1.0",
        feature_version="research_features_v1.0",
        label_version="research_labels_v1.0",
        dataset_hash="a" * 64,
        sample_role="USER_ACTION",
        created_at="2026-05-27T08:00:00+00:00",
    )

    storage.save_strategy_sample(row)
    stored = storage.list_strategy_samples_for_experiment("exp_1")

    assert len(stored) == 1
    assert stored[0]["profile_id"] == "profile_1"
    assert stored[0]["profile_version"] == "1.0"
    assert stored[0]["feature_version"] == "research_features_v1.0"
    assert stored[0]["label_version"] == "research_labels_v1.0"
    assert stored[0]["dataset_hash"] == "a" * 64


def test_attach_samples_to_experiment_creates_rows_for_observations():
    rows = attach_samples_to_experiment(
        [{"sample_id": "obs_1"}, {"sample_id": "obs_2"}],
        experiment_id="exp_1",
        profile_id=None,
        profile_version=None,
        feature_version="f1",
        label_version="l1",
        dataset_hash="b" * 64,
        sample_role="NO_ACTION",
        created_at="2026-05-27T08:00:00+00:00",
    )

    assert [row["sample_id"] for row in rows] == ["obs_1", "obs_2"]
    assert all(row["sample_role"] == "NO_ACTION" for row in rows)


def test_invalid_strategy_sample_role_is_rejected():
    with pytest.raises(ValueError):
        validate_sample_role("LIVE_ORDER")


def test_manifest_accepts_declared_profile_and_validation_specs():
    manifest = create_manifest(
        pd.DataFrame({"event_id": ["e1"]}),
        "fwd_ret_10_side_adj",
        [],
        profile_id="profile_1",
        profile_version="1.0",
        baseline_spec={"method": "unassigned_v1_4"},
        split_spec={"method": "chronological"},
    )

    assert manifest["profile_id"] == "profile_1"
    assert manifest["profile_version"] == "1.0"
    assert "unassigned_v1_4" in manifest["baseline_spec_json"]
    assert "chronological" in manifest["split_spec_json"]
