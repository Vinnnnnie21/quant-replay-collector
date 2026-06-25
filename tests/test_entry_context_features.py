from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.entry_context_features import (
    FEATURE_COLUMNS,
    FeatureQualityReport,
    FeatureSpec,
    build_entry_context_features,
    build_feature_quality_report,
    validate_no_forbidden_context_fields,
)


def _klines(count: int = 30) -> pd.DataFrame:
    rows = []
    for index in range(count):
        close = 100.0 + index
        rows.append(
            {
                "bar_index": index,
                "open_time": f"2026-06-18T10:{index:02d}:00+08:00",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 100.0 + index,
            }
        )
    return pd.DataFrame(rows)


def _observations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_id": "obs_10",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": 10,
                "bar_time": "2026-06-18T10:10:00+08:00",
                "decision_timing": "CURRENT_BAR_CLOSE",
            },
            {
                "observation_id": "obs_20",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": 20,
                "bar_time": "2026-06-18T10:20:00+08:00",
                "decision_timing": "CURRENT_BAR_CLOSE",
            },
        ]
    )




def _next_confirmation_observation() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_id": "obs_confirm",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": 21,
                "bar_time": "2026-06-18T10:21:00+08:00",
                "setup_bar_index": 20,
                "decision_bar_index": 21,
                "setup_bar_time": "2026-06-18T10:20:00+08:00",
                "decision_bar_time": "2026-06-18T10:21:00+08:00",
                "decision_timing": "NEXT_BAR_CONFIRMATION",
            }
        ]
    )

def test_builds_one_feature_row_per_observation_with_prior_ret_5():
    result = build_entry_context_features(_klines(), _observations())

    assert list(result.columns) == FEATURE_COLUMNS
    assert result.attrs["feature_version"] == "entry_context_features_v1"
    assert result.attrs["feature_quality_report"]["row_count"] == 2
    assert result["observation_id"].tolist() == ["obs_10", "obs_20"]
    obs_10 = result[result["observation_id"] == "obs_10"].iloc[0]
    assert obs_10["symbol"] == "BTCUSDT"
    assert obs_10["bar_index"] == 10
    assert obs_10["feature_version"] == "entry_context_features_v1"
    assert math.isclose(obs_10["prior_ret_5"], 110.0 / 105.0 - 1.0)


def test_feature_spec_is_serializable_and_controls_version_metadata():
    spec = FeatureSpec(
        feature_version="entry_context_features_test_v2",
        lookback_windows=(5, 10, 20),
        decision_timing_policy="setup_bar_until_confirmation_allowed",
        allow_confirmation_bar=False,
        feature_cols=("prior_ret_5", "lower_shadow_ratio"),
    )

    restored = FeatureSpec.from_dict(spec.to_dict())
    result = build_entry_context_features(_klines(), _observations().head(1), feature_spec=restored)

    assert restored == spec
    assert result.iloc[0]["feature_version"] == "entry_context_features_test_v2"
    assert result.attrs["feature_spec"]["feature_cols"] == ["prior_ret_5", "lower_shadow_ratio"]


def test_feature_quality_report_detects_nan_constant_and_forbidden_fields():
    features = pd.DataFrame(
        {
            "observation_id": ["a", "b", "c"],
            "bar_index": [10, 11, 12],
            "prior_ret_5": [math.nan, 0.01, 0.02],
            "constant_feature": [1.0, 1.0, 1.0],
            "fwd_ret_5": [0.1, 0.2, 0.3],
        }
    )

    report = build_feature_quality_report(features)

    assert isinstance(report, FeatureQualityReport)
    assert report.row_count == 3
    assert report.feature_count == 3
    assert math.isclose(report.nan_ratio_by_col["prior_ret_5"], 1 / 3)
    assert report.constant_feature_cols == ["constant_feature"]
    assert report.forbidden_fields_detected == ["fwd_ret_5"]
    assert report.min_bar_index == 10
    assert report.max_bar_index == 12

    with pytest.raises(ValueError, match="forbidden context feature fields"):
        validate_no_forbidden_context_fields(features)


def test_insufficient_lookback_returns_nan_and_flag_without_crashing():
    observations = _observations().head(1).assign(bar_index=2, observation_id="obs_2")

    result = build_entry_context_features(_klines(), observations)

    row = result.iloc[0]
    assert math.isnan(row["prior_ret_5"])
    assert row["insufficient_history"] is True


def test_kline_shape_features_are_computed_from_current_bar():
    klines = _klines()
    klines.loc[20, ["open", "high", "low", "close"]] = [106.0, 110.0, 100.0, 108.0]
    observations = _observations().tail(1)

    result = build_entry_context_features(klines, observations)

    row = result.iloc[0]
    assert math.isclose(row["body_ratio"], 0.2)
    assert math.isclose(row["upper_shadow_ratio"], 0.2)
    assert math.isclose(row["lower_shadow_ratio"], 0.6)
    assert math.isclose(row["close_position_in_range"], 0.8)


def test_volume_zscore_20_uses_prior_twenty_bars_only():
    klines = _klines()
    klines.loc[:19, "volume"] = np.arange(100.0, 120.0)
    klines.loc[20, "volume"] = 130.0
    observations = _observations().tail(1)

    result = build_entry_context_features(klines, observations)

    prior = np.arange(100.0, 120.0)
    expected = (130.0 - float(prior.mean())) / float(prior.std(ddof=0))
    assert math.isclose(result.iloc[0]["volume_zscore_20"], expected)


def test_feature_columns_exclude_future_outcomes_and_signal_names():
    forbidden = ("fwd_", "future", "mfe", "mae", "hit_tp", "hit_sl", "pnl", "profit", "win", "buy_signal")

    assert not any(any(token in column.lower() for token in forbidden) for column in FEATURE_COLUMNS)


def test_features_do_not_read_bars_after_observation():
    klines = _klines(35)
    changed_future = klines.copy()
    changed_future.loc[21:, ["open", "high", "low", "close", "volume"]] = [9999.0, 9999.0, 9999.0, 9999.0, 9999.0]
    observations = _observations().tail(1)

    base = build_entry_context_features(klines, observations)
    mutated = build_entry_context_features(changed_future, observations)

    assert base.equals(mutated)


def test_shuffled_input_is_sorted_by_bar_index_before_feature_calculation():
    ordered = build_entry_context_features(_klines(), _observations().tail(1))
    shuffled = build_entry_context_features(_klines().sample(frac=1.0, random_state=7), _observations().tail(1))

    assert shuffled.equals(ordered)


def test_next_bar_confirmation_observation_is_explicitly_marked():
    observations = _observations().tail(1).assign(decision_timing="NEXT_BAR_CONFIRMATION")

    result = build_entry_context_features(_klines(), observations)

    assert result.iloc[0]["decision_timing"] == "NEXT_BAR_CONFIRMATION"
    assert result.iloc[0]["uses_next_bar_confirmation"] is True


def test_current_bar_close_feature_cutoff_is_decision_bar():
    observations = _observations().tail(1).assign(setup_bar_index=20, decision_bar_index=20)

    result = build_entry_context_features(_klines(), observations)

    row = result.iloc[0]
    assert row["setup_bar_index"] == 20
    assert row["decision_bar_index"] == 20
    assert row["feature_cutoff_bar_index"] == 20
    assert row["feature_timing_policy"] == "current_bar_close"
    assert result.attrs["feature_quality_report"]["feature_timing_policy"] == "current_bar_close"


def test_next_bar_confirmation_without_confirmation_bar_uses_setup_cutoff_only():
    klines = _klines(30)
    klines.loc[20, ["open", "high", "low", "close", "volume"]] = [106.0, 110.0, 100.0, 108.0, 130.0]
    klines.loc[21, ["open", "high", "low", "close", "volume"]] = [500.0, 505.0, 499.0, 504.0, 9999.0]
    mutated_confirmation = klines.copy()
    mutated_confirmation.loc[21, ["open", "high", "low", "close", "volume"]] = [900.0, 950.0, 850.0, 940.0, 1.0]
    observations = _next_confirmation_observation()
    spec = FeatureSpec(allow_confirmation_bar=False)

    base = build_entry_context_features(klines, observations, feature_spec=spec)
    mutated = build_entry_context_features(mutated_confirmation, observations, feature_spec=spec)

    row = base.iloc[0]
    assert row["feature_cutoff_bar_index"] == 20
    assert row["feature_timing_policy"] == "setup_bar_only"
    assert math.isclose(row["lower_shadow_ratio"], 0.6)
    assert base[["prior_ret_5", "lower_shadow_ratio", "volume_zscore_20"]].equals(
        mutated[["prior_ret_5", "lower_shadow_ratio", "volume_zscore_20"]]
    )


def test_next_bar_confirmation_with_confirmation_bar_uses_decision_cutoff():
    klines = _klines(30)
    klines.loc[20, ["open", "high", "low", "close", "volume"]] = [106.0, 110.0, 100.0, 108.0, 130.0]
    klines.loc[21, ["open", "high", "low", "close", "volume"]] = [500.0, 505.0, 499.0, 504.0, 9999.0]
    observations = _next_confirmation_observation()
    spec = FeatureSpec(allow_confirmation_bar=True)

    result = build_entry_context_features(klines, observations, feature_spec=spec)

    row = result.iloc[0]
    assert row["feature_cutoff_bar_index"] == 21
    assert row["feature_timing_policy"] == "confirmation_bar_included"
    assert math.isclose(row["lower_shadow_ratio"], (500.0 - 499.0) / (505.0 - 499.0))
    assert row["volume_zscore_20"] > 100.0


def test_feature_cutoff_after_decision_bar_is_rejected():
    observations = _next_confirmation_observation().assign(feature_cutoff_bar_index=22)

    with pytest.raises(ValueError, match="feature_cutoff_bar_index"):
        build_entry_context_features(_klines(30), observations)