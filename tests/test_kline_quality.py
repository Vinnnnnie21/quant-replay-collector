from __future__ import annotations

import pandas as pd

from quant_collector_app.research.kline_quality import (
    attach_candle_ids,
    build_candle_id,
    build_kline_quality_report,
    describe_multi_timeframe_anchor_rule,
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
