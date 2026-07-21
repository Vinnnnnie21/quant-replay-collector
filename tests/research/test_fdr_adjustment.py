from __future__ import annotations

import pandas as pd
import pytest

from research.multiple_testing import add_fdr_results, benjamini_hochberg, multiple_testing_warning


def test_benjamini_hochberg_computes_stable_q_values():
    result = benjamini_hochberg([0.01, 0.04, 0.03, 0.20], alpha=0.05)

    assert result[0]["q_value"] == pytest.approx(0.04)
    assert result[1]["q_value"] == pytest.approx(0.0533333333)
    assert result[2]["q_value"] == pytest.approx(0.0533333333)
    assert result[3]["q_value"] == pytest.approx(0.20)
    assert [row["fdr_pass"] for row in result] == [True, False, False, False]


def test_empty_and_missing_p_values_are_handled_without_claiming_pass():
    assert benjamini_hochberg([], alpha=0.1) == []

    rules = pd.DataFrame([{"rule_id": "r1", "p_value": 0.01}, {"rule_id": "r2", "p_value": None}])
    adjusted = add_fdr_results(rules, alpha=0.1)

    assert {"q_value", "fdr_pass", "fdr_status"} <= set(adjusted.columns)
    assert adjusted.loc[adjusted["rule_id"] == "r2", "fdr_status"].iloc[0] == "unavailable"
    assert bool(adjusted.loc[adjusted["rule_id"] == "r2", "fdr_pass"].iloc[0]) is False


def test_multiple_testing_warning_is_emitted_for_large_rule_search():
    assert multiple_testing_warning(21, threshold=20)
    assert multiple_testing_warning(20, threshold=20) is None
