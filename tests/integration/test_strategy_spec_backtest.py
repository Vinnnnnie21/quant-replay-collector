from __future__ import annotations

import pandas as pd

from backtesting.strategy_spec import StrategySpec
from backtesting.strategy_spec_adapter import run_strategy_spec_backtest
from backtesting.types import BacktestConfig


def _market_frame(*, second_spike: bool = False) -> pd.DataFrame:
    close = [100.0 + index * 0.1 for index in range(30)]
    volume = [100.0] * 30
    volume[20] = 300.0
    if second_spike:
        volume[23] = 500.0
    return pd.DataFrame(
        {
            "bar_index": range(30),
            "open_time_bjt": pd.date_range(
                "2026-01-01",
                periods=30,
                freq="min",
                tz="Asia/Shanghai",
            ),
            "open": close,
            "high": [value + 0.2 for value in close],
            "low": [value - 0.2 for value in close],
            "close": close,
            "volume": volume,
        }
    )


def _strategy_spec() -> StrategySpec:
    return StrategySpec.from_dict(
        {
            "schema_version": "strategy_spec_v1",
            "provenance": {
                "source": "decision_research",
                "setup_version_id": "setup-version-1",
                "research_snapshot_id": "snapshot-abc",
                "decision_mode": "entry_research",
                "formula_version": "decision-research-v1",
                "feature_version": "features-v1",
                "application_version": "1.6.0",
                "random_seed": 42,
                "maturity": "EXPLORATORY_HYPOTHESIS",
                "warnings": [],
            },
            "market": {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "data_start_utc_ms": 1_700_000_000_000,
                "data_end_utc_ms": 1_700_086_400_000,
            },
            "entry": {
                "rule": {
                    "all": [
                        {"feature": "volume_ratio_20", "op": ">=", "value": 2.5}
                    ]
                }
            },
            "exit": {
                "mode": "tp_sl_timeout",
                "take_profit_pct": 1.0,
                "stop_loss_pct": 1.0,
                "max_holding_bars": 3,
            },
            "position": {
                "direction": "long_only",
                "allow_overlap_positions": False,
                "cooldown_bars": 0,
                "notional_per_trade": 1000.0,
                "fee_bps": 0.0,
                "slippage_bps": 0.0,
            },
        }
    )


def test_strategy_spec_backtest_computes_registered_features_and_runs_rule():
    result = run_strategy_spec_backtest(
        _strategy_spec(),
        _market_frame(),
        BacktestConfig(initial_equity=10_000.0),
        symbol="BTCUSDT",
        interval="1m",
    )

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["entry_signal_bar_index"] == 20
    assert trade["entry_bar_index"] == 21
    assert trade["exit_reason"] == "max_bars_hold"
    assert result.strategy_name == "StrategySpec v1"
    assert result.random_baseline_summary["status"] == "ready"
    assert result.random_baseline_summary["target_trade_count"] == len(result.trades)
    assert not result.random_baseline_equity_curve.empty


def test_strategy_spec_backtest_obeys_cooldown_after_closed_trade():
    spec = StrategySpec.from_dict(
        {
            **_strategy_spec().to_dict(),
            "exit": {
                "mode": "tp_sl_timeout",
                "take_profit_pct": 1.0,
                "stop_loss_pct": 1.0,
                "max_holding_bars": 2,
            },
            "position": {
                **_strategy_spec().to_dict()["position"],
                "cooldown_bars": 3,
            },
        }
    )

    result = run_strategy_spec_backtest(
        spec,
        _market_frame(second_spike=True),
        BacktestConfig(initial_equity=10_000.0),
        symbol="BTCUSDT",
        interval="1m",
    )

    assert result.trades["entry_signal_bar_index"].tolist() == [20]
