from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from backtesting.date_range import BacktestDateRange
from backtesting.parameter_schema import StrategyRuleParams
from backtesting.strategy_spec import StrategySpec
from backtesting.types import BacktestConfig
from controllers.backtest_controller import BacktestController
from project_paths import REPO_ROOT


class _BacktestService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, config, market_df, **kwargs):
        self.calls.append({"config": config, "market_df": market_df, **kwargs})
        return SimpleNamespace(success=True, errors=[])


def _form_values(**overrides):
    values = BacktestController.default_form_values()
    values.update(
        {
            "symbol": "BTCUSDT",
            "interval": "5m",
            "backtest_start": "2026-01-01 09:00+08:00",
            "backtest_end": "2026-01-02 09:00+08:00",
        }
    )
    values.update(overrides)
    return values


def test_controller_builds_config_and_rule_params_then_calls_service():
    service = _BacktestService()
    controller = BacktestController(service=service)
    market_df = pd.DataFrame({"close": [1.0]})

    result = controller.run(
        _form_values(min_drop_pct="0.04", fee_bps="7", notional_per_trade="2500"),
        market_df,
        manual_trades=[{"entry_bar_index": 1}],
    )

    assert result.success is True
    call = service.calls[0]
    assert isinstance(call["config"], BacktestConfig)
    assert call["config"].fee_bps == 7.0
    assert call["config"].notional_quote == 2500.0
    assert isinstance(call["date_range"], BacktestDateRange)
    assert call["date_range"].symbol == "BTCUSDT"
    assert isinstance(call["rule_params"], StrategyRuleParams)
    assert call["rule_params"].min_drop_pct == 0.04
    assert call["manual_trades"] == [{"entry_bar_index": 1}]


def test_controller_returns_clear_errors_before_calling_service():
    service = _BacktestService()
    controller = BacktestController(service=service)

    invalid_params = controller.run(
        _form_values(min_drop_pct="0"),
        pd.DataFrame({"close": [1.0]}),
    )
    invalid_dates = controller.run(
        _form_values(backtest_start="2026-01-02", backtest_end="2026-01-01"),
        pd.DataFrame({"close": [1.0]}),
    )

    assert invalid_params.success is False
    assert "min_drop_pct" in invalid_params.errors[0]
    assert invalid_dates.success is False
    assert "start" in invalid_dates.errors[0]
    assert service.calls == []


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
def test_controller_rejects_unsupported_deep_v_capabilities(field, value):
    service = _BacktestService()
    controller = BacktestController(service=service)

    result = controller.run(
        _form_values(**{field: value}),
        pd.DataFrame({"close": [1.0]}),
    )

    assert result.success is False
    assert field in result.errors[0]
    assert service.calls == []


def test_controller_rejects_selected_market_that_does_not_match_loaded_data():
    service = _BacktestService()
    controller = BacktestController(service=service)

    result = controller.run(
        _form_values(symbol="ETHUSDT", interval="15m"),
        pd.DataFrame({"close": [1.0]}),
        loaded_market_key=("BTCUSDT", "5m", "2026-01-01", "2026-01-02"),
    )

    assert result.success is False
    assert "currently loaded K-line data" in result.errors[0]
    assert service.calls == []


def test_controller_applies_analysis_params_and_rejects_missing_source():
    controller = BacktestController(service=_BacktestService())

    values = controller.apply_analysis_params(
        {
            "drop_pct_threshold": 0.05,
            "volume_spike_threshold": 3.0,
            "future_window": 12,
        },
        current_values=_form_values(symbol="ETHUSDT"),
    )

    assert values["symbol"] == "ETHUSDT"
    assert values["min_drop_pct"] == 0.05
    assert values["volume_spike_multiple"] == 3.0
    assert values["max_holding_bars"] == 12
    with pytest.raises(ValueError, match="No analysis candidate"):
        controller.apply_analysis_params(None)


def test_controller_applies_strategy_spec_without_running_backtest_service():
    service = _BacktestService()
    controller = BacktestController(service=service)
    spec = StrategySpec.from_dict(
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
                "interval": "5m",
                "data_start_utc_ms": 1_700_000_000_000,
                "data_end_utc_ms": 1_700_086_400_000,
            },
            "entry": {"rule": {"all": [{"feature": "volume_ratio_20", "op": ">=", "value": 1.8}]}},
            "exit": {
                "mode": "tp_sl_timeout",
                "take_profit_pct": 0.03,
                "stop_loss_pct": 0.015,
                "max_holding_bars": 20,
            },
            "position": {
                "direction": "long_only",
                "allow_overlap_positions": False,
                "cooldown_bars": 4,
                "notional_per_trade": 2500.0,
                "fee_bps": 5.0,
                "slippage_bps": 1.5,
            },
        }
    )

    values = controller.apply_strategy_spec(
        spec,
        current_values=_form_values(symbol="ETHUSDT"),
    )

    assert values["symbol"] == "BTCUSDT"
    assert values["interval"] == "5m"
    assert values["take_profit_pct"] == 0.03
    assert values["stop_loss_pct"] == 0.015
    assert values["max_holding_bars"] == 20
    assert values["cooldown_bars"] == 4
    assert values["notional_per_trade"] == 2500.0
    assert values["fee_bps"] == 5.0
    assert values["slippage_bps"] == 1.5
    assert values["strategy_spec"]["provenance"]["research_snapshot_id"] == "snapshot-abc"
    assert service.calls == []


def test_controller_runs_real_service_and_returns_zero_trade_warning():
    times = pd.date_range("2026-01-01 09:00", periods=60, freq="5min", tz="Asia/Shanghai")
    market_df = pd.DataFrame(
        {
            "bar_index": range(len(times)),
            "open_time_bjt": times,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 100.0,
        }
    )
    result = BacktestController().run(
        _form_values(
            backtest_end="2026-01-01 14:00+08:00",
            trend_lookback=5,
            drop_lookback=5,
            volume_lookback=5,
            uptrend_lookback=5,
        ),
        market_df,
    )

    assert result.success is True
    assert result.summary["total_trades"] == 0
    assert result.trades.empty


def test_backtest_controller_package_import_does_not_require_pyside6():
    repo_root = REPO_ROOT
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    probe = """
import builtins
import sys
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.startswith("PySide6"):
        raise ModuleNotFoundError("PySide6 intentionally unavailable")
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
import quant_collector_app.controllers.backtest_controller
assert "PySide6" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
