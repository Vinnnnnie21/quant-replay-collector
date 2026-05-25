from __future__ import annotations

import pandas as pd

from research.factor_ic import factor_ic


def test_factor_ic_computes_rank_ic_without_required_scipy():
    samples = pd.DataFrame(
        {
            "body_pct": [1, 2, 3, 4, 5],
            "fwd_ret_10_side_adj": [1, 2, 3, 4, 5],
            "event_time_bjt": pd.date_range("2026-01-01", periods=5, freq="MS"),
        }
    )
    result = factor_ic(samples, "body_pct")
    assert result["spearman_rank_ic"] == 1.0
    assert result["sample_count"] == 5
