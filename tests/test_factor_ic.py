from __future__ import annotations

import pandas as pd
import pytest

from research.factor_ic import build_factor_ic_summary, factor_ic


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


def test_factor_ic_reports_bootstrap_ci_and_approximate_p_value_for_overlapping_label():
    samples = pd.DataFrame(
        {
            "body_pct": [i / 10 for i in range(60)],
            "fwd_ret_10_side_adj": [i / 100 for i in range(60)],
            "event_time_bjt": pd.date_range("2026-01-01", periods=60, freq="D"),
        }
    )

    result = factor_ic(
        samples,
        "body_pct",
        label="fwd_ret_10_side_adj",
        n_bootstrap=80,
        random_seed=7,
    )

    assert result["pearson_ic"] == pytest.approx(1.0)
    assert result["spearman_rank_ic"] == 1.0
    assert result["approximate_p_value"] == result["p_value"]
    assert "p_value_is_approximate" in result["warning"]
    assert "overlapping_forward_returns" in result["warning"]
    assert result["ic_bootstrap_ci_low"] <= result["spearman_rank_ic"]
    assert result["ic_bootstrap_ci_high"] >= result["spearman_rank_ic"]
    assert result["block_size"] >= 10


def test_factor_ic_marks_low_time_block_count_without_crashing():
    samples = pd.DataFrame(
        {
            "body_pct": [0.1, 0.2, 0.3, 0.4],
            "fwd_ret_1_side_adj": [0.01, 0.02, -0.01, -0.02],
            "event_time_bjt": pd.date_range("2026-01-01", periods=4, freq="D"),
        }
    )

    result = factor_ic(samples, "body_pct", label="fwd_ret_1_side_adj", min_time_blocks=3)

    assert "ic_positive_ratio" in result
    assert "ic_mean_by_block" in result
    assert "ic_std_by_block" in result
    assert "stability_score" in result
    assert result["min_block_count_warning"] is True


def test_factor_ic_summary_preserves_new_statistical_boundary_fields():
    features = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(30)],
            "body_pct": [i / 10 for i in range(30)],
        }
    )
    labels = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(30)],
            "fwd_ret_10_side_adj": [i / 100 for i in range(30)],
        }
    )

    summary = build_factor_ic_summary(features, labels, factors=["body_pct"])

    assert {
        "approximate_p_value",
        "ic_bootstrap_ci_low",
        "ic_bootstrap_ci_high",
        "min_block_count_warning",
    } <= set(summary.columns)
