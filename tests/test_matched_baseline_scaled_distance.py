from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from research.matched_baseline import (
    MatchedBaselineSpec,
    build_match_pool,
    select_matched_controls,
)


def _observations() -> pd.DataFrame:
    rows = [
        ("user_1", "OPEN_LONG", "USER_TRADE", 1),
        ("wrong_absolute_near", "NO_ACTION", "SCHEDULED_BAR", 0),
        ("right_scaled_near", "NO_ACTION", "SCHEDULED_BAR", 0),
        ("volume_anchor_high", "NO_ACTION", "SCHEDULED_BAR", 0),
        ("volume_anchor_low", "NO_ACTION", "SCHEDULED_BAR", 0),
    ]
    return pd.DataFrame(
        [
            {
                "sample_id": sample_id,
                "symbol": "BTCUSDT",
                "interval": "1m",
                "user_action": action,
                "source_type": source_type,
                "is_user_trade": is_user_trade,
            }
            for sample_id, action, source_type, is_user_trade in rows
        ]
    )


def _context() -> pd.DataFrame:
    values = {
        "user_1": {"pre_ret_20": 0.00, "volume_zscore_20": 0.0},
        "wrong_absolute_near": {"pre_ret_20": 0.30, "volume_zscore_20": 1.0},
        "right_scaled_near": {"pre_ret_20": 0.01, "volume_zscore_20": 20.0},
        "volume_anchor_high": {"pre_ret_20": 0.02, "volume_zscore_20": 100.0},
        "volume_anchor_low": {"pre_ret_20": -0.02, "volume_zscore_20": -100.0},
    }
    return pd.DataFrame(
        [
            {"sample_id": sample_id, "feature_name": feature_name, "feature_value": value}
            for sample_id, features in values.items()
            for feature_name, value in features.items()
        ]
    )


@pytest.mark.parametrize("distance_scaling", ["robust", "zscore"])
def test_scaled_distance_selects_relative_state_match(distance_scaling: str):
    pool = build_match_pool(_observations(), _context())

    unscaled = select_matched_controls(
        "user_1",
        pool,
        MatchedBaselineSpec(
            numeric_features=("pre_ret_20", "volume_zscore_20"),
            controls_per_sample=1,
            distance_scaling="none",
        ),
    )
    scaled = select_matched_controls(
        "user_1",
        pool,
        MatchedBaselineSpec(
            numeric_features=("pre_ret_20", "volume_zscore_20"),
            controls_per_sample=1,
            distance_scaling=distance_scaling,
        ),
    )

    assert unscaled["control_sample_id"].tolist() == ["wrong_absolute_near"]
    assert scaled["control_sample_id"].tolist() == ["right_scaled_near"]
    assert math.isfinite(float(scaled.iloc[0]["context_distance"]))

    contributions = json.loads(scaled.iloc[0]["distance_contributions_json"])
    assert set(contributions) == {"pre_ret_20", "volume_zscore_20"}
    assert all(value >= 0 for value in contributions.values())


def test_scaled_distance_tolerates_missing_numeric_features():
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
                "sample_id": "control_missing",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "user_action": "NO_ACTION",
                "source_type": "SCHEDULED_BAR",
                "is_user_trade": 0,
            },
        ]
    )
    context = pd.DataFrame(
        [
            {"sample_id": "user_1", "feature_name": "pre_ret_20", "feature_value": 0.01},
            {"sample_id": "user_1", "feature_name": "volume_zscore_20", "feature_value": 5.0},
            {"sample_id": "control_missing", "feature_name": "pre_ret_20", "feature_value": 0.02},
        ]
    )
    pool = build_match_pool(observations, context)

    matches = select_matched_controls(
        "user_1",
        pool,
        MatchedBaselineSpec(
            numeric_features=("pre_ret_20", "volume_zscore_20"),
            controls_per_sample=1,
            distance_scaling="robust",
        ),
    )

    assert matches["control_sample_id"].tolist() == ["control_missing"]
    assert math.isfinite(float(matches.iloc[0]["context_distance"]))
    contributions = json.loads(matches.iloc[0]["distance_contributions_json"])
    assert set(contributions) == {"pre_ret_20"}
