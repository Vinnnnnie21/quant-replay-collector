from __future__ import annotations

import json

import pandas as pd

from exporter import Exporter
from storage import StorageManager
from test_exporter_basic import insert_complete_trade, insert_session
from test_storage_trade_flow import SESSION_ID
from time_series_analysis.report import build_time_series_report, write_time_series_report


def _klines(n=80):
    return pd.DataFrame(
        {
            "bar_index": range(n),
            "open_time_bjt": pd.date_range("2026-01-01", periods=n, freq="min").astype(str),
            "open": [100 + i * 0.1 for i in range(n)],
            "high": [101 + i * 0.1 for i in range(n)],
            "low": [99 + i * 0.1 for i in range(n)],
            "close": [100 + i * 0.2 for i in range(n)],
            "volume": [10 + (i % 5) for i in range(n)],
        }
    )


def test_time_series_report_includes_liquidity_proxy_diagnostics():
    result = build_time_series_report(_klines())

    diagnostics = result["liquidity_proxy_diagnostics"]
    assert diagnostics["enabled"] is True
    assert diagnostics["proxy_name"] == "Kline Liquidity Impact Proxy"
    assert "OHLCV-based proxy" in diagnostics["disclaimer"]
    assert "not order book liquidity" in diagnostics["disclaimer"]
    assert {
        "total_rows",
        "valid_rows",
        "state_counts",
        "low_liquidity_shock_count",
        "event_repricing_count",
        "absorption_count",
        "mean_impact_score",
        "median_impact_score",
    }.issubset(diagnostics["summary"])


def test_time_series_report_disables_liquidity_proxy_when_ohlcv_is_missing():
    result = build_time_series_report(pd.DataFrame({"bar_index": [0], "open": [100.0]}))

    diagnostics = result["liquidity_proxy_diagnostics"]
    assert diagnostics["enabled"] is False
    assert diagnostics["reason"]
    assert "not order book liquidity" in diagnostics["disclaimer"]


def test_time_series_report_survives_liquidity_proxy_summary_failure(monkeypatch):
    import time_series_analysis.report as report_module

    def fail_summary(_):
        raise RuntimeError("summary failed")

    monkeypatch.setattr(report_module, "summarize_liquidity_proxy", fail_summary)

    result = report_module.build_time_series_report(_klines())

    diagnostics = result["liquidity_proxy_diagnostics"]
    assert diagnostics["enabled"] is False
    assert "summary failed" in diagnostics["reason"]


def test_event_window_only_report_does_not_claim_liquidity_proxy_state():
    result = build_time_series_report(_klines(), source="event_windows_only")

    diagnostics = result["liquidity_proxy_diagnostics"]
    assert diagnostics["enabled"] is False
    assert "event_windows_only" in diagnostics["reason"]
    assert "contiguous" in diagnostics["reason"]


def test_time_series_report_generates_markdown(tmp_path):
    result = build_time_series_report(_klines())
    path = write_time_series_report(result, tmp_path / "time_series_report.md")
    text = path.read_text(encoding="utf-8")
    assert "收益率定义" in text
    assert "波动率状态" in text
    assert "研究限制" in text


def test_time_series_report_supports_english(tmp_path):
    result = build_time_series_report(_klines())
    path = write_time_series_report(result, tmp_path / "time_series_report_en.md", language="en_US")
    text = path.read_text(encoding="utf-8")
    assert "Return Definition" in text
    assert "Volatility Regime" in text
    assert "Kline Liquidity Impact Proxy" in text
    assert "OHLCV-based proxy" in text
    assert "not order book liquidity" in text
    assert '"state_counts"' in text
    assert "Research Limitations" in text


def test_exporter_writes_time_series_outputs(tmp_path):
    storage = StorageManager(tmp_path / "export_ts.db")
    insert_session(storage)
    insert_complete_trade(storage)
    export_dir = Exporter(storage).export_session(SESSION_ID, tmp_path / "exports")
    assert (export_dir / "time_series_returns.csv").exists()
    assert (export_dir / "time_series_regimes.csv").exists()
    assert (export_dir / "time_series_summary.json").exists()
    assert (export_dir / "time_series_report.md").exists()
    manifest = json.loads((export_dir / "export_manifest.json").read_text(encoding="utf-8"))
    assert "time_series_returns" in manifest["files"]
    assert "time_series_summary" in manifest["files"]
    assert manifest["files"]["time_series_summary"]["source"] == "event_windows_only"
    assert "limitations" in manifest["files"]["time_series_summary"]
