from __future__ import annotations

import pandas as pd

from backtesting.optimization import grid_search, time_series_split, walk_forward_grid_search
from backtesting.strategies import MovingAverageCrossStrategy
from backtesting.types import BacktestConfig


def _df(n=120):
    close = [100 + i * 0.2 for i in range(n)]
    return pd.DataFrame(
        {
            "bar_index": range(n),
            "open_time_bjt": pd.date_range("2026-01-01", periods=n, freq="min", tz="Asia/Shanghai"),
            "open": close,
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "volume": [100.0] * n,
        }
    )


def test_time_series_split_order():
    split = time_series_split(_df(100))
    assert split["train"]["bar_index"].max() < split["valid"]["bar_index"].min()
    assert split["valid"]["bar_index"].max() < split["test"]["bar_index"].min()


def test_grid_search_outputs_results():
    out = grid_search(
        _df(),
        MovingAverageCrossStrategy,
        {"fast_window": [3, 5], "slow_window": [8]},
        BacktestConfig(),
        "BTCUSDT",
        "1m",
    )
    assert len(out) == 2
    assert "params_json" in out.columns
    assert "sharpe" in out.columns


def test_walk_forward_test_not_used_for_selection():
    out = walk_forward_grid_search(
        _df(),
        MovingAverageCrossStrategy,
        {"fast_window": [3, 5], "slow_window": [8, 13]},
        BacktestConfig(),
        "BTCUSDT",
        "1m",
    )
    assert "selected_params" in out
    assert out["test_result"]["split"] == "test"
    assert "train_results" in out and "valid_results" in out


def test_param_limit_and_missing_objective_safe():
    out = walk_forward_grid_search(
        _df(),
        MovingAverageCrossStrategy,
        {"fast_window": list(range(30)), "slow_window": list(range(40, 60))},
        BacktestConfig(),
        "BTCUSDT",
        "1m",
        objective="missing",
        max_combinations=10,
    )
    assert len(out["train_results"]) == 10
    assert out["selected_params"] is not None
