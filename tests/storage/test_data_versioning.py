from __future__ import annotations

import pandas as pd

from quant_collector_app.research.data_versioning import (
    attach_data_version_metadata,
    build_data_version,
    compute_data_hash,
)
from quant_collector_app.research.entry_context_features import build_entry_context_features
from quant_collector_app.research.entry_observation_universe import generate_entry_observation_universe
from quant_collector_app.research.entry_outcome_labels import build_entry_outcome_labels


def _klines() -> pd.DataFrame:
    rows = []
    for index in range(30):
        close = 120.0 - index * 0.4
        rows.append(
            {
                "bar_index": index,
                "open_time": f"2026-01-01T00:{index:02d}:00Z",
                "open": close + 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100.0 + index,
            }
        )
    rows[25].update({"open": 107.0, "high": 112.0, "low": 100.0, "close": 111.0, "volume": 450.0})
    return pd.DataFrame(rows)


def _observations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_id": "obs_25",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "bar_index": 25,
                "bar_time": "2026-01-01T00:25:00Z",
                "decision_timing": "CURRENT_BAR_CLOSE",
            }
        ]
    )


def test_data_hash_is_stable_under_row_order_and_column_order_changes():
    klines = _klines()
    shuffled = klines[["close", "volume", "low", "open_time", "high", "open", "bar_index"]].sample(
        frac=1.0,
        random_state=9,
    )

    assert compute_data_hash(klines, symbol="BTCUSDT", interval="1m") == compute_data_hash(
        shuffled,
        symbol="BTCUSDT",
        interval="1m",
    )


def test_data_hash_changes_when_ohlcv_payload_changes():
    changed = _klines()
    changed.loc[10, "close"] += 0.01

    assert compute_data_hash(_klines(), symbol="BTCUSDT", interval="1m") != compute_data_hash(
        changed,
        symbol="BTCUSDT",
        interval="1m",
    )


def test_build_data_version_includes_hash_quality_and_anchor_metadata():
    quality_report = {"quality_status": "WARNING", "warnings": ["missing_bars"], "missing_bars": 1}

    version = build_data_version(
        _klines(),
        symbol="BTCUSDT",
        interval="1m",
        quality_report=quality_report,
        higher_timeframe_intervals=["5m", "15m"],
    )

    assert version["data_version"].startswith("kline_")
    assert version["data_hash"] == compute_data_hash(_klines(), symbol="BTCUSDT", interval="1m")
    assert version["row_count"] == 30
    assert version["quality_status"] == "WARNING"
    assert version["quality_warnings"] == ["missing_bars"]
    assert version["multi_timeframe_anchor_rules"][0]["higher_interval"] == "5m"


def test_attach_data_version_metadata_uses_attrs_not_table_columns():
    frame = pd.DataFrame({"observation_id": ["obs_1"]})
    version = build_data_version(_klines(), symbol="BTCUSDT", interval="1m")

    annotated = attach_data_version_metadata(frame, version)

    assert list(annotated.columns) == ["observation_id"]
    assert annotated.attrs["data_hash"] == version["data_hash"]
    assert annotated.attrs["data_version"] == version["data_version"]
    assert "data_quality_warnings" in annotated.attrs


def test_entry_research_outputs_record_data_version_in_attrs_without_new_columns():
    klines = _klines()
    observations = generate_entry_observation_universe(
        klines,
        symbol="BTCUSDT",
        interval="1m",
        min_prior_drop_pct=0.005,
        min_range_pct=0.02,
        volume_ratio_threshold=1.2,
        volume_zscore_threshold=0.5,
    )
    if observations.empty:
        observations = _observations()
    features = build_entry_context_features(klines, observations.head(1))
    outcomes = build_entry_outcome_labels(klines, observations.head(1), horizons=(3, 5, 10, 20))

    expected_hash = compute_data_hash(klines, symbol="BTCUSDT", interval="1m")
    for output in (observations, features, outcomes):
        assert output.attrs["data_hash"] == expected_hash
        assert output.attrs["data_version"].startswith("kline_")
        assert "data_hash" not in output.columns
