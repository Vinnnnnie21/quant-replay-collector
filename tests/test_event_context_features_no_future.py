from __future__ import annotations

import pandas as pd
import pytest

from research.context_features import (
    compute_context_features_for_sample,
    validate_context_feature_name,
)
from storage import StorageManager


def _klines(total: int = 80) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_index": range(total),
            "open_time_bjt": pd.date_range("2026-05-01", periods=total, freq="min").astype(str),
            "open": [100.0 + index * 0.1 for index in range(total)],
            "high": [100.6 + index * 0.1 for index in range(total)],
            "low": [99.6 + index * 0.1 for index in range(total)],
            "close": [100.2 + index * 0.1 for index in range(total)],
            "volume": [1000.0 + index for index in range(total)],
        }
    )


def _sample(bar_index: int = 55) -> dict:
    return {
        "sample_id": "obs_1",
        "session_id": "session_1",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "bar_index": bar_index,
        "created_at": "2026-05-27T08:00:00+00:00",
    }


def test_context_features_ignore_future_changes_and_persist_idempotently(tmp_path):
    original = _klines()
    changed_future = original.copy()
    changed_future.loc[changed_future["bar_index"] > 55, ["high", "low", "close", "volume"]] = [
        99999.0,
        1.0,
        50000.0,
        9_000_000.0,
    ]

    first = compute_context_features_for_sample(original, _sample(), 20, "context_v1")
    second = compute_context_features_for_sample(changed_future, _sample(), 20, "context_v1")
    pd.testing.assert_frame_equal(first, second)

    storage = StorageManager(tmp_path / "context.db")
    storage.save_event_context_features(first.to_dict("records"))
    storage.save_event_context_features(first.to_dict("records"))
    stored = storage.list_event_context_features(sample_id="obs_1", feature_version="context_v1")

    assert stored
    assert len(stored) == len(first)
    assert {row["lookback_bars"] for row in stored} == {20}


@pytest.mark.parametrize(
    "feature_name",
    [
        "fwd_ret",
        "post_range",
        "future_high",
        "mfe",
        "mae",
        "hit_tp",
        "hit_sl",
        "pnl_net",
        "exit_price",
        "label_value",
    ],
)
def test_context_feature_names_reject_outcome_or_future_tokens(feature_name):
    with pytest.raises(ValueError):
        validate_context_feature_name(feature_name)


def test_context_features_report_insufficient_history_without_invented_metrics():
    result = compute_context_features_for_sample(_klines(12), _sample(11), 20, "context_v1")
    values = dict(zip(result["feature_name"], result["feature_value"]))

    assert values["available_bars"] == 12
    assert values["insufficient_history"] == 1
    assert "pre_log_ret" not in values
