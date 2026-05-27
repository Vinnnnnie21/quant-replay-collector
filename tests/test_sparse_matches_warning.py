from __future__ import annotations

import pandas as pd

from research.matched_baseline import MatchedBaselineSpec, summarize_matched_baseline


def _context(sample_ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"sample_id": sample_id, "feature_name": "pre_ret_20", "feature_value": -0.02}
            for sample_id in sample_ids
        ]
    )


def test_no_matching_control_returns_warning_without_significance_claim():
    observations = pd.DataFrame(
        [
            {
                "sample_id": "user_1",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "user_action": "OPEN_LONG",
                "source_type": "USER_TRADE",
                "is_user_trade": 1,
            },
            {
                "sample_id": "unrelated_control",
                "symbol": "ETHUSDT",
                "interval": "1m",
                "user_action": "NO_ACTION",
                "source_type": "SCHEDULED_BAR",
                "is_user_trade": 0,
            },
        ]
    )
    outcomes = pd.DataFrame(
        [{"sample_id": "user_1", "fwd_ret": 0.02}, {"sample_id": "unrelated_control", "fwd_ret": -0.01}]
    )

    result = summarize_matched_baseline(
        observations,
        _context(["user_1", "unrelated_control"]),
        outcomes,
        MatchedBaselineSpec(numeric_features=("pre_ret_20",), min_controls_per_sample=1),
        n_bootstrap=50,
        n_permutations=50,
        random_seed=11,
    )

    assert result["sparse_matches_warning"] is True
    assert result["match_counts"] == {"user_1": 0}
    assert result["effect_size"] is None
    assert result["bootstrap_ci"]["warning"] == "insufficient_sample_for_bootstrap"
    assert result["permutation_test"]["p_value"] is None
    assert result["conclusion_strength"] == "insufficient_evidence"
    assert result["not_trading_signal"] is True


def test_one_matched_control_does_not_fall_back_to_unrelated_market_controls():
    observations = pd.DataFrame(
        [
            {
                "sample_id": "user_1",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "user_action": "OPEN_LONG",
                "source_type": "USER_TRADE",
                "is_user_trade": 1,
            },
            {
                "sample_id": "near_control",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "user_action": "NO_ACTION",
                "source_type": "AUTO_CANDIDATE",
                "is_user_trade": 0,
            },
            {
                "sample_id": "wrong_market",
                "symbol": "ETHUSDT",
                "interval": "1m",
                "user_action": "NO_ACTION",
                "source_type": "SCHEDULED_BAR",
                "is_user_trade": 0,
            },
        ]
    )
    outcomes = pd.DataFrame(
        [
            {"sample_id": "user_1", "fwd_ret": 0.03},
            {"sample_id": "near_control", "fwd_ret": 0.01},
            {"sample_id": "wrong_market", "fwd_ret": -0.99},
        ]
    )

    result = summarize_matched_baseline(
        observations,
        _context(["user_1", "near_control", "wrong_market"]),
        outcomes,
        MatchedBaselineSpec(numeric_features=("pre_ret_20",), min_controls_per_sample=2),
        n_bootstrap=50,
        n_permutations=50,
        random_seed=11,
    )

    assert result["match_counts"] == {"user_1": 1}
    assert result["matched_control_ids"] == ["near_control"]
    assert result["sparse_matches_warning"] is True
