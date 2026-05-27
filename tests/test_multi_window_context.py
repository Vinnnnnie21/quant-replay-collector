from __future__ import annotations

import pandas as pd
import pytest

from research.context_features import compute_context_features_for_sample, compute_multi_window_context_features


def _klines(total: int = 130) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_index": range(total),
            "high": [101.0 + index * 0.05 for index in range(total)],
            "low": [99.0 + index * 0.05 for index in range(total)],
            "close": [100.0 + index * 0.05 for index in range(total)],
            "volume": [500.0 + index for index in range(total)],
        }
    )


def _sample(bar_index: int = 110) -> dict:
    return {
        "sample_id": "obs_windows",
        "session_id": "session_1",
        "symbol": "ETHUSDT",
        "interval": "5m",
        "bar_index": bar_index,
        "created_at": "2026-05-27T08:00:00+00:00",
    }


def test_multi_window_context_outputs_pre_20_pre_50_and_pre_100_with_version():
    result = compute_multi_window_context_features(_klines(), _sample(), feature_version="context_v1.5")

    assert set(result["lookback_bars"]) == {20, 50, 100}
    assert set(result["feature_version"]) == {"context_v1.5"}
    status = result[result["feature_name"] == "insufficient_history"]
    assert set(status["feature_value"]) == {0.0}


def test_multi_window_context_marks_only_unavailable_history():
    result = compute_multi_window_context_features(_klines(60), _sample(55), feature_version="context_v1")
    status = result[result["feature_name"] == "insufficient_history"].set_index("lookback_bars")

    assert status.loc[20, "feature_value"] == 0
    assert status.loc[50, "feature_value"] == 0
    assert status.loc[100, "feature_value"] == 1


def test_context_rejects_unapproved_lookback_bars():
    with pytest.raises(ValueError):
        compute_context_features_for_sample(_klines(), _sample(), 30, "context_v1")
