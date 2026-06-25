
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quant_collector_app.research.entry_experiment_registry import load_experiment_manifest
from quant_collector_app.research.entry_logic_experiment import run_entry_logic_experiment
from quant_collector_app.research.temporal_validation import SplitResult


FEATURE_COLS = ["lower_shadow_ratio", "volume_zscore_20", "range_pct"]


def _features() -> pd.DataFrame:
    shapes = [
        (0.82, 2.2, 0.040),
        (0.18, -1.2, 0.010),
        (0.88, 2.5, 0.045),
        (0.22, -0.8, 0.014),
        (0.78, 2.0, 0.038),
        (0.25, -0.6, 0.012),
        (0.86, 2.4, 0.043),
        (0.24, -0.7, 0.012),
        (0.84, 2.1, 0.041),
        (0.20, -0.9, 0.013),
        (0.90, 2.7, 0.046),
        (0.16, -1.0, 0.011),
        (0.50, 0.2, 0.020),
        (0.87, 2.3, 0.044),
        (0.83, 2.2, 0.042),
        (0.30, -0.4, 0.018),
    ]
    rows = []
    for index, (shadow, volume, range_pct) in enumerate(shapes):
        rows.append(
            {
                "observation_id": f"obs_{index:02d}",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": index,
                "decision_bar_index": index,
                "setup_bar_index": max(0, index - 1),
                "feature_cutoff_bar_index": index,
                "bar_time": (pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(minutes=index)).isoformat(),
                "feature_version": "test_features_v1",
                "data_version": "test_data_version",
                "candidate_source": "rule_seeded",
                "candidate_reason": "wide_reversal_candidate",
                "lower_shadow_ratio": shadow,
                "volume_zscore_20": volume,
                "range_pct": range_pct,
            }
        )
    frame = pd.DataFrame(rows)
    frame.attrs["data_hash"] = "test_data_hash"
    frame.attrs["data_version"] = "test_data_version"
    return frame


def _annotations(include_reject: bool = True) -> pd.DataFrame:
    decisions = {
        "obs_00": "ENTRY",
        "obs_01": "REJECT",
        "obs_02": "ENTRY",
        "obs_03": "REJECT",
        "obs_04": "ENTRY",
        "obs_05": "REJECT",
        "obs_06": "ENTRY",
        "obs_07": "REJECT",
        "obs_08": "ENTRY",
        "obs_09": "REJECT",
        "obs_10": "ENTRY",
        "obs_11": "REJECT",
        "obs_12": "UNCERTAIN",
        "obs_13": "UNLABELED",
    }
    rows = []
    for observation_id, decision in decisions.items():
        if decision == "REJECT" and not include_reject:
            continue
        rows.append(
            {
                "observation_id": observation_id,
                "human_decision": decision,
                "annotation_version": "test_annotations_v1",
                "is_active": True,
            }
        )
    return pd.DataFrame(rows)


def _split_config() -> dict[str, float | int | str]:
    return {
        "method": "purged_chronological",
        "train_ratio": 0.5,
        "validation_ratio": 0.25,
        "test_ratio": 0.25,
        "horizon_bars": 2,
        "embargo_bars": 1,
        "episode_gap_bars": 1,
    }


def test_runner_splits_only_entry_and_reject_labels(tmp_path):
    result = run_entry_logic_experiment(
        _features(),
        _annotations(),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path,
        split_config=_split_config(),
        top_k=3,
        metadata={"app_version": "test", "label_version": "test_labels_v1"},
    )

    split = result["split"]
    assert isinstance(split, SplitResult)
    split_ids = set(split.train["observation_id"]) | set(split.validation["observation_id"]) | set(split.test["observation_id"])
    labeled_ids = set(_annotations().loc[_annotations()["human_decision"].isin(["ENTRY", "REJECT"]), "observation_id"])
    assert split_ids <= labeled_ids
    assert "obs_12" not in split_ids
    assert "obs_13" not in split_ids
    assert set(result["labeled_dataset"]["human_decision"]) == {"ENTRY", "REJECT"}
    assert set(result["unlabeled_dataset"]["observation_id"]) == {"obs_13", "obs_14", "obs_15"}

    summary = result["split_summary"]
    assert summary["split_method"] == "purged_chronological"
    assert {"purged_count", "embargoed_count", "episode_leakage_count"} <= set(summary)
    assert summary["original_count"] == 12


def test_validation_selects_threshold_and_test_uses_frozen_threshold(tmp_path):
    result = run_entry_logic_experiment(
        _features(),
        _annotations(),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path,
        split_config=_split_config(),
        top_k=2,
    )

    threshold_selection = result["threshold_selection"]
    assert threshold_selection["selected_on"] == "validation"
    assert threshold_selection["test_used_for_threshold"] is False
    assert threshold_selection["selected_threshold"] == result["threshold"]
    assert "validation_precision_at_k" in threshold_selection
    assert "validation_reject_rate_above_threshold" in threshold_selection
    assert result["test_metrics"]["threshold"] == result["threshold"]
    assert result["test_metrics"]["test_entry_count"] >= 1
    assert result["test_metrics"]["test_reject_count"] >= 1
    assert "score_summary_by_decision" in result["test_metrics"]


def test_purged_chronological_summary_is_saved_to_manifest(tmp_path):
    result = run_entry_logic_experiment(
        _features(),
        _annotations(),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path,
        split_config=_split_config(),
        model_type="prototype_similarity",
    )

    manifest = load_experiment_manifest(result["manifest_path"])
    assert manifest["split_method"] == "purged_chronological"
    assert manifest["data_hash"] == "test_data_hash"
    assert manifest["feature_version"] == "test_features_v1"
    assert manifest["label_version"] is None or manifest["label_version"] == "test_labels_v1"
    assert manifest["threshold"] == result["threshold"]
    assert manifest["metrics"]["split_summary"]["purged_count"] == result["split_summary"]["purged_count"]
    assert manifest["metrics"]["threshold_selection"]["test_used_for_threshold"] is False
    experiment_dir = Path(result["experiment_dir"])
    assert experiment_dir.parent == tmp_path / "experiments"
    assert (tmp_path / "entry_logic_scores.csv").exists()
    assert (experiment_dir / "manifest.json").exists()
    assert (experiment_dir / "split_summary.json").exists()


def test_review_queue_only_uses_unlabeled_candidates(tmp_path):
    result = run_entry_logic_experiment(
        _features(),
        _annotations(),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path,
        split_config=_split_config(),
        top_k=10,
    )

    queue_ids = set(result["review_queue"]["observation_id"])
    assert queue_ids <= {"obs_13", "obs_14", "obs_15"}
    assert "obs_12" not in queue_ids
    assert queue_ids.isdisjoint(set(result["labeled_dataset"]["observation_id"]))
    assert set(result["scored_unlabeled"]["observation_id"]) == {"obs_13", "obs_14", "obs_15"}
    serialized = json.dumps(result["review_queue"].to_dict(orient="records"), ensure_ascii=False, default=str)
    assert "buy_signal" not in serialized
    assert "trade_signal" not in serialized


def test_runner_supports_pu_dataset_prototype_ranker_without_using_unlabeled_as_negative(tmp_path):
    result = run_entry_logic_experiment(
        _features(),
        _annotations(),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path,
        model_type="pu_dataset_prototype_ranker",
        split_config=_split_config(),
    )

    assert result["model_config"]["model_type"] == "pu_dataset_prototype_ranker"
    assert result["model_config"]["unlabeled_as_negative"] is False
    assert result["prototype"]["method"] == "entry_prototype_median_iqr"
    assert result["prototype"].get("pu_dataset_role_counts", {}).get("positive", 0) >= 1


def test_runner_raises_clear_error_without_entry(tmp_path):
    annotations = _annotations().copy()
    annotations.loc[annotations["human_decision"] == "ENTRY", "human_decision"] = "REJECT"

    with pytest.raises(ValueError, match="At least one ENTRY"):
        run_entry_logic_experiment(_features(), annotations, feature_cols=FEATURE_COLS, output_dir=tmp_path)


def test_runner_warns_without_reject_but_still_runs(tmp_path):
    result = run_entry_logic_experiment(
        _features(),
        _annotations(include_reject=False),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path,
        split_config={
            "method": "purged_chronological",
            "train_ratio": 0.5,
            "validation_ratio": 0.25,
            "test_ratio": 0.25,
            "horizon_bars": 1,
            "embargo_bars": 0,
        },
    )

    assert "no_reject_labels" in result["warnings"]
    assert result["test_metrics"]["test_reject_count"] == 0
    assert result["test_metrics"]["test_reject_rate_in_top_k"] is None


def test_runner_rejects_forbidden_outcome_feature_columns(tmp_path):
    features = _features().assign(fwd_ret_5=[0.01] * len(_features()))

    with pytest.raises(ValueError, match="not allowed"):
        run_entry_logic_experiment(
            features,
            _annotations(),
            feature_cols=[*FEATURE_COLS, "fwd_ret_5"],
            output_dir=tmp_path,
        )

    with pytest.raises(ValueError, match="not allowed"):
        run_entry_logic_experiment(
            _features().assign(MFE_10=[0.01] * len(_features())),
            _annotations(),
            feature_cols=[*FEATURE_COLS, "MFE_10"],
            output_dir=tmp_path,
        )


def test_duplicate_active_annotation_for_same_observation_is_rejected(tmp_path):
    annotations = pd.concat([_annotations(), _annotations().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="multiple active annotations"):
        run_entry_logic_experiment(
            _features(),
            annotations,
            feature_cols=FEATURE_COLS,
            output_dir=tmp_path,
        )


def test_unsupported_human_decision_is_rejected(tmp_path):
    annotations = _annotations().copy()
    annotations.loc[0, "human_decision"] = "BUY"

    with pytest.raises(ValueError, match="Unsupported human_decision"):
        run_entry_logic_experiment(
            _features(),
            annotations,
            feature_cols=FEATURE_COLS,
            output_dir=tmp_path,
        )


def test_chronological_split_mode_is_supported_but_warns_without_purge(tmp_path):
    result = run_entry_logic_experiment(
        _features(),
        _annotations(),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path,
        split_config={"method": "chronological", "train_ratio": 0.5, "validation_ratio": 0.25, "test_ratio": 0.25},
    )

    assert result["split_summary"]["split_method"] == "chronological"
    assert "chronological_split_without_purge" in result["warnings"]
    assert result["split_summary"]["purged_count"] == 0


def test_runner_is_reproducible_with_same_input(tmp_path):
    first = run_entry_logic_experiment(
        _features(),
        _annotations(),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path / "first",
        split_config=_split_config(),
    )
    second = run_entry_logic_experiment(
        _features(),
        _annotations(),
        feature_cols=FEATURE_COLS,
        output_dir=tmp_path / "second",
        split_config=_split_config(),
    )

    assert first["threshold"] == second["threshold"]
    assert first["scores"]["human_entry_similarity"].round(12).tolist() == second["scores"]["human_entry_similarity"].round(12).tolist()
    assert first["review_queue"]["observation_id"].tolist() == second["review_queue"]["observation_id"].tolist()
    assert first["split_summary"]["train_count"] == second["split_summary"]["train_count"]
    output_columns = " ".join(first["scores"].columns).lower()
    assert "buy_signal" not in output_columns
    assert "trade_signal" not in output_columns

def test_runner_rejects_too_few_labeled_samples_without_fake_metrics(tmp_path):
    features = _features().head(2).copy()
    annotations = pd.DataFrame(
        {
            "observation_id": ["obs_00", "obs_01"],
            "human_decision": ["ENTRY", "REJECT"],
            "annotation_version": ["test_annotations_v1", "test_annotations_v1"],
            "is_active": [True, True],
        }
    )

    with pytest.raises(ValueError, match="at least 3 labeled ENTRY/REJECT"):
        run_entry_logic_experiment(
            features,
            annotations,
            feature_cols=FEATURE_COLS,
            output_dir=tmp_path,
            split_config=_split_config(),
        )