from __future__ import annotations

import json

import pytest

from backtesting.parameter_schema import StrategyRuleParams


def test_default_strategy_rule_params_are_valid_and_long_only():
    params = StrategyRuleParams()

    assert params.validate() is params
    assert params.strategy_name == "deep_v_reversal"
    assert params.direction == "long_only"
    assert params.entry_mode == "next_open"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trend_lookback", 0),
        ("min_drop_pct", 0.0),
        ("min_drop_pct", 1.1),
        ("volume_spike_multiple", 0.0),
        ("take_profit_pct", 0.0),
        ("stop_loss_pct", -0.01),
        ("max_holding_bars", 0),
    ],
)
def test_strategy_rule_params_reject_invalid_values(field, value):
    params = StrategyRuleParams(**{field: value})

    with pytest.raises(ValueError, match=field):
        params.validate()


def test_strategy_rule_params_round_trip_through_dict_and_json():
    params = StrategyRuleParams(
        trend_lookback=30,
        min_drop_pct=0.035,
        volume_spike_multiple=2.5,
        lower_shadow_min_ratio=0.5,
        take_profit_pct=0.04,
        stop_loss_pct=0.02,
    )

    restored_dict = StrategyRuleParams.from_dict(params.to_dict())
    restored_json = StrategyRuleParams.from_json(params.to_json())

    assert restored_dict == params
    assert restored_json == params
    assert json.loads(params.to_json()) == params.to_dict()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("strategy_name", "another_strategy"),
        ("direction", "short_only"),
        ("direction", "both"),
        ("exit_mode", "timeout"),
        ("exit_mode", "signal"),
        ("allow_overlap_positions", True),
    ],
)
def test_strategy_rule_params_reject_capabilities_not_implemented_by_deep_v(field, value):
    params = StrategyRuleParams(**{field: value})

    with pytest.raises(ValueError, match=field):
        params.validate()
