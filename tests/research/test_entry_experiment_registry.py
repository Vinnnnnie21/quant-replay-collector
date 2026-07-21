from __future__ import annotations

import pytest

from quant_collector_app.research.entry_experiment_registry import (
    compare_experiments,
    create_experiment_id,
    load_experiment_manifest,
    load_latest_experiment,
    save_experiment_bundle,
    save_experiment_manifest,
    validate_experiment_manifest,
)


def _config() -> dict:
    return {
        "app_version": "1.4.1",
        "symbol": "BTCUSDT",
        "interval": "5m",
        "data_start": "2026-01-01T00:00:00Z",
        "data_end": "2026-01-31T23:55:00Z",
        "annotation_version": "entry_annotations_v1",
        "feature_version": "entry_context_v1",
        "feature_cols": ["lower_shadow_ratio", "volume_zscore_20", "range_pct"],
        "split_method": "walk_forward",
        "embargo_bars": 2,
        "model_type": "entry_prototype_pu",
        "model_params": {"top_k": 20, "score": "human_entry_similarity"},
    }


def test_same_config_generates_stable_experiment_id():
    first = create_experiment_id(_config())
    second = create_experiment_id(dict(reversed(list(_config().items()))))

    assert first == second
    assert first.startswith("entry_exp_")


def test_manifest_can_be_saved_and_loaded(tmp_path):
    path = tmp_path / "entry_experiment_manifest.json"
    metrics = {"precision_at_10": 0.6, "unlabeled_scored": 42}
    artifacts = {
        "score_table": "research/entry_logic_scores.csv",
        "report": "research/entry_logic_report.md",
    }

    manifest = save_experiment_manifest(path, _config(), metrics, artifacts)
    loaded = load_experiment_manifest(path)

    assert loaded == manifest
    assert loaded["experiment_id"] == create_experiment_id(_config())
    assert loaded["metrics"] == metrics
    assert loaded["artifact_paths"] == artifacts
    assert loaded["warnings"] == []


def test_manifest_validation_reports_missing_fields_clearly(tmp_path):
    manifest = save_experiment_manifest(
        tmp_path / "manifest.json",
        {**_config(), "created_at": "2026-01-01T00:00:00Z"},
        {},
        {},
    )
    manifest.pop("feature_cols")

    with pytest.raises(ValueError, match="Missing experiment manifest fields: feature_cols"):
        validate_experiment_manifest(manifest)


def test_warnings_are_preserved_for_reproducibility_notes(tmp_path):
    config = {
        **_config(),
        "warnings": ["low_sample", "possible_time_leakage_reviewed", "insufficient_labels"],
    }

    manifest = save_experiment_manifest(tmp_path / "manifest.json", config, {}, {})

    assert manifest["warnings"] == ["low_sample", "possible_time_leakage_reviewed", "insufficient_labels"]


def test_artifact_paths_must_be_relative(tmp_path):
    with pytest.raises(ValueError, match="artifact_paths must be relative"):
        save_experiment_manifest(
            tmp_path / "manifest.json",
            _config(),
            {},
            {"report": "D:/Trading/private/report.md"},
        )


def test_sensitive_keys_are_rejected(tmp_path):
    config = {**_config(), "api_key": "secret"}

    with pytest.raises(ValueError, match="Sensitive field is not allowed"):
        save_experiment_manifest(tmp_path / "manifest.json", config, {}, {})

def _long_term_config(**overrides) -> dict:
    config = {
        **_config(),
        "data_hash": "data_hash_v1",
        "label_version": "labels_v1",
        "split_config": {"method": "chronological", "train_ratio": 0.6, "val_ratio": 0.2, "test_ratio": 0.2},
        "model_config": {"model_type": "prototype_similarity", "top_k": 20},
        "threshold": 0.72,
        "annotation_counts": {"ENTRY": 10, "REJECT": 30, "UNCERTAIN": 2, "UNLABELED": 100},
    }
    config.update(overrides)
    return config


def test_experiment_bundle_creates_dated_directory_and_artifacts(tmp_path):
    result = save_experiment_bundle(
        tmp_path,
        _long_term_config(),
        metrics={"test_precision_at_k": 0.6},
        report_markdown="# Entry Logic Report\n",
        review_queue=[{"observation_id": "obs_1", "human_entry_similarity": 0.88}],
        feature_quality={"row_count": 10, "forbidden_fields_detected": []},
        split_summary={"train_count": 6, "val_count": 2, "test_count": 2},
        warnings=["low_sample"],
        note="本轮新增 120 个 REJECT",
        created_at="2026-06-20T10:11:12Z",
    )

    experiment_dir = result["experiment_dir"]
    assert experiment_dir.parent == tmp_path / "experiments"
    assert experiment_dir.name.startswith("2026-06-20_entry_exp_")
    for filename in (
        "manifest.json",
        "metrics.json",
        "report.md",
        "review_queue.csv",
        "feature_quality.json",
        "split_summary.json",
        "warnings.json",
    ):
        assert (experiment_dir / filename).exists()
    manifest = load_experiment_manifest(experiment_dir / "manifest.json")
    assert manifest["experiment_note"] == "本轮新增 120 个 REJECT"
    assert manifest["artifact_paths"]["report"] == "report.md"
    assert all(not value.startswith("D:/") for value in manifest["artifact_paths"].values())


def test_compare_experiments_detects_feature_and_annotation_changes(tmp_path):
    first = save_experiment_bundle(
        tmp_path,
        _long_term_config(feature_version="entry_context_v1"),
        metrics={"test_precision_at_k": 0.5},
        created_at="2026-06-19T10:00:00Z",
    )
    second = save_experiment_bundle(
        tmp_path,
        _long_term_config(
            feature_version="entry_context_v2",
            annotation_counts={"ENTRY": 10, "REJECT": 35, "UNCERTAIN": 2, "UNLABELED": 95},
        ),
        metrics={"test_precision_at_k": 0.7},
        created_at="2026-06-20T10:00:00Z",
    )

    comparison = compare_experiments(first["experiment_dir"], second["experiment_dir"])

    assert comparison["same_data"] is True
    assert comparison["feature_version_changed"] is True
    assert comparison["annotation_count_delta"]["REJECT"] == 5
    assert comparison["metrics_delta"]["test_precision_at_k"] == pytest.approx(0.2)
    assert comparison["split_changed"] is False


def test_load_latest_experiment_returns_newest_manifest(tmp_path):
    save_experiment_bundle(
        tmp_path,
        _long_term_config(experiment_id="entry_exp_old"),
        created_at="2026-06-19T09:00:00Z",
    )
    newest = save_experiment_bundle(
        tmp_path,
        _long_term_config(experiment_id="entry_exp_new"),
        created_at="2026-06-20T09:00:00Z",
    )

    loaded = load_latest_experiment(tmp_path)

    assert loaded["experiment_id"] == newest["manifest"]["experiment_id"]


def test_missing_artifacts_are_reported_as_warning(tmp_path):
    result = save_experiment_bundle(
        tmp_path,
        _long_term_config(),
        report_markdown="# Entry Logic Report\n",
        created_at="2026-06-20T10:11:12Z",
    )
    (result["experiment_dir"] / "report.md").unlink()

    loaded = load_experiment_manifest(result["experiment_dir"] / "manifest.json", check_artifacts=True)

    assert any("missing_artifact:report" in warning for warning in loaded["warnings"])


def test_manifest_records_real_split_feature_timing_and_frozen_metrics(tmp_path):
    metrics = {
        "threshold_selection": {
            "selected_threshold": 0.73,
            "validation_precision_at_k": 0.8,
            "validation_recall_on_entry": 0.6,
        },
        "split_summary": {
            "split_method": "purged_chronological",
            "train_count": 12,
            "validation_count": 4,
            "test_count": 4,
            "purged_count": 2,
            "embargoed_count": 1,
            "episode_leakage_count": 0,
            "horizon_bars": 10,
            "embargo_bars": 2,
        },
        "unlabeled_scored_count": 30,
        "test_precision_at_k": 0.5,
        "test_recall_on_entry": 0.4,
        "test_reject_rate_in_top_k": 0.2,
    }
    config = {
        **_config(),
        "data_hash": "hash_abc",
        "label_version": "entry_outcome_labels_v1",
        "feature_timing_policy": "setup_bar_only",
        "allow_confirmation_bar": False,
        "split_method": "purged_chronological",
        "split_summary": metrics["split_summary"],
        "model_type": "prototype_similarity",
        "model_config": {"threshold_metric": "precision_at_k"},
        "review_queue_config": {"name": "high_similarity", "top_k": 10},
    }

    manifest = save_experiment_manifest(tmp_path / "manifest.json", config, metrics, {"report": "report.md"})

    assert manifest["split_method"] == "purged_chronological"
    assert manifest["feature_timing_policy"] == "setup_bar_only"
    assert manifest["allow_confirmation_bar"] is False
    assert manifest["train_count"] == 12
    assert manifest["validation_count"] == 4
    assert manifest["test_count"] == 4
    assert manifest["unlabeled_scored_count"] == 30
    assert manifest["purged_count"] == 2
    assert manifest["embargoed_count"] == 1
    assert manifest["episode_leakage_count"] == 0
    assert manifest["threshold_tuning_metric"] == "precision_at_k"
    assert manifest["selected_threshold"] == 0.73
    assert manifest["validation_metrics"]["validation_precision_at_k"] == 0.8
    assert manifest["frozen_test_metrics"]["test_precision_at_k"] == 0.5
    assert manifest["review_queue_config"]["name"] == "high_similarity"