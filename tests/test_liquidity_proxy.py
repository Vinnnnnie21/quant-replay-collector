from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from time_series_analysis.liquidity_proxy import compute_liquidity_proxy, summarize_liquidity_proxy


def _stable_klines(n: int = 30) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [10.0] * n,
        }
    )


def _with_last_bar(*, high: float, low: float, volume: float) -> pd.DataFrame:
    frame = _stable_klines()
    frame.loc[len(frame)] = {
        "open": 100.0,
        "high": high,
        "low": low,
        "close": 100.0,
        "volume": volume,
    }
    return frame


def test_compute_liquidity_proxy_adds_required_output_fields():
    result = compute_liquidity_proxy(_stable_klines(), window=5, state_window=10)

    assert {
        "log_return",
        "range_log",
        "quote_volume",
        "range_vol_base",
        "volume_base",
        "vol_ratio",
        "volume_ratio",
        "impact_score",
        "impact_median",
        "impact_mad",
        "impact_z",
        "liquidity_state",
    }.issubset(result.columns)


def test_compute_liquidity_proxy_uses_log_ranges_and_rolling_median_baselines():
    frame = pd.DataFrame(
        {
            "open": [100.0, 102.0],
            "high": [101.0, 104.0],
            "low": [99.0, 96.0],
            "close": [100.0, 102.0],
            "volume": [10.0, 20.0],
            "quote_volume": [1000.0, 2000.0],
        }
    )

    result = compute_liquidity_proxy(frame, window=2, state_window=2)
    expected_range = np.log(104.0 / 96.0)
    expected_base = np.median([np.log(101.0 / 99.0), expected_range])
    expected_vol_ratio = expected_range / (expected_base + 1e-12)
    expected_volume_ratio = 2000.0 / (1500.0 + 1e-12)

    assert np.isclose(result.loc[1, "log_return"], np.log(102.0 / 100.0))
    assert np.isclose(result.loc[1, "range_log"], expected_range)
    assert np.isclose(result.loc[1, "range_vol_base"], expected_base)
    assert np.isclose(result.loc[1, "volume_base"], 1500.0)
    assert np.isclose(result.loc[1, "vol_ratio"], expected_vol_ratio)
    assert np.isclose(result.loc[1, "volume_ratio"], expected_volume_ratio)
    assert np.isclose(result.loc[1, "impact_score"], expected_vol_ratio / (expected_volume_ratio + 1e-12))


def test_compute_liquidity_proxy_prefers_supplied_quote_volume():
    frame = _stable_klines()
    frame["quote_volume"] = [123.0] * len(frame)

    result = compute_liquidity_proxy(frame, window=5, state_window=10)

    assert result["quote_volume"].tolist() == frame["quote_volume"].tolist()
    assert result["quote_volume"].iloc[-1] != frame["volume"].iloc[-1] * frame["close"].iloc[-1]


def test_compute_liquidity_proxy_does_not_modify_source_frame():
    frame = _stable_klines()
    original_columns = list(frame.columns)

    compute_liquidity_proxy(frame, window=5, state_window=10)

    assert list(frame.columns) == original_columns


def test_low_volume_high_impact_bar_is_low_liquidity_shock():
    result = compute_liquidity_proxy(
        _with_last_bar(high=125.0, low=75.0, volume=1.0),
        window=5,
        state_window=10,
    )

    assert result.iloc[-1]["impact_z"] > 2
    assert result.iloc[-1]["volume_ratio"] < 0.8
    assert result.iloc[-1]["liquidity_state"] == "LOW_LIQUIDITY_SHOCK"


def test_high_volume_high_impact_bar_is_event_repricing():
    result = compute_liquidity_proxy(
        _with_last_bar(high=200.0, low=50.0, volume=20.0),
        window=5,
        state_window=10,
    )

    assert result.iloc[-1]["impact_z"] > 2
    assert result.iloc[-1]["volume_ratio"] >= 1.5
    assert result.iloc[-1]["liquidity_state"] == "EVENT_REPRICING"


def test_high_volume_low_impact_bar_is_absorption():
    result = compute_liquidity_proxy(
        _with_last_bar(high=100.1, low=99.9, volume=20.0),
        window=5,
        state_window=10,
    )

    assert result.iloc[-1]["impact_z"] < -1
    assert result.iloc[-1]["volume_ratio"] >= 1.5
    assert result.iloc[-1]["liquidity_state"] == "ABSORPTION"


def test_low_volume_low_range_bar_is_quiet_thin_market():
    result = compute_liquidity_proxy(
        _with_last_bar(high=100.02, low=99.98, volume=1.0),
        window=5,
        state_window=10,
    )

    assert result.iloc[-1]["volume_ratio"] < 0.5
    assert result.iloc[-1]["vol_ratio"] < 0.8
    assert result.iloc[-1]["liquidity_state"] == "QUIET_THIN_MARKET"


@pytest.mark.parametrize(
    ("column", "value"),
    [("high", 0.0), ("high", -1.0), ("low", 0.0), ("low", -1.0), ("close", 0.0), ("close", -1.0)],
)
def test_invalid_price_does_not_produce_a_liquidity_state(column: str, value: float):
    frame = _stable_klines()
    frame["quote_volume"] = frame["volume"] * frame["close"]
    frame.loc[len(frame) - 1, column] = value

    result = compute_liquidity_proxy(frame, window=5, state_window=10)

    if column == "close":
        assert pd.isna(result.iloc[-1]["log_return"])
    assert pd.isna(result.iloc[-1]["impact_score"])
    assert result.iloc[-1]["liquidity_state"] == "UNKNOWN"


def test_nonpositive_quote_volume_is_safe_and_never_produces_infinity():
    frame = _stable_klines()
    frame["quote_volume"] = frame["volume"] * frame["close"]
    frame.loc[len(frame) - 2, "quote_volume"] = 0.0
    frame.loc[len(frame) - 1, "quote_volume"] = -1.0

    result = compute_liquidity_proxy(frame, window=5, state_window=10)
    numeric = result.select_dtypes(include="number")

    assert result.iloc[-1]["liquidity_state"] == "UNKNOWN"
    assert not np.isinf(numeric.to_numpy(dtype=float)).any()


def test_numeric_string_ohlcv_values_are_accepted():
    frame = _stable_klines().astype(str)

    result = compute_liquidity_proxy(frame, window=5, state_window=10)

    assert result["range_log"].notna().any()
    assert result["quote_volume"].iloc[-1] == 1000.0


def test_insufficient_rolling_history_is_unknown():
    result = compute_liquidity_proxy(_stable_klines(8), window=5, state_window=10)

    assert set(result["liquidity_state"]) == {"UNKNOWN"}


def test_summarize_liquidity_proxy_reports_valid_states_and_scores():
    result = compute_liquidity_proxy(
        _with_last_bar(high=125.0, low=75.0, volume=1.0),
        window=5,
        state_window=10,
    )

    summary = summarize_liquidity_proxy(result)

    assert summary["total_rows"] == len(result)
    assert summary["valid_rows"] == int((result["liquidity_state"] != "UNKNOWN").sum())
    assert summary["state_counts"]["LOW_LIQUIDITY_SHOCK"] == 1
    assert summary["low_liquidity_shock_count"] == 1
    assert summary["event_repricing_count"] == 0
    assert summary["absorption_count"] == 0
    assert summary["mean_impact_score"] is not None
    assert summary["median_impact_score"] is not None


def test_liquidity_proxy_public_functions_are_exported_by_package():
    from time_series_analysis import classify_liquidity_state, compute_liquidity_proxy as public_compute
    from time_series_analysis import summarize_liquidity_proxy as public_summarize

    result = public_compute(_stable_klines(), window=5, state_window=10)

    assert callable(classify_liquidity_state)
    assert public_summarize(result)["total_rows"] == len(result)
