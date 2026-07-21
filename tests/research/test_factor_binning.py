from __future__ import annotations

import pandas as pd
import pytest

from research.factor_binning import bin_factor


def test_factor_binning_does_not_crash_on_duplicate_values():
    samples = pd.DataFrame({"body_pct": [1.0] * 10 + [2.0] * 10, "fwd_ret_10_side_adj": [0.01, -0.01] * 10})
    result = bin_factor(samples, "body_pct", n_bins=5)
    assert not result.empty
    assert "bootstrap_ci_low" in result.columns


def test_factor_binning_propagates_bootstrap_cancellation():
    samples = pd.DataFrame(
        {
            "body_pct": list(range(30)),
            "fwd_ret_10_side_adj": [index / 100 for index in range(30)],
        }
    )
    cancellation_checks = 0

    def cancelled() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 2

    with pytest.raises(RuntimeError, match="research calculation cancelled") as exc_info:
        bin_factor(samples, "body_pct", n_bins=2, cancelled=cancelled)

    assert type(exc_info.value).__name__ == "ResearchCancelled"
