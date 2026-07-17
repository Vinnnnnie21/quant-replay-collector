from __future__ import annotations

import pandas as pd
import pytest

from quant_collector_app.research.kline_quality import (
    attach_candle_ids,
    build_candle_id,
    build_kline_quality_report,
    describe_multi_timeframe_anchor_rule,
    validate_research_klines,
)


def _problem_klines() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"open_time": "2026-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10},
            {"open_time": "2026-01-01T00:01:00Z", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 11},
            {"open_time": "2026-01-01T00:04:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 12},
            {"open_time": "2026-01-01T00:03:00Z", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 13},
            {"open_time": "2026-01-01T00:03:00Z", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 14},
            {"open_time": "2026-01-01T00:05:00Z", "open": 105, "high": 104, "low": 103, "close": 105, "volume": 15},
            {"open_time": "2026-01-01T00:06:00Z", "open": 105, "high": 106, "low": 104, "close": 105, "volume": -1},
            {"open_time": "2026-01-01T00:07:00Z", "open": 105, "high": 106, "low": 104, "close": 105, "volume": None},
        ]
    )


def _valid_klines() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"open_time": "2026-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10},
            {"open_time": "2026-01-01T00:01:00Z", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 11},
            {"open_time": "2026-01-01T00:02:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 12},
        ]
    )


def test_research_quality_gate_rejects_out_of_order_klines():
    unordered = _valid_klines().iloc[[1, 0, 2]].reset_index(drop=True)

    with pytest.raises(ValueError, match="out-of-order.*reload.*quality report"):
        validate_research_klines(unordered, context="strategy research")


def test_research_quality_gate_rejects_duplicate_klines():
    duplicated = pd.concat([_valid_klines().iloc[:2], _valid_klines().iloc[[1]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate.*reload.*quality report"):
        validate_research_klines(duplicated, context="statistical analysis")


def test_research_quality_gate_rejects_missing_critical_price_column():
    missing_close = _valid_klines().drop(columns=["close"])

    with pytest.raises(ValueError, match="missing critical price columns: close.*reload.*quality report"):
        validate_research_klines(missing_close, context="backtest")


def test_research_quality_gate_rejects_nan_critical_price():
    missing_price = _valid_klines()
    missing_price.loc[1, "close"] = float("nan")

    with pytest.raises(ValueError, match="missing critical price values.*close.*reload.*quality report"):
        validate_research_klines(missing_price, context="backtest")


def test_research_quality_gate_rejects_infinite_numeric_value():
    non_finite = _valid_klines()
    non_finite["volume"] = non_finite["volume"].astype(float)
    non_finite.loc[1, "volume"] = float("inf")

    with pytest.raises(ValueError, match="non-finite numeric values.*volume.*reload.*quality report"):
        validate_research_klines(non_finite, context="statistical analysis")


def test_research_quality_gate_rejects_missing_timestamp():
    missing_time = _valid_klines()
    missing_time.loc[1, "open_time"] = None

    with pytest.raises(ValueError, match="missing or invalid K-line timestamps.*reload.*quality report"):
        validate_research_klines(missing_time, context="strategy research")


def test_research_quality_gate_rejects_positive_infinite_numeric_timestamp():
    invalid_time = _valid_klines().assign(open_time_utc_ms=[1.0, 2.0, float("inf")])
    original = invalid_time.copy(deep=True)

    with pytest.raises(
        ValueError,
        match="strategy research.*invalid/non-finite K-line timestamps.*reload.*quality report",
    ):
        validate_research_klines(invalid_time, context="strategy research")
    pd.testing.assert_frame_equal(invalid_time, original)


@pytest.mark.parametrize("invalid_value", [float("-inf"), float("nan")])
def test_research_quality_gate_rejects_other_non_finite_numeric_timestamps(invalid_value):
    invalid_time = _valid_klines().assign(open_time_utc_ms=[1.0, 2.0, invalid_value])

    with pytest.raises(ValueError, match="invalid/non-finite K-line timestamps.*quality report"):
        validate_research_klines(invalid_time, context="backtest")


def test_research_quality_gate_rejects_unparseable_string_timestamp():
    invalid_time = _valid_klines()
    invalid_time.loc[1, "open_time"] = "not-a-timestamp"

    with pytest.raises(ValueError, match="invalid/non-finite K-line timestamps.*quality report"):
        validate_research_klines(invalid_time, context="statistical analysis")


def test_research_quality_gate_accepts_finite_utc_millisecond_timestamps():
    valid = _valid_klines().assign(open_time_utc_ms=[1_767_225_600_000, 1_767_225_660_000, 1_767_225_720_000])

    validate_research_klines(valid, context="backtest")


def test_quality_report_marks_infinite_numeric_timestamp_invalid():
    invalid_time = _valid_klines().assign(open_time_utc_ms=[1.0, 2.0, float("inf")])

    report = build_kline_quality_report(invalid_time, symbol="BTCUSDT", interval="1m")

    assert report["invalid_rows"] > 0
    assert report["missing_time_rows"] > 0
    assert report["quality_status"] == "FAIL"
    assert "missing_time" in report["warnings"]


def test_research_quality_gate_rejects_out_of_order_bar_index():
    unordered = _valid_klines().assign(bar_index=[0, 2, 1])

    with pytest.raises(ValueError, match="out-of-order bar_index.*reload.*quality report"):
        validate_research_klines(unordered, context="backtest")


def test_candle_id_is_stable_from_symbol_interval_open_time():
    first = build_candle_id("BTCUSDT", "1m", "2026-01-01T00:00:00Z")
    second = build_candle_id("btcusdt", "1m", "2026-01-01T00:00:00Z")

    assert first == second
    assert len(first) == 32


def test_attach_candle_ids_copies_frame_without_overwriting_raw_data():
    raw = _problem_klines()

    with_ids = attach_candle_ids(raw, symbol="BTCUSDT", interval="1m")

    assert "candle_id" not in raw.columns
    assert "candle_id" in with_ids.columns
    assert with_ids.loc[3, "candle_id"] == with_ids.loc[4, "candle_id"]
    assert with_ids.loc[0, "open"] == raw.loc[0, "open"]


def test_quality_report_detects_gaps_duplicates_disorder_and_invalid_rows():
    report = build_kline_quality_report(_problem_klines(), symbol="BTCUSDT", interval="1m")

    assert report["quality_status"] == "FAIL"
    assert report["row_count"] == 8
    assert report["duplicate_bars"] == 1
    assert report["missing_bars"] == 1
    assert report["out_of_order_bars"] == 1
    assert report["invalid_ohlc_rows"] == 1
    assert report["negative_volume_rows"] == 1
    assert report["missing_volume_rows"] == 1
    assert report["first_open_time"] == "2026-01-01T00:00:00+00:00"
    assert report["last_open_time"] == "2026-01-01T00:07:00+00:00"
    assert {"missing_bars", "duplicate_bars", "out_of_order", "invalid_ohlc", "negative_volume", "missing_volume"} <= set(
        report["warnings"]
    )


def test_quality_report_handles_missing_volume_column_without_crashing():
    frame = _problem_klines().drop(columns=["volume"])

    report = build_kline_quality_report(frame, symbol="BTCUSDT", interval="1m")

    assert report["quality_status"] == "FAIL"
    assert report["missing_required_columns"] == ["volume"]
    assert report["missing_volume_rows"] == len(frame)


def test_multi_timeframe_anchor_rule_is_explicit_and_non_trading():
    rule = describe_multi_timeframe_anchor_rule(primary_interval="1m", higher_interval="5m")

    assert rule["primary_interval"] == "1m"
    assert rule["higher_interval"] == "5m"
    assert rule["position_anchor"] == "primary_open_time_containing_higher_timeframe_bar"
    assert rule["feature_anchor"] == "latest_completed_higher_timeframe_bar_at_or_before_primary_open_time"
    assert rule["no_future_higher_timeframe_bar"] is True
    assert "buy_signal" not in " ".join(str(value) for value in rule.values()).lower()
