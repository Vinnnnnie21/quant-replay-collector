from __future__ import annotations

import math

import pandas as pd
import pytest

from backtesting.features import build_ohlcv_feature_frame


def _ohlcv_frame() -> pd.DataFrame:
    close = [100.0 + index for index in range(60)]
    return pd.DataFrame(
        {
            "bar_index": range(60),
            "open_time_bjt": pd.date_range(
                "2026-01-01",
                periods=60,
                freq="min",
                tz="Asia/Shanghai",
            ),
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [float(index + 1) for index in range(60)],
        }
    )


def test_relative_volume_features_use_only_prior_ohlcv_history():
    out = build_ohlcv_feature_frame(
        _ohlcv_frame(),
        required_features=[
            "volume_ratio_20",
            "volume_ratio_50",
            "volume_zscore_20",
            "volume_percentile_50",
        ],
    )

    assert math.isnan(out.loc[19, "volume_ratio_20"])
    assert out.loc[20, "volume_ratio_20"] == pytest.approx(21.0 / 10.5)
    assert out.loc[50, "volume_ratio_50"] == pytest.approx(51.0 / 25.5)
    assert out.loc[20, "volume_zscore_20"] == pytest.approx(
        (21.0 - 10.5) / pd.Series(range(1, 21), dtype=float).std(ddof=0)
    )
    assert out.loc[50, "volume_percentile_50"] == pytest.approx(1.0)
