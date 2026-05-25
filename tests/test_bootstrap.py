from __future__ import annotations

import math

import numpy as np

from research.bootstrap import bootstrap_mean_ci, bootstrap_win_rate_ci


def test_bootstrap_handles_empty_and_nan_samples():
    assert math.isnan(bootstrap_mean_ci([])["ci_low"])
    assert math.isnan(bootstrap_mean_ci([np.nan, np.nan])["estimate"])


def test_bootstrap_mean_and_win_rate_return_intervals():
    mean_ci = bootstrap_mean_ci([1.0, 2.0, 3.0], n_boot=100)
    win_ci = bootstrap_win_rate_ci([True, False, True], n_boot=100)
    assert mean_ci["ci_low"] <= mean_ci["estimate"] <= mean_ci["ci_high"]
    assert 0 <= win_ci["ci_low"] <= win_ci["ci_high"] <= 100
