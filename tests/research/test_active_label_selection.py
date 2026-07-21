from __future__ import annotations

import pandas as pd

from quant_collector_app.research.active_label_selection import (
    build_label_review_queue,
    select_high_similarity_unlabeled,
    select_diverse_candidates,
    select_uncertain_candidates,
)


def _scored() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": [
                "entry_1",
                "reject_1",
                "uncertain_1",
                "unlabeled_hi",
                "unlabeled_a",
                "unlabeled_b",
                "unlabeled_low",
            ],
            "human_entry_similarity": [0.99, 0.10, 0.50, 0.92, 0.55, 0.55, 0.25],
            "setup_confidence": [0.99, 0.10, 0.50, 0.92, 0.55, 0.55, 0.25],
            "nearest_entry_pattern": ["ENTRY_PROTOTYPE_MEDIAN_IQR"] * 7,
            "explanation_features": [[] for _ in range(7)],
        }
    )


def _annotations() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_id": ["entry_1", "reject_1", "uncertain_1", "unlabeled_hi"],
            "human_decision": ["ENTRY", "REJECT", "UNCERTAIN", "UNLABELED"],
            "is_active": [1, 1, 1, 1],
        }
    )


def test_high_similarity_queue_excludes_labeled_rows_and_sorts_descending():
    queue = select_high_similarity_unlabeled(_scored(), _annotations(), top_k=2)

    assert queue["observation_id"].tolist() == ["unlabeled_a", "unlabeled_b"]
    assert queue["human_entry_similarity"].tolist() == [0.55, 0.55]
    assert queue["review_reason"].tolist() == ["high_similarity_to_entry_prototype"] * 2
    assert queue["review_id"].is_unique
    assert not {"entry_1", "reject_1", "uncertain_1", "unlabeled_hi"} & set(queue["observation_id"])


def test_uncertain_candidates_select_middle_similarity_band():
    queue = build_label_review_queue(
        _scored(),
        _annotations(),
        pd.DataFrame({"observation_id": _scored()["observation_id"]}),
        mode={"name": "uncertain", "lower": 0.40, "upper": 0.70, "top_k": 2},
    )

    assert queue["observation_id"].tolist() == ["unlabeled_a", "unlabeled_b"]
    assert queue["review_reason"].tolist() == ["uncertain_similarity_band"] * 2


def test_diverse_candidates_do_not_repeat_observations_and_cover_shapes():
    feature_df = pd.DataFrame(
        {
            "observation_id": ["unlabeled_hi", "unlabeled_a", "unlabeled_b", "unlabeled_low"],
            "lower_shadow_ratio": [0.9, 0.88, 0.50, 0.2],
            "volume_zscore_20": [2.5, 2.4, 0.1, -1.0],
        }
    )
    scored = _scored()[_scored()["observation_id"].isin(feature_df["observation_id"])]

    queue = select_diverse_candidates(scored, feature_df, top_k=3)

    assert len(queue) == 3
    assert queue["observation_id"].is_unique
    assert "unlabeled_hi" in queue["observation_id"].tolist()
    assert "unlabeled_low" in queue["observation_id"].tolist()
    assert len(set(queue["diversity_bucket"])) >= 2
    assert set(queue["review_reason"]) == {"diverse_feature_coverage"}


def test_build_label_review_queue_dispatches_mode_and_handles_large_top_k():
    feature_df = pd.DataFrame(
        {
            "observation_id": ["unlabeled_hi", "unlabeled_a", "unlabeled_b", "unlabeled_low"],
            "lower_shadow_ratio": [0.9, 0.5, 0.35, 0.2],
        }
    )

    queue = build_label_review_queue(
        _scored(),
        _annotations(),
        feature_df,
        mode={"name": "high_similarity", "top_k": 10},
    )

    assert queue["observation_id"].tolist() == ["unlabeled_a", "unlabeled_b", "unlabeled_low"]
    assert set(queue["review_mode"]) == {"high_similarity"}
    assert "review_reason" in queue.columns


def test_review_queue_output_does_not_contain_trade_advice_columns():
    base = _scored()
    scored = base.assign(
        fwd_ret_10=[0.1] * len(base),
        mfe_10=[0.2] * len(base),
        mae_10=[-0.1] * len(base),
    )
    queue = select_high_similarity_unlabeled(scored, _annotations(), top_k=3)
    joined_columns = " ".join(queue.columns).lower()

    assert "buy_signal" not in joined_columns
    assert "sell_signal" not in joined_columns
    assert "trade_signal" not in joined_columns
    assert "trade_advice" not in joined_columns
    assert "recommendation" not in joined_columns
    assert "fwd" not in joined_columns
    assert "mfe" not in joined_columns
    assert "mae" not in joined_columns


def test_review_queue_falls_back_to_rule_seeded_candidates_without_scores():
    observations = pd.DataFrame(
        {
            "observation_id": ["obs_b", "obs_a", "obs_c"],
            "candidate_source": ["rule_seeded", "rule_seeded", "manual_context"],
            "candidate_reason": ["review_filter", "review_filter", "manual_review"],
            "decision_bar_index": [20, 10, 30],
        }
    )
    annotations = pd.DataFrame({"observation_id": ["obs_c"], "human_decision": ["ENTRY"], "is_active": [1]})

    queue = build_label_review_queue(
        pd.DataFrame(columns=["observation_id"]),
        annotations,
        observations,
        mode={"name": "high_similarity", "top_k": 5, "queue_version": "test_v1"},
    )

    assert queue["observation_id"].tolist() == ["obs_a", "obs_b"]
    assert queue["review_reason"].tolist() == ["rule_seeded_unscored_candidate"] * 2
    assert queue["review_id"].tolist() == build_label_review_queue(
        pd.DataFrame(columns=["observation_id"]),
        annotations,
        observations,
        mode={"name": "high_similarity", "top_k": 5, "queue_version": "test_v1"},
    )["review_id"].tolist()
