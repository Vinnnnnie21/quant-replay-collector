from __future__ import annotations

import json

import pytest

from analysis.rule_parameter_export import analysis_output_to_backtest_params
from backtesting.parameter_schema import StrategyRuleParams


def test_analysis_output_maps_to_strategy_rule_params():
    params = analysis_output_to_backtest_params(
        {
            "drop_pct_threshold": 0.035,
            "volume_spike_threshold": 2.8,
            "lower_shadow_ratio": 0.52,
            "next_candle_body_ratio": 0.67,
            "trend_window": 30,
            "future_window": 15,
            "tp_threshold": 0.05,
            "sl_threshold": 0.02,
        }
    )

    assert isinstance(params, StrategyRuleParams)
    assert params.min_drop_pct == pytest.approx(0.035)
    assert params.volume_spike_multiple == pytest.approx(2.8)
    assert params.lower_shadow_min_ratio == pytest.approx(0.52)
    assert params.bullish_next_candle_min_body_ratio == pytest.approx(0.67)
    assert params.trend_lookback == 30
    assert params.max_holding_bars == 15
    assert params.take_profit_pct == pytest.approx(0.05)
    assert params.stop_loss_pct == pytest.approx(0.02)


def test_project_candidate_conditions_map_known_aliases_and_keep_defaults():
    conditions = [
        {"column": "pre_ret_20", "op": "<=", "value": -0.04},
        {"column": "event_volume_ratio_20", "op": ">=", "value": 2.3},
        {"column": "event_lower_wick_ratio", "op": ">=", "value": 0.48},
    ]

    params = analysis_output_to_backtest_params({"conditions_json": json.dumps(conditions)})

    assert params.drop_lookback == 20
    assert params.min_drop_pct == pytest.approx(0.04)
    assert params.volume_lookback == 20
    assert params.volume_spike_multiple == pytest.approx(2.3)
    assert params.lower_shadow_min_ratio == pytest.approx(0.48)
    assert params.direction == "long_only"


@pytest.mark.parametrize(
    "forbidden_field",
    ["fwd_ret_10", "mfe_10", "mae_10", "hit_tp", "hit_sl", "outcome_labels"],
)
def test_analysis_mapping_rejects_outcome_fields(forbidden_field):
    with pytest.raises(ValueError, match=forbidden_field):
        analysis_output_to_backtest_params({forbidden_field: 1})


def test_analysis_mapping_rejects_candidate_conditions_without_semantic_mapping():
    unsupported = [
        {"column": "lower_wick_atr_ratio", "op": ">=", "value": 1.5},
        {"column": "volume_zscore_20", "op": ">=", "value": 2.0},
    ]

    with pytest.raises(ValueError, match="lower_wick_atr_ratio"):
        analysis_output_to_backtest_params({"conditions_json": json.dumps(unsupported)})
