from __future__ import annotations

import pandas as pd

from backtesting.random_baseline import RandomBaselineConfig, run_random_entry_baseline
from backtesting.types import BacktestConfig


def _market_frame(rows: int = 80) -> pd.DataFrame:
    close = [100.0 + i * 0.1 for i in range(rows)]
    return pd.DataFrame(
        {
            "bar_index": range(rows),
            "open_time_bjt": pd.date_range("2026-01-01", periods=rows, freq="min", tz="Asia/Shanghai"),
            "open": close,
            "high": [value + 0.8 for value in close],
            "low": [value - 0.8 for value in close],
            "close": close,
            "volume": [100.0 + i for i in range(rows)],
        }
    )


def _strategy_trades(entry_bars: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry_bar_index": entry_bars,
            "exit_bar_index": [entry + 2 for entry in entry_bars],
            "side": ["LONG"] * len(entry_bars),
        }
    )


def test_random_baseline_defaults_to_100_runs_and_is_seed_reproducible():
    config = BacktestConfig(max_bars_hold=3, cooldown_bars=1, stop_loss_pct=2.0, take_profit_pct=2.0)
    trades = _strategy_trades([10, 30, 50])

    first = run_random_entry_baseline(
        _market_frame(),
        trades,
        config,
        symbol="BTCUSDT",
        interval="1m",
        random_config=RandomBaselineConfig(random_seed=12345),
    )
    second = run_random_entry_baseline(
        _market_frame(),
        trades,
        config,
        symbol="BTCUSDT",
        interval="1m",
        random_config=RandomBaselineConfig(random_seed=12345),
    )

    assert first.status == "ready"
    assert first.summary["simulation_count"] == 100
    assert first.summary["completed_runs"] == 100
    assert first.summary["random_seed"] == 12345
    assert first.summary["target_trade_count"] == len(trades)
    assert all(len(run["entry_bar_indices"]) == len(trades) for run in first.summary["runs"])
    assert first.summary["runs"] == second.summary["runs"]
    assert first.median_equity_curve["equity"].round(10).tolist() == second.median_equity_curve["equity"].round(10).tolist()


def test_random_baseline_avoids_strategy_entries_and_enforces_spacing():
    config = BacktestConfig(max_bars_hold=4, cooldown_bars=2, stop_loss_pct=50.0, take_profit_pct=50.0)
    strategy_entries = {12, 24, 36}

    result = run_random_entry_baseline(
        _market_frame(),
        _strategy_trades(sorted(strategy_entries)),
        config,
        symbol="BTCUSDT",
        interval="1m",
        random_config=RandomBaselineConfig(random_seed=7, simulation_count=12),
    )

    assert result.status == "ready"
    minimum_spacing = config.max_bars_hold + config.cooldown_bars
    for run in result.summary["runs"]:
        entries = run["entry_bar_indices"]
        assert not strategy_entries.intersection(entries)
        assert all(right - left >= minimum_spacing for left, right in zip(entries, entries[1:]))


def test_random_baseline_skips_when_no_valid_random_schedule_exists():
    result = run_random_entry_baseline(
        _market_frame(rows=8),
        _strategy_trades([2, 4, 6]),
        BacktestConfig(max_bars_hold=4, cooldown_bars=3),
        symbol="BTCUSDT",
        interval="1m",
        random_config=RandomBaselineConfig(random_seed=3, simulation_count=5),
    )

    assert result.status == "skipped"
    assert result.median_equity_curve.empty
    assert result.summary["completed_runs"] == 0
    assert result.warnings
