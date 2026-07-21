from __future__ import annotations

import json

import pandas as pd

from backtesting.engine import run_backtest
from backtesting.export import export_backtest_result
from backtesting.strategies import FeatureRuleLongStrategy
from backtesting.types import BacktestConfig, BacktestResult


def _df():
    close = [100, 101, 102, 103, 104]
    return pd.DataFrame(
        {
            "bar_index": range(5),
            "open_time_bjt": pd.date_range("2026-01-01", periods=5, freq="min", tz="Asia/Shanghai"),
            "open": close,
            "high": [c + 0.5 for c in close],
            "low": [c - 0.5 for c in close],
            "close": close,
            "volume": [100.0] * 5,
            "pre_ret_20": [-0.04] * 5,
        }
    )


def test_export_backtest_result_files(tmp_path):
    result = run_backtest(
        _df(),
        FeatureRuleLongStrategy([{"column": "pre_ret_20", "op": "<=", "value": -0.03}], exit_bars=3),
        BacktestConfig(),
        "BTCUSDT",
        "1m",
    )
    out = export_backtest_result(result, tmp_path, pd.DataFrame([{"params_json": "{}"}]), {"selected_params": {}})
    for name in [
        "backtest_trades.csv",
        "backtest_equity_curve.csv",
        "backtest_metrics.json",
        "parameter_scan_results.csv",
        "walk_forward_summary.json",
        "data_dictionary.md",
    ]:
        assert (out / name).exists()
    metrics = json.loads((out / "backtest_metrics.json").read_text(encoding="utf-8"))
    assert "risk_notice" in metrics


def test_export_empty_result_safe(tmp_path):
    result = BacktestResult(pd.DataFrame(), pd.DataFrame(), {}, {}, "empty", [])
    out = export_backtest_result(result, tmp_path)
    assert (out / "backtest_trades.csv").exists()
    assert (out / "backtest_equity_curve.csv").exists()
