from __future__ import annotations

import pandas as pd

from time_series_analysis.regime import build_regime_features, summarize_regime_distribution
from time_series_analysis.returns import build_return_series


def _klines(n=90):
    return pd.DataFrame(
        {
            "bar_index": range(n),
            "open_time_bjt": pd.date_range("2026-01-01", periods=n, freq="min").astype(str),
            "open": [100 + i * 0.05 for i in range(n)],
            "high": [101 + i * 0.05 for i in range(n)],
            "low": [99 + i * 0.05 for i in range(n)],
            "close": [100 + i * 0.1 for i in range(n)],
            "volume": [10 + (i % 7) for i in range(n)],
        }
    )


def test_regime_empty_safe():
    out = build_regime_features(pd.DataFrame())
    assert out.empty
    assert "volatility_regime" in out.columns


def test_regime_features_and_summary():
    returns = build_return_series(_klines())
    regimes = build_regime_features(returns)
    assert "volatility_regime" in regimes.columns
    assert "trend_regime" in regimes.columns
    assert "trend_threshold" in regimes.columns
    assert "regime_label" in regimes.columns
    summary = summarize_regime_distribution(regimes)
    assert summary["sample_count"] == len(regimes)
    assert "volatility_regime" in summary


def test_regime_trend_threshold_can_classify_up_down_range():
    base = _klines(120)
    up = build_return_series(base.assign(close=[100 + i for i in range(120)]))
    up_regime = build_regime_features(up, window=10, vol_multiplier=0.1, min_abs_threshold=0.005)
    assert "uptrend" in set(up_regime["trend_regime"])

    down = build_return_series(base.assign(close=[220 - i for i in range(120)]))
    down_regime = build_regime_features(down, window=10, vol_multiplier=0.1, min_abs_threshold=0.005)
    assert "downtrend" in set(down_regime["trend_regime"])

    flat = build_return_series(base.assign(close=[100 for _ in range(120)]))
    flat_regime = build_regime_features(flat, window=10, vol_multiplier=0.1, min_abs_threshold=0.02)
    assert "range" in set(flat_regime["trend_regime"])
