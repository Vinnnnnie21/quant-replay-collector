from __future__ import annotations

import pandas as pd
import pytest

from research.matched_baseline import (
    MatchedBaselineSpec,
    bootstrap_effect_ci,
    build_match_pool,
    compare_user_vs_controls,
    permutation_test_effect,
    select_matched_controls,
)


def _observations() -> pd.DataFrame:
    return pd.DataFrame(
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
                "sample_id": "control_near",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "user_action": "NO_ACTION",
                "source_type": "SCHEDULED_BAR",
                "is_user_trade": 0,
            },
            {
                "sample_id": "control_wrong_symbol",
                "symbol": "ETHUSDT",
                "interval": "1m",
                "user_action": "NO_ACTION",
                "source_type": "SCHEDULED_BAR",
                "is_user_trade": 0,
            },
            {
                "sample_id": "control_wrong_interval",
                "symbol": "BTCUSDT",
                "interval": "5m",
                "user_action": "NO_ACTION",
                "source_type": "AUTO_CANDIDATE",
                "is_user_trade": 0,
            },
        ]
    )


def _context() -> pd.DataFrame:
    values = {
        "user_1": {"pre_ret_20": -0.020, "realized_vol_20": 0.012, "volume_zscore_20": 0.20},
        "control_near": {"pre_ret_20": -0.019, "realized_vol_20": 0.011, "volume_zscore_20": 0.22},
        "control_wrong_symbol": {"pre_ret_20": -0.020, "realized_vol_20": 0.012, "volume_zscore_20": 0.20},
        "control_wrong_interval": {"pre_ret_20": -0.020, "realized_vol_20": 0.012, "volume_zscore_20": 0.20},
    }
    return pd.DataFrame(
        [
            {"sample_id": sample_id, "feature_name": name, "feature_value": value}
            for sample_id, features in values.items()
            for name, value in features.items()
        ]
    )


def test_matched_controls_are_same_market_and_never_the_user_sample():
    pool = build_match_pool(_observations(), _context())
    matches = select_matched_controls(
        "user_1",
        pool,
        MatchedBaselineSpec(controls_per_sample=3, numeric_features=("pre_ret_20", "realized_vol_20", "volume_zscore_20")),
    )

    assert matches["control_sample_id"].tolist() == ["control_near"]
    assert set(matches["symbol"]) == {"BTCUSDT"}
    assert set(matches["interval"]) == {"1m"}
    assert "user_1" not in set(matches["control_sample_id"])


def test_match_pool_rejects_outcome_fields_in_context_features():
    invalid_context = pd.concat(
        [
            _context(),
            pd.DataFrame([{"sample_id": "user_1", "feature_name": "fwd_ret", "feature_value": 9.0}]),
        ],
        ignore_index=True,
    )

    with pytest.raises(ValueError):
        build_match_pool(_observations(), invalid_context)


def test_executed_action_is_not_accepted_as_control_even_if_source_is_scheduled_bar():
    observations = pd.concat(
        [
            _observations(),
            pd.DataFrame(
                [
                    {
                        "sample_id": "executed_scheduled",
                        "symbol": "BTCUSDT",
                        "interval": "1m",
                        "user_action": "OPEN_SHORT",
                        "source_type": "SCHEDULED_BAR",
                        "is_user_trade": 1,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    context = pd.concat(
        [
            _context(),
            pd.DataFrame(
                [
                    {"sample_id": "executed_scheduled", "feature_name": "pre_ret_20", "feature_value": -0.020},
                    {"sample_id": "executed_scheduled", "feature_name": "realized_vol_20", "feature_value": 0.012},
                    {"sample_id": "executed_scheduled", "feature_name": "volume_zscore_20", "feature_value": 0.20},
                ]
            ),
        ],
        ignore_index=True,
    )
    pool = build_match_pool(observations, context)

    matches = select_matched_controls(
        "user_1",
        pool,
        MatchedBaselineSpec(controls_per_sample=3, numeric_features=("pre_ret_20", "realized_vol_20", "volume_zscore_20")),
    )

    assert "executed_scheduled" not in set(matches["control_sample_id"])


def test_effect_and_resampling_statistics_are_computed_after_matching_and_reproducible():
    pool = build_match_pool(_observations(), _context())
    matches = select_matched_controls(
        "user_1",
        pool,
        MatchedBaselineSpec(controls_per_sample=1, numeric_features=("pre_ret_20", "realized_vol_20")),
    )
    outcomes = pd.DataFrame(
        [
            {"sample_id": "user_1", "fwd_ret": 0.04},
            {"sample_id": "control_near", "fwd_ret": 0.01},
        ]
    )

    comparison = compare_user_vs_controls(matches, outcomes, metric="fwd_ret")

    assert comparison.iloc[0]["effect_size"] == pytest.approx(0.03)

    effects = pd.DataFrame({"effect_size": [0.03, 0.01, 0.02, 0.04]})
    assert bootstrap_effect_ci(effects, n_bootstrap=100, random_seed=17) == bootstrap_effect_ci(
        effects, n_bootstrap=100, random_seed=17
    )
    assert permutation_test_effect(effects, n_permutations=100, random_seed=17) == permutation_test_effect(
        effects, n_permutations=100, random_seed=17
    )
