from __future__ import annotations

import pandas as pd
import pytest

from quant_collector_app.research.pu_entry_learning import (
    build_pu_dataset,
    estimate_positive_prior_basic,
    evaluate_pu_ranking_with_labeled_holdout,
    score_unlabeled_by_positive_density,
)


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "entry_2", "unlabeled_1", "unlabeled_2", "reject_1"],
            "lower_shadow_ratio": [0.80, 0.90, 0.82, 0.30, 0.20],
            "volume_zscore_20": [2.0, 2.5, 2.1, -0.5, -1.0],
            "range_pct": [0.040, 0.045, 0.041, 0.015, 0.010],
        }
    )


def _annotations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "entry_2", "unlabeled_1", "unlabeled_2", "reject_1"],
            "human_decision": ["ENTRY", "ENTRY", "UNLABELED", "UNLABELED", "REJECT"],
        }
    )


def test_entry_and_unlabeled_rows_build_pu_dataset_without_negative_rejects():
    dataset = build_pu_dataset(
        _features(),
        _annotations(),
        ["lower_shadow_ratio", "volume_zscore_20", "range_pct"],
    )

    assert dataset.loc[dataset["observation_id"] == "entry_1", "pu_role"].iloc[0] == "positive"
    assert dataset.loc[dataset["observation_id"] == "unlabeled_1", "pu_role"].iloc[0] == "unlabeled"
    assert dataset.loc[dataset["observation_id"] == "reject_1", "pu_role"].iloc[0] == "holdout_reject"
    assert dataset.loc[dataset["observation_id"] == "reject_1", "pu_label"].isna().all()
    assert set(dataset["pu_label"].dropna()) == {1}


def test_missing_entry_rows_raise_clear_error():
    annotations = _annotations().assign(human_decision=["UNLABELED"] * 5)

    with pytest.raises(ValueError, match="At least one ENTRY"):
        build_pu_dataset(_features(), annotations, ["lower_shadow_ratio", "volume_zscore_20"])


def test_positive_prior_basic_counts_entry_against_entry_and_unlabeled_only():
    dataset = build_pu_dataset(_features(), _annotations(), ["lower_shadow_ratio", "volume_zscore_20"])

    prior = estimate_positive_prior_basic(dataset)

    assert prior["positive_count"] == 2
    assert prior["unlabeled_count"] == 2
    assert prior["holdout_reject_count"] == 1
    assert prior["positive_prior"] == pytest.approx(0.5)


def test_unlabeled_samples_receive_stable_similarity_scores():
    dataset = build_pu_dataset(
        _features(),
        _annotations(),
        ["lower_shadow_ratio", "volume_zscore_20", "range_pct"],
    )

    scored = score_unlabeled_by_positive_density(dataset, ["lower_shadow_ratio", "volume_zscore_20", "range_pct"])

    assert scored["observation_id"].tolist() == ["unlabeled_1", "unlabeled_2"]
    assert scored["pu_entry_score"].between(0, 1).all()
    assert scored["human_entry_similarity"].between(0, 1).all()
    assert scored.loc[scored["observation_id"] == "unlabeled_1", "pu_entry_score"].iloc[0] > scored.loc[
        scored["observation_id"] == "unlabeled_2", "pu_entry_score"
    ].iloc[0]


def test_pu_outputs_do_not_include_future_outcome_or_buy_signal_fields():
    features = _features().assign(fwd_ret_10=[0.1] * 5, MFE=[0.2] * 5, MAE=[-0.1] * 5, buy_signal=[0] * 5)
    dataset = build_pu_dataset(features, _annotations(), ["lower_shadow_ratio", "volume_zscore_20"])
    scored = score_unlabeled_by_positive_density(dataset, ["lower_shadow_ratio", "volume_zscore_20"])

    joined = " ".join(scored.columns).lower()
    for token in ("future", "fwd", "mfe", "mae", "hit_tp", "hit_sl", "buy_signal"):
        assert token not in joined

    with pytest.raises(ValueError, match="Outcome or trading-signal feature"):
        build_pu_dataset(features, _annotations(), ["lower_shadow_ratio", "fwd_ret_10"])


def test_labeled_holdout_reports_precision_at_k_and_entry_recall():
    holdout_scores = pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "entry_2", "reject_2"],
            "pu_entry_score": [0.95, 0.90, 0.60, 0.20],
        }
    )
    holdout_annotations = pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "entry_2", "reject_2"],
            "human_decision": ["ENTRY", "REJECT", "ENTRY", "REJECT"],
        }
    )

    metrics = evaluate_pu_ranking_with_labeled_holdout(holdout_scores, holdout_annotations, k=2)

    assert metrics["evaluated_count"] == 4
    assert metrics["manual_entry_count"] == 2
    assert metrics["precision_at_k"] == pytest.approx(0.5)
    assert metrics["recall_on_manual_entries"] == pytest.approx(0.5)
    assert metrics["reject_treated_as_negative_training_sample"] is False
