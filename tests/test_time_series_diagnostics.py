from __future__ import annotations

import numpy as np

from time_series_analysis.diagnostics import descriptive_stats, jarque_bera_test


def test_jarque_bera_statistic_is_larger_for_heavy_tail_sample():
    rng = np.random.default_rng(42)
    normal = jarque_bera_test(rng.normal(size=3000))
    heavy = jarque_bera_test(rng.standard_t(df=3, size=3000))
    assert heavy["statistic"] > normal["statistic"]
    assert heavy["p_value_method"] == "chi_square_df2_closed_form"


def test_descriptive_stats_include_tail_and_normality_fields():
    result = descriptive_stats([0.0, 0.01, -0.02, 0.03, -0.04, 0.02])
    assert result["n"] == 6
    assert "excess_kurtosis" in result
    assert "jb_statistic" in result
    assert result["jb_p_value_method"] == "chi_square_df2_closed_form"
    assert "q05" in result
