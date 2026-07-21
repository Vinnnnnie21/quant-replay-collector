from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from time_series_analysis.concentration_bounds import (
    cantelli_bound,
    chebyshev_bound,
    empirical_sigma_exceedance,
    summarize_concentration_bounds,
)


def test_chebyshev_bound_matches_distribution_free_formula():
    assert chebyshev_bound(2) == pytest.approx(0.25)
    assert chebyshev_bound(3) == pytest.approx(1 / 9)


def test_cantelli_bound_matches_one_sided_formula():
    assert cantelli_bound(3) == pytest.approx(0.1)


def test_empirical_sigma_exceedance_returns_a_valid_ratio():
    returns = pd.Series([-0.05, -0.02, -0.01, 0.0, 0.01, 0.02, 0.07])

    ratio = empirical_sigma_exceedance(returns, 2)

    assert 0.0 <= ratio <= 1.0


def test_summary_handles_nan_empty_and_zero_std_with_warnings():
    with_nan = summarize_concentration_bounds([np.nan, -0.02, 0.0, 0.02], ks=(2,))
    empty = summarize_concentration_bounds([], ks=(2,))
    zero_std = summarize_concentration_bounds([0.01, 0.01, 0.01], ks=(2,))

    assert with_nan["sample_size"] == 3
    assert "nan_values_dropped" in with_nan["warnings"]
    assert "insufficient_sample" in empty["warnings"]
    assert "zero_std" in zero_std["warnings"]
    assert math.isnan(empty["rows"][0]["empirical_two_sided_exceedance"])
    assert math.isnan(zero_std["rows"][0]["empirical_downside_exceedance"])


def test_summary_fields_are_risk_diagnostics_not_trading_signals():
    result = summarize_concentration_bounds([-0.03, -0.01, 0.0, 0.01, 0.04], ks=(2, 3))

    assert result["diagnostic_name"] == "concentration_bounds"
    assert "Chebyshev" in result["disclaimer"]
    assert "not a prediction" in result["disclaimer"]
    assert "not trading advice" in result["disclaimer"]
    assert "trading_signal" not in result
    assert "trading_signal" not in result["rows"][0]
    assert set(result["rows"][0]) >= {
        "k",
        "chebyshev_bound",
        "cantelli_downside_bound",
        "empirical_two_sided_exceedance",
        "empirical_downside_exceedance",
        "sample_size",
        "mean",
        "std",
        "warnings",
    }
