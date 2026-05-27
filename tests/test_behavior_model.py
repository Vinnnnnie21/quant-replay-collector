from __future__ import annotations

import pandas as pd
import pytest

from research.behavior_model import (
    compute_behavior_entropy,
    compute_profile_adherence,
    compute_state_action_table,
    summarize_action_frequency,
    summarize_behavior_model,
)
from strategy_consistency.profile import StrategyProfile


def _observations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"sample_id": "s1", "user_action": "OPEN_LONG", "symbol": "BTCUSDT", "interval": "1m"},
            {"sample_id": "s2", "user_action": "OPEN_LONG", "symbol": "BTCUSDT", "interval": "1m"},
            {"sample_id": "s3", "user_action": "NO_ACTION", "symbol": "BTCUSDT", "interval": "1m"},
            {"sample_id": "s4", "user_action": "NO_ACTION", "symbol": "BTCUSDT", "interval": "1m"},
        ]
    )


def test_action_frequency_and_entropy_are_descriptive_statistics():
    frequency = summarize_action_frequency(_observations())
    entropy = compute_behavior_entropy(_observations())

    values = frequency.set_index("user_action")
    assert values.loc["OPEN_LONG", "count"] == 2
    assert values.loc["NO_ACTION", "frequency"] == pytest.approx(0.5)
    assert entropy["behavior_entropy"] == pytest.approx(1.0)
    assert entropy["sample_count"] == 4
    assert entropy["descriptive_only"] is True


def test_undeclared_profile_is_descriptive_only_and_has_no_discipline_score():
    result = compute_profile_adherence(_observations(), profile=None)

    assert result["descriptive_only"] is True
    assert result["profile_status"] == "UNDECLARED"
    assert result["adherence_rate"] is None
    assert result["violation_count"] is None
    assert result["strategy_effectiveness_evaluated"] is False


def test_only_long_profile_does_not_penalize_absent_shorts_but_flags_executed_short():
    profile = StrategyProfile(
        strategy_id="only_long",
        name="Only Long",
        allowed_sides=["LONG"],
        allowed_symbols=["BTCUSDT"],
        allowed_intervals=["1m"],
        max_holding_bars=None,
    )
    all_long = compute_profile_adherence(_observations(), profile)

    with_short = pd.concat(
        [
            _observations(),
            pd.DataFrame(
                [{"sample_id": "s5", "user_action": "OPEN_SHORT", "symbol": "BTCUSDT", "interval": "1m"}]
            ),
        ],
        ignore_index=True,
    )
    violated = compute_profile_adherence(with_short, profile)

    assert all_long["violation_count"] == 0
    assert all_long["adherence_rate"] == pytest.approx(1.0)
    assert all_long["exit_discipline_evaluated"] is False
    assert violated["violation_count"] == 1
    assert violated["adherence_rate"] == pytest.approx(2 / 3)


def test_state_action_summary_marks_low_sample_and_never_claims_effectiveness():
    context = pd.DataFrame(
        [
            {"sample_id": "s1", "feature_name": "volatility_regime", "feature_value": 1},
            {"sample_id": "s2", "feature_name": "volatility_regime", "feature_value": 1},
            {"sample_id": "s3", "feature_name": "volatility_regime", "feature_value": 2},
            {"sample_id": "s4", "feature_name": "volatility_regime", "feature_value": 2},
        ]
    )

    table = compute_state_action_table(_observations(), context)
    result = summarize_behavior_model(_observations(), context, profile=None, min_sample_count=10)

    assert table["count"].sum() == 4
    assert {"volatility_regime", "user_action", "count", "frequency_in_state"} <= set(table.columns)
    assert result["sample_count"] == 4
    assert result["low_sample_warning"] is True
    assert result["descriptive_only"] is True
    assert result["strategy_effectiveness_evaluated"] is False
    assert result["adherence_rate"] is None
