from __future__ import annotations

import pandas as pd
from pathlib import Path
import os
import subprocess
import sys

import pytest

from backtesting.date_range import BacktestDateRange
from backtesting.parameter_schema import StrategyRuleParams
from backtesting.types import BacktestConfig
from services.backtest_service import BacktestService


def _market_df() -> pd.DataFrame:
    rows = []
    for idx in range(30):
        close = 110.0 - idx * 0.5 if idx <= 20 else 102.0 + (idx - 21) * 0.3
        rows.append(
            {
                "bar_index": idx,
                "open_time_bjt": pd.Timestamp("2026-01-01 09:00", tz="Asia/Shanghai")
                + pd.Timedelta(minutes=idx),
                "open": close + 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100.0,
            }
        )
    rows[20].update({"open": 99.0, "high": 101.0, "low": 94.0, "close": 100.0, "volume": 350.0})
    rows[21].update({"open": 102.0, "high": 103.0, "low": 101.0, "close": 102.5, "volume": 100.0})
    rows[22].update({"open": 102.5, "high": 106.0, "low": 102.0, "close": 105.0, "volume": 100.0})
    return pd.DataFrame(rows)


def _params(**overrides) -> StrategyRuleParams:
    values = {
        "trend_lookback": 5,
        "drop_lookback": 5,
        "volume_lookback": 5,
        "uptrend_lookback": 10,
        "min_drop_pct": 0.02,
        "volume_spike_multiple": 2.0,
        "lower_shadow_min_ratio": 0.45,
        "max_holding_bars": 5,
    }
    values.update(overrides)
    return StrategyRuleParams(**values)


def _date_range() -> BacktestDateRange:
    return BacktestDateRange(
        "BTCUSDT",
        "1m",
        "2026-01-01 09:00+08:00",
        "2026-01-01 09:30+08:00",
    )


def test_backtest_service_runs_deep_v_and_returns_standard_outputs():
    result = BacktestService().run(
        BacktestConfig(initial_equity=10_000.0, fee_bps=0, slippage_bps=0),
        _market_df(),
        date_range=_date_range(),
        rule_params=_params(),
    )

    assert result.success is True
    assert result.errors == []
    assert result.summary["total_trades"] == 1
    assert result.summary["hit_tp_count"] == 1
    assert {
        "total_trades",
        "closed_trades",
        "win_rate",
        "avg_return",
        "median_return",
        "total_return",
        "max_drawdown",
        "profit_factor",
        "expectancy",
        "avg_holding_bars",
        "max_holding_bars",
        "fee_total",
        "slippage_total",
        "hit_tp_count",
        "hit_sl_count",
        "timeout_exit_count",
    } <= set(result.summary)
    assert {
        "entry_bar_index",
        "entry_time",
        "entry_price",
        "exit_bar_index",
        "exit_time",
        "exit_price",
        "side",
        "return_pct",
        "pnl",
        "exit_reason",
        "holding_bars",
        "fee",
        "slippage",
    } <= set(result.trades.columns)
    assert {"bar_index", "time", "equity", "drawdown"} <= set(result.equity_curve.columns)


def test_backtest_service_returns_clear_errors_for_invalid_inputs():
    service = BacktestService()

    invalid_config = service.run(
        BacktestConfig(initial_equity=0),
        _market_df(),
        date_range=_date_range(),
        rule_params=_params(),
    )
    invalid_risk_config = service.run(
        BacktestConfig(stop_loss_pct=-1, max_bars_hold=0),
        _market_df(),
        date_range=_date_range(),
        rule_params=_params(),
    )
    invalid_params = service.run(
        BacktestConfig(),
        _market_df(),
        date_range=_date_range(),
        rule_params=_params(min_drop_pct=0),
    )
    invalid_dates = service.run(
        BacktestConfig(),
        _market_df(),
        date_range=BacktestDateRange("BTCUSDT", "1m", "2026-01-01 09:10", "2026-01-01 09:10"),
        rule_params=_params(),
    )
    empty_data = service.run(
        BacktestConfig(),
        pd.DataFrame(),
        date_range=_date_range(),
        rule_params=_params(),
    )

    assert invalid_config.success is False
    assert "initial_equity" in invalid_config.errors[0]
    assert invalid_risk_config.success is False
    assert "max_bars_hold" in invalid_risk_config.errors[0] or "stop_loss_pct" in invalid_risk_config.errors[0]
    assert invalid_params.success is False
    assert "min_drop_pct" in invalid_params.errors[0]
    assert invalid_dates.success is False
    assert "start" in invalid_dates.errors[0]
    assert empty_data.success is False
    assert "no K-line data" in empty_data.errors[0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("strategy_name", "unsupported"),
        ("direction", "short_only"),
        ("direction", "both"),
        ("exit_mode", "timeout"),
        ("exit_mode", "signal"),
        ("allow_overlap_positions", True),
    ],
)
def test_backtest_service_rejects_unsupported_deep_v_capabilities(field, value):
    result = BacktestService().run(
        BacktestConfig(),
        _market_df(),
        date_range=_date_range(),
        rule_params=_params(**{field: value}),
    )

    assert result.success is False
    assert field in result.errors[0]


def test_backtest_service_returns_safe_empty_result_when_no_rule_trade_occurs():
    no_signal = _market_df()
    no_signal["volume"] = 100.0

    result = BacktestService().run(
        BacktestConfig(),
        no_signal,
        date_range=_date_range(),
        rule_params=_params(),
    )

    assert result.success is True
    assert result.summary["total_trades"] == 0
    assert result.summary["hit_tp_count"] == 0
    assert result.trades.empty
    assert not result.equity_curve.empty


def test_backtest_service_requires_uptrend_history_when_regime_filter_is_enabled():
    result = BacktestService().run(
        BacktestConfig(),
        _market_df(),
        date_range=_date_range(),
        rule_params=_params(regime_filter="uptrend", uptrend_lookback=50),
    )

    assert result.success is False
    assert "insufficient bars" in result.errors[0]


def test_backtest_service_compares_manual_and_rule_entries_without_leaking_manual_outcomes():
    manual = pd.DataFrame(
        [
            {
                "trade_id": "manual_overlap",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "status": "CLOSED",
                "entry_bar_index": 21,
                "final_return_pct": 5.0,
                "future_best_price": 999999.0,
            },
            {
                "trade_id": "manual_only",
                "symbol": "BTCUSDT",
                "interval": "1m",
                "status": "CLOSED",
                "entry_bar_index": 25,
                "final_return_pct": -1.0,
                "future_best_price": 999999.0,
            },
        ]
    )
    pessimistic_manual = manual.copy()
    pessimistic_manual["final_return_pct"] = [-999.0, -999.0]
    pessimistic_manual["future_best_price"] = 0.0

    service = BacktestService()
    result = service.run(
        BacktestConfig(fee_bps=0, slippage_bps=0),
        _market_df(),
        date_range=_date_range(),
        rule_params=_params(),
        manual_trades=manual,
    )
    pessimistic_result = service.run(
        BacktestConfig(fee_bps=0, slippage_bps=0),
        _market_df(),
        date_range=_date_range(),
        rule_params=_params(),
        manual_trades=pessimistic_manual,
    )

    comparison = result.manual_vs_rule_comparison
    assert comparison["manual_trade_count"] == 2
    assert comparison["rule_trade_count"] == 1
    assert comparison["overlap_entry_bars"] == [21]
    assert comparison["manual_only_bars"] == [25]
    assert comparison["rule_only_bars"] == []
    assert comparison["manual_avg_return"] == 2.0
    assert comparison["manual_win_rate"] == 50.0
    assert comparison["overlap_ratio"] == 0.5
    assert result.trades["entry_bar_index"].tolist() == pessimistic_result.trades["entry_bar_index"].tolist()
    assert result.trades["return_pct"].tolist() == pessimistic_result.trades["return_pct"].tolist()


def test_backtest_service_can_map_analysis_params_without_qt_dependency():
    analysis_params = {
        "drop_pct_threshold": 0.03,
        "volume_spike_threshold": 2.0,
        "lower_shadow_ratio": 0.45,
        "trend_window": 5,
        "future_window": 5,
    }

    result = BacktestService().run(
        BacktestConfig(fee_bps=0, slippage_bps=0),
        _market_df(),
        date_range=_date_range(),
        analysis_params_source=analysis_params,
    )

    assert result.success is True
    assert result.summary["total_trades"] == 0

    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "assert 'PySide6' not in sys.modules; "
                "import quant_collector_app.services.backtest_service; "
                "assert 'PySide6' not in sys.modules"
            ),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_backtest_service_rule_entries_ignore_outcome_columns():
    optimistic = _market_df().assign(
        fwd_ret_10=999.0,
        mfe_10=999.0,
        mae_10=999.0,
        hit_tp=1,
        hit_sl=0,
    )
    pessimistic = _market_df().assign(
        fwd_ret_10=-999.0,
        mfe_10=-999.0,
        mae_10=-999.0,
        hit_tp=0,
        hit_sl=1,
    )
    service = BacktestService()

    optimistic_result = service.run(
        BacktestConfig(fee_bps=0, slippage_bps=0),
        optimistic,
        date_range=_date_range(),
        rule_params=_params(),
    )
    pessimistic_result = service.run(
        BacktestConfig(fee_bps=0, slippage_bps=0),
        pessimistic,
        date_range=_date_range(),
        rule_params=_params(),
    )

    assert optimistic_result.trades["entry_bar_index"].tolist() == pessimistic_result.trades["entry_bar_index"].tolist()
    assert optimistic_result.trades["return_pct"].tolist() == pessimistic_result.trades["return_pct"].tolist()
