from __future__ import annotations

import pandas as pd

from research.walk_forward import chronological_train_test_split, evaluate_rule_on_split


def test_chronological_split_never_randomizes_time():
    samples = pd.DataFrame(
        {
            "event_time_bjt": ["2026-01-03", "2026-01-01", "2026-01-04", "2026-01-02"],
            "body_pct": [3, 1, 4, 2],
            "fwd_ret_10_side_adj": [0.1, -0.1, 0.2, -0.2],
        }
    )
    train, test = chronological_train_test_split(samples, train_ratio=0.5)
    assert pd.to_datetime(train["event_time_bjt"]).max() < pd.to_datetime(test["event_time_bjt"]).min()
    result = evaluate_rule_on_split(train, test, "r1", [{"column": "body_pct", "op": ">=", "value": 1}])
    assert result["rule_id"] == "r1"
