from __future__ import annotations

import pandas as pd
import pytest

from time_series_analysis.entry_distribution_diagnostics import (
    compute_excess_kurtosis,
    compute_quantiles,
    compute_skewness,
    compare_entry_reject_distributions,
    describe_feature_distribution,
    feature_bin_outcome_summary,
    feature_drift_by_period,
    outcome_time_series_diagnostics,
    quantile_feature_binning,
    tail_concentration,
)


def test_skewness_detects_symmetric_and_right_skewed_series():
    assert abs(compute_skewness([-2, -1, 0, 1, 2])) < 1e-12
    assert compute_skewness([1, 1, 1, 2, 10]) > 0


def test_excess_kurtosis_is_higher_for_heavy_tail_series():
    ordinary = [-2, -1, 0, 1, 2, -1, 0, 1]
    heavy_tail = ordinary + [20, -20]

    assert compute_excess_kurtosis(heavy_tail) > compute_excess_kurtosis(ordinary)


def test_quantiles_output_is_stable():
    result = compute_quantiles([1, 2, 3, 4, 5])

    assert list(result.keys()) == ["q01", "q05", "q25", "q50", "q75", "q95", "q99"]
    assert result["q50"] == 3.0
    assert result["q25"] == 2.0
    assert result["q75"] == 4.0


def test_entry_reject_group_statistics_are_computed_per_feature():
    frame = pd.DataFrame(
        {
            "human_decision": ["ENTRY", "ENTRY", "REJECT", "REJECT", "UNLABELED"],
            "lower_shadow_ratio": [0.8, 0.6, 0.2, None, 0.4],
            "volume_zscore_20": [2.0, 1.0, -0.5, 0.0, None],
        }
    )

    described = describe_feature_distribution(frame, "human_decision", ["lower_shadow_ratio", "volume_zscore_20"])
    entry_shadow = described[
        (described["group"] == "ENTRY") & (described["feature"] == "lower_shadow_ratio")
    ].iloc[0]
    reject_shadow = described[
        (described["group"] == "REJECT") & (described["feature"] == "lower_shadow_ratio")
    ].iloc[0]

    assert entry_shadow["n"] == 2
    assert entry_shadow["mean"] == 0.7
    assert reject_shadow["n"] == 1
    assert reject_shadow["missing_count"] == 1

    compared = compare_entry_reject_distributions(frame, "human_decision", ["lower_shadow_ratio"])
    row = compared.iloc[0]
    assert row["feature"] == "lower_shadow_ratio"
    assert row["entry_n"] == 2
    assert row["reject_n"] == 1
    assert row["mean_diff_entry_minus_reject"] == pytest.approx(0.5)


def test_entry_reject_difference_report_includes_iqr_quantile_shape_differences():
    frame = pd.DataFrame(
        {
            "human_decision": ["ENTRY"] * 5 + ["REJECT"] * 5,
            "lower_shadow_ratio": [0.7, 0.8, 0.9, 1.0, 1.1, 0.1, 0.2, 0.3, 0.4, 0.5],
        }
    )

    compared = compare_entry_reject_distributions(frame, "human_decision", ["lower_shadow_ratio"])
    row = compared.iloc[0]

    assert row["median_diff_entry_minus_reject"] == pytest.approx(0.6)
    assert row["iqr_diff_entry_minus_reject"] == pytest.approx(0.0)
    assert row["quantile_diff_entry_minus_reject"]["q50"] == pytest.approx(0.6)
    assert "skewness_diff_entry_minus_reject" in compared.columns
    assert "excess_kurtosis_diff_entry_minus_reject" in compared.columns


def test_quantile_feature_binning_counts_entry_reject_and_entry_rate():
    frame = pd.DataFrame(
        {
            "human_decision": ["REJECT", "REJECT", "ENTRY", "ENTRY", "ENTRY", "REJECT"],
            "lower_shadow_ratio": [0.1, 0.2, 0.7, 0.8, 0.9, 1.0],
        }
    )

    bins = quantile_feature_binning(frame, "human_decision", ["lower_shadow_ratio"], q=3)

    assert bins["feature"].tolist() == ["lower_shadow_ratio"] * 3
    assert bins["total_count"].sum() == 6
    assert bins.loc[bins["bin_id"] == 0, "entry_count"].iloc[0] == 0
    assert bins.loc[bins["bin_id"] == 1, "entry_rate"].iloc[0] == pytest.approx(1.0)
    assert "buy_signal" not in " ".join(bins.columns).lower()


def test_feature_bin_outcome_summary_is_marked_as_posterior_only():
    features = pd.DataFrame(
        {
            "observation_id": ["a", "b", "c", "d"],
            "lower_shadow_ratio": [0.1, 0.2, 0.8, 0.9],
        }
    )
    annotations = pd.DataFrame(
        {
            "observation_id": ["a", "b", "c", "d"],
            "human_decision": ["REJECT", "REJECT", "ENTRY", "ENTRY"],
        }
    )
    outcomes = pd.DataFrame(
        {
            "observation_id": ["a", "b", "c", "d"],
            "fwd_ret_5": [-0.02, -0.01, 0.03, 0.04],
            "mfe_10": [0.01, 0.02, 0.08, 0.09],
            "mae_10": [-0.04, -0.03, -0.01, -0.01],
        }
    )

    summary = feature_bin_outcome_summary(
        features,
        annotations,
        outcomes,
        feature_cols=["lower_shadow_ratio"],
        outcome_cols=["fwd_ret_5", "mfe_10", "mae_10"],
        q=2,
    )

    assert set(summary["analysis_role"]) == {"posterior_outcome_analysis_only"}
    assert summary.loc[summary["outcome_col"] == "fwd_ret_5", "median"].notna().all()
    assert "model_input" not in " ".join(summary.columns).lower()


def test_outcome_time_series_diagnostics_handles_small_samples_and_volatility_clustering():
    outcomes = pd.DataFrame({"fwd_ret_5": [0.01, -0.02, 0.03]})

    diagnostics = outcome_time_series_diagnostics(outcomes, outcome_cols=["fwd_ret_5"], lags=5)

    row = diagnostics.iloc[0]
    assert row["outcome_col"] == "fwd_ret_5"
    assert row["sample_count"] == 3
    assert row["analysis_role"] == "posterior_time_series_diagnostic_only"
    assert "insufficient" in " ".join(row["warnings"])


def test_feature_drift_by_period_is_sorted_by_time():
    frame = pd.DataFrame(
        {
            "bar_time": ["2026-03-01", "2026-01-01", "2026-02-01", "2026-01-15"],
            "lower_shadow_ratio": [0.9, 0.1, 0.4, 0.3],
        }
    )

    drift = feature_drift_by_period(frame, "bar_time", ["lower_shadow_ratio"], period="M")

    assert drift["period"].tolist() == ["2026-01", "2026-02", "2026-03"]
    assert drift["mean"].tolist() == pytest.approx([0.2, 0.4, 0.9])
    assert drift["feature"].tolist() == ["lower_shadow_ratio"] * 3
    assert drift["drift_warning"].tolist() == [False, False, True]


def test_missing_values_are_ignored_and_small_samples_are_warned():
    frame = pd.DataFrame(
        {
            "human_decision": ["ENTRY", "ENTRY", "ENTRY"],
            "range_pct": [1.0, None, float("inf")],
        }
    )

    described = describe_feature_distribution(frame, "human_decision", ["range_pct"])
    row = described.iloc[0]

    assert row["n"] == 1
    assert row["missing_count"] == 1
    assert row["invalid_count"] == 2
    assert row["mean"] == 1.0
    assert row["sample_warning"] == "low_sample: 1 < 20"


def test_tail_concentration_flags_dominant_extreme_values():
    result = tail_concentration([1.0] * 30 + [100.0])

    assert result["top_5pct_abs_share"] > 0.75
    assert result["heavy_tail_warning"] is True


def test_diagnostics_do_not_emit_trade_signal_columns():
    frame = pd.DataFrame(
        {
            "human_decision": ["ENTRY", "REJECT"],
            "bar_time": ["2026-01-01", "2026-02-01"],
            "range_pct": [1.0, 2.0],
        }
    )

    outputs = [
        describe_feature_distribution(frame, "human_decision", ["range_pct"]),
        compare_entry_reject_distributions(frame, "human_decision", ["range_pct"]),
        feature_drift_by_period(frame, "bar_time", ["range_pct"]),
    ]

    for output in outputs:
        joined_columns = " ".join(output.columns).lower()
        assert "buy_signal" not in joined_columns
        assert "sell_signal" not in joined_columns
        assert "signal" not in joined_columns
