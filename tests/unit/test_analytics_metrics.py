from __future__ import annotations

import pytest

from analytics.metrics import annualization_factor, max_drawdown, profit_factor, sharpe_ratio


def test_annualization_factor_crypto_24_7():
    assert annualization_factor("1m") == 365 * 24 * 60
    assert annualization_factor("1h") == 365 * 24
    assert annualization_factor("1d") == 365


def test_max_drawdown_negative_pct():
    out = max_drawdown([100, 120, 90, 110])
    assert out["max_drawdown_pct"] == pytest.approx(-25.0)
    assert out["max_drawdown_start"] == 1
    assert out["max_drawdown_end"] == 2


def test_profit_factor_mixed_and_all_win():
    assert profit_factor([1, 2, -1]) == pytest.approx(3.0)
    assert profit_factor([1, 2]) is None


def test_trade_sharpe_safe():
    assert sharpe_ratio([1, -1, 2]) is not None
    assert sharpe_ratio([1]) is None
