from __future__ import annotations

import pandas as pd
import pytest

from backtesting.rule_evaluator import RuleEvaluationError, evaluate_rule


def test_rule_evaluator_supports_nested_all_any_numeric_conditions():
    rule = {
        "all": [
            {"feature": "volume_ratio_20", "op": ">=", "value": 1.8},
            {
                "any": [
                    {"feature": "pre_ret_20", "op": "<=", "value": -0.03},
                    {"feature": "close_position", "op": ">=", "value": 0.7},
                ]
            },
        ]
    }

    assert evaluate_rule(
        rule,
        pd.Series(
            {
                "volume_ratio_20": 2.0,
                "pre_ret_20": -0.01,
                "close_position": 0.75,
            }
        ),
    ) is True


def test_rule_evaluator_fails_clearly_when_required_feature_is_missing():
    rule = {"feature": "volume_ratio_20", "op": ">=", "value": 1.8}

    with pytest.raises(RuleEvaluationError, match="volume_ratio_20"):
        evaluate_rule(rule, pd.Series({"close": 100.0}))
