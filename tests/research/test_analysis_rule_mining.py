from __future__ import annotations

import pandas as pd
import pytest

from analysis.rule_mining import evaluate_rule, generate_candidate_rules


def _df():
    return pd.DataFrame({"pre_ret_20": [i / 100 for i in range(-50, 50)], "event_lower_wick_ratio": [0.5] * 100, "fwd_ret_10_side_adj": [0.01 if i > 0 else -0.01 for i in range(-50, 50)], "mfe_10": [0.02] * 100, "mae_10": [-0.01] * 100})


def test_single_condition_rule():
    out = evaluate_rule(_df(), [{"column": "pre_ret_20", "op": ">", "value": 0}], "fwd_ret_10_side_adj")
    assert out["sample_count"] == 49
    assert out["win_rate_pct"] == 100.0


def test_double_condition_generation():
    out = generate_candidate_rules(_df(), min_samples=30)
    assert not out.empty


def test_sample_too_small_filtered():
    out = generate_candidate_rules(_df().head(10), min_samples=30)
    assert out.empty


def test_illegal_field_and_operator():
    with pytest.raises(ValueError):
        evaluate_rule(_df(), [{"column": "bad", "op": ">=", "value": 0}], "fwd_ret_10_side_adj")
    with pytest.raises(ValueError):
        evaluate_rule(_df(), [{"column": "pre_ret_20", "op": "!=", "value": 0}], "fwd_ret_10_side_adj")


def test_empty_data():
    out = evaluate_rule(pd.DataFrame(), [{"column": "x", "op": ">=", "value": 0}], "y")
    assert out["sample_count"] == 0
