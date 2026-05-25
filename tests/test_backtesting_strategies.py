from __future__ import annotations

import pandas as pd
import pytest

from backtesting.strategies import FeatureRuleLongStrategy, MovingAverageCrossStrategy, load_candidate_rule
from backtesting.types import Signal


@pytest.mark.parametrize("column", ["fwd_ret_10", "post_close_1", "mfe_10", "mae_10", "manual_trade_final_return_pct"])
def test_feature_rule_rejects_future_fields(column):
    with pytest.raises(ValueError):
        FeatureRuleLongStrategy([{"column": column, "op": ">", "value": 0}])


def test_load_candidate_rule_from_dataframe():
    rules = pd.DataFrame(
        {
            "conditions_json": [
                '[{"column": "pre_ret_20", "op": "<=", "value": -0.03}]',
                '[{"column": "event_lower_wick_ratio", "op": ">=", "value": 0.4}]',
            ]
        }
    )
    strategy = load_candidate_rule(rules, 1)
    assert isinstance(strategy, FeatureRuleLongStrategy)
    assert strategy.conditions[0]["column"] == "event_lower_wick_ratio"


def test_load_candidate_rule_rejects_future_fields():
    rules = pd.DataFrame({"conditions_json": ['[{"column": "mfe_10", "op": ">", "value": 0.01}]']})
    with pytest.raises(ValueError):
        load_candidate_rule(rules, 0)


def test_feature_rule_opens_and_exits():
    strategy = FeatureRuleLongStrategy([{"column": "pre_ret_20", "op": "<=", "value": -0.03}], exit_bars=2)
    row = pd.Series({"pre_ret_20": -0.04, "high": 101, "low": 99})
    assert strategy.on_bar(0, row, pd.DataFrame([row]), None) == Signal.OPEN_LONG
    position = {"side": "LONG", "entry_bar_index": 0, "entry_fill_price": 100}
    assert strategy.on_bar(1, row, pd.DataFrame([row, row]), position) == Signal.CLOSE_LONG


def test_ma_strategy_returns_hold_until_enough_data():
    strategy = MovingAverageCrossStrategy(fast_window=2, slow_window=5)
    history = pd.DataFrame({"close": [1, 2, 3]})
    assert strategy.on_bar(2, history.iloc[-1], history, None) == Signal.HOLD
