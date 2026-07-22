from __future__ import annotations

import json
from types import SimpleNamespace

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


def test_export_backtest_result_includes_random_baseline_outputs(tmp_path):
    result = BacktestResult(pd.DataFrame(), pd.DataFrame(), {}, {}, "with-baseline", [])
    result.random_baseline_equity_curve = pd.DataFrame(
        [{"bar_index": 1, "time": "2026-01-01T00:01:00+08:00", "equity": 10001.0, "drawdown": 0.0}]
    )
    result.random_baseline_summary = {
        "status": "ready",
        "random_seed": 123,
        "simulation_count": 100,
        "completed_runs": 100,
    }

    out = export_backtest_result(result, tmp_path)

    assert (out / "random_baseline_median_equity_curve.csv").exists()
    assert (out / "random_baseline_summary.json").exists()
    summary = json.loads((out / "random_baseline_summary.json").read_text(encoding="utf-8"))
    assert summary["random_seed"] == 123


def test_export_service_result_shape_includes_structured_strategy_spec_and_params(tmp_path):
    result = SimpleNamespace(
        summary={"total_trades": 1, "total_return": 0.01},
        trades=pd.DataFrame([{"entry_bar_index": 3, "pnl": 12.5}]),
        equity_curve=pd.DataFrame([{"bar_index": 3, "equity": 10012.5, "drawdown": 0.0}]),
        random_baseline_equity_curve=pd.DataFrame(
            [{"bar_index": 3, "equity": 9998.0, "drawdown": -0.0002}]
        ),
        random_baseline_summary={"status": "ready", "random_seed": 42},
    )
    strategy_spec = {
        "schema_version": "strategy_spec_v1",
        "provenance": {"research_snapshot_id": "snapshot-export"},
    }

    out = export_backtest_result(
        result,
        tmp_path,
        strategy_spec=strategy_spec,
        applied_params={"symbol": "BTCUSDT", "interval": "5m"},
    )

    metrics = json.loads((out / "backtest_metrics.json").read_text(encoding="utf-8"))
    exported_spec = json.loads((out / "strategy_spec_v1.json").read_text(encoding="utf-8"))
    applied = json.loads((out / "backtest_applied_params.json").read_text(encoding="utf-8"))
    assert metrics["total_trades"] == 1
    assert exported_spec["provenance"]["research_snapshot_id"] == "snapshot-export"
    assert applied["symbol"] == "BTCUSDT"
