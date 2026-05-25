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
