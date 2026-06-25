from __future__ import annotations

import pandas as pd
import pytest

from quant_collector_app.research.entry_logic_scoring import (
    explain_similarity_score,
    fit_entry_prototype,
    rank_unlabeled_candidates,
    score_entry_similarity,
)


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["obs_entry_1", "obs_entry_2", "obs_reject_1", "obs_unlabeled_1"],
            "lower_shadow_ratio": [0.70, 0.90, 0.20, 0.80],
            "volume_zscore_20": [2.0, 3.0, -0.5, 2.5],
            "range_pct": [0.030, 0.050, 0.015, 0.040],
        }
    )


def _annotations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["obs_entry_1", "obs_entry_2", "obs_reject_1", "obs_unlabeled_1"],
            "human_decision": ["ENTRY", "ENTRY", "REJECT", "UNLABELED"],
        }
    )


def test_entry_samples_fit_prototype_with_robust_center_and_scale():
    prototype = fit_entry_prototype(
        _features(),
        _annotations(),
        ["lower_shadow_ratio", "volume_zscore_20", "range_pct"],
    )

    assert prototype["method"] == "entry_prototype_median_iqr"
    assert prototype["entry_count"] == 2
    assert prototype["feature_cols"] == ["lower_shadow_ratio", "volume_zscore_20", "range_pct"]
    assert prototype["center"]["lower_shadow_ratio"] == 0.80
    assert prototype["center"]["volume_zscore_20"] == 2.5
    assert prototype["scale"]["lower_shadow_ratio"] > 0


def test_samples_closer_to_entry_center_receive_higher_similarity():
    prototype = fit_entry_prototype(
        _features(),
        _annotations(),
        ["lower_shadow_ratio", "volume_zscore_20", "range_pct"],
    )
    candidates = pd.DataFrame(
        {
            "observation_id": ["near_entry", "far_from_entry"],
            "lower_shadow_ratio": [0.81, 0.10],
            "volume_zscore_20": [2.55, -2.0],
            "range_pct": [0.041, 0.010],
        }
    )

    scores = score_entry_similarity(candidates, prototype)

    near = scores.loc[scores["observation_id"] == "near_entry", "human_entry_similarity"].iloc[0]
    far = scores.loc[scores["observation_id"] == "far_from_entry", "human_entry_similarity"].iloc[0]
    assert near > far
    assert scores["setup_confidence"].between(0, 1).all()
    assert set(["nearest_entry_pattern", "explanation_features"]).issubset(scores.columns)


def test_missing_values_and_constant_features_do_not_break_scoring():
    features = pd.DataFrame(
        {
            "observation_id": ["entry_1", "entry_2", "candidate_missing"],
            "lower_shadow_ratio": [0.8, 0.8, None],
            "volume_zscore_20": [2.0, 2.0, 2.0],
        }
    )
    annotations = pd.DataFrame(
        {
            "observation_id": ["entry_1", "entry_2", "candidate_missing"],
            "human_decision": ["ENTRY", "ENTRY", "UNLABELED"],
        }
    )
    prototype = fit_entry_prototype(features, annotations, ["lower_shadow_ratio", "volume_zscore_20"])

    scores = score_entry_similarity(features.tail(1), prototype)

    assert prototype["scale"]["lower_shadow_ratio"] == 1.0
    assert prototype["scale"]["volume_zscore_20"] == 1.0
    assert scores.iloc[0]["missing_feature_count"] == 1
    assert scores.iloc[0]["human_entry_similarity"] == 1.0


def test_rank_unlabeled_candidates_returns_stable_top_k_order():
    features = pd.DataFrame(
        {
            "observation_id": ["entry_1", "entry_2", "reject_1", "unlabeled_a", "unlabeled_b", "unlabeled_c"],
            "lower_shadow_ratio": [0.8, 0.8, 0.2, 0.8, 0.8, 0.3],
            "volume_zscore_20": [2.0, 2.0, -1.0, 2.0, 2.0, -2.0],
            "range_pct": [0.04, 0.04, 0.01, 0.04, 0.04, 0.01],
        }
    )
    annotations = pd.DataFrame(
        {
            "observation_id": ["entry_1", "entry_2", "reject_1", "unlabeled_a", "unlabeled_b", "unlabeled_c"],
            "human_decision": ["ENTRY", "ENTRY", "REJECT", "UNLABELED", "UNLABELED", "UNLABELED"],
        }
    )

    ranked = rank_unlabeled_candidates(features, annotations, top_k=2)

    assert ranked["observation_id"].tolist() == ["unlabeled_a", "unlabeled_b"]
    assert ranked["human_entry_similarity"].is_monotonic_decreasing
    assert "reject_1" not in ranked["observation_id"].tolist()


def test_explanation_features_return_largest_similarity_contributors():
    prototype = fit_entry_prototype(
        _features(),
        _annotations(),
        ["lower_shadow_ratio", "volume_zscore_20", "range_pct"],
    )
    row = pd.Series(
        {
            "observation_id": "candidate",
            "lower_shadow_ratio": 0.80,
            "volume_zscore_20": 2.50,
            "range_pct": 0.20,
        }
    )

    explanation = explain_similarity_score(row, prototype, top_n_features=2)

    assert [item["feature"] for item in explanation] == ["lower_shadow_ratio", "volume_zscore_20"]
    assert explanation[0]["normalized_distance"] == 0.0
    assert explanation[0]["similarity_contribution"] == 1.0


def test_scoring_outputs_do_not_include_trade_signal_or_outcome_fields():
    prototype = fit_entry_prototype(
        _features(),
        _annotations(),
        ["lower_shadow_ratio", "volume_zscore_20", "range_pct"],
    )

    scores = score_entry_similarity(_features(), prototype)
    joined_columns = " ".join(scores.columns).lower()

    assert "buy_signal" not in joined_columns
    assert "future" not in joined_columns
    assert "fwd" not in joined_columns
    assert "mfe" not in joined_columns
    assert "mae" not in joined_columns


def test_outcome_or_signal_feature_columns_are_rejected():
    features = _features().assign(fwd_ret_10=[0.1, 0.2, -0.1, 0.0], buy_signal=[0, 1, 0, 0])

    with pytest.raises(ValueError, match="Outcome or trading-signal feature"):
        fit_entry_prototype(features, _annotations(), ["lower_shadow_ratio", "fwd_ret_10"])

    with pytest.raises(ValueError, match="Outcome or trading-signal feature"):
        fit_entry_prototype(features, _annotations(), ["lower_shadow_ratio", "buy_signal"])
