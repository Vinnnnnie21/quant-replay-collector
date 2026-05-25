from __future__ import annotations

import pandas as pd

from research.factor_binning import bin_factor


def test_factor_binning_does_not_crash_on_duplicate_values():
    samples = pd.DataFrame({"body_pct": [1.0] * 10 + [2.0] * 10, "fwd_ret_10_side_adj": [0.01, -0.01] * 10})
    result = bin_factor(samples, "body_pct", n_bins=5)
    assert not result.empty
    assert "bootstrap_ci_low" in result.columns
