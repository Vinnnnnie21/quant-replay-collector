from __future__ import annotations

import pandas as pd

from event_study import build_event_study_summary


def test_event_study_includes_distribution_ci_and_warnings():
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "event_type": ["OPEN", "OPEN", "CLOSE"],
            "side": ["LONG", "LONG", "SHORT"],
            "label_tags_json": ['["wick"]', '["wick"]', '["break"]'],
        }
    )
    features = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "fwd_ret_1_side_adj": [0.01, -0.02, 0.03],
        }
    )

    out = build_event_study_summary(events, features)
    wick = out[out["label_tag"] == "wick"].iloc[0]
    assert wick["sample_count"] == 2
    assert "fwd_ret_1_side_adj_std" in out.columns
    assert "fwd_ret_1_side_adj_mean_ci95_low" in out.columns
    assert bool(wick["small_sample_warning"]) is True
    assert "exploratory" in wick["multiple_testing_warning"]
