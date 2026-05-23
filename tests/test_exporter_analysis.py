from __future__ import annotations

import json

import pandas as pd

from exporter import Exporter
from storage import StorageManager
from test_storage_trade_flow import (
    INTERVAL,
    NOW,
    SESSION_ID,
    SYMBOL,
    make_event_row,
    make_feature_row,
    make_trade_row,
    make_window_rows,
)


def _storage(tmp_path):
    return StorageManager(tmp_path / "export_analysis.db")


def _insert_session(storage):
    storage.upsert_session(
        {
            "session_id": SESSION_ID,
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-02",
            "cursor_bar_index": 12,
            "follow_latest": 0,
            "speed": 1.0,
            "last_opened_at": NOW,
            "last_saved_at": NOW,
            "app_version": "test",
            "initial_equity": 10000.0,
            "trade_notional": 1000.0,
            "fee_bps": 4.0,
            "slippage_bps": 1.0,
            "fill_mode": "close",
        }
    )


def _insert_trade_with_labels(storage):
    feature = make_feature_row()
    feature.update(
        {
            "pre_ret_3": -0.01,
            "pre_ret_5": -0.02,
            "pre_ret_10": -0.03,
            "fwd_ret_5": 0.004,
            "fwd_ret_10": 0.012,
            "fwd_ret_5_side_adj": 0.004,
            "fwd_ret_10_side_adj": 0.012,
            "mfe_10": 0.016,
            "mae_10": -0.003,
        }
    )
    windows = []
    for offset in range(-20, 11):
        base = 100.0 + offset * 0.2
        windows.append(
            {
                "offset": offset,
                "is_event_bar": 1 if offset == 0 else 0,
                "bar_index": 100 + offset,
                "bar_open_time_bjt": NOW,
                "open": base,
                "high": base + 1.0,
                "low": base - 1.0,
                "close": base + (0.6 if offset == 0 else -0.1),
                "volume": 100.0 + abs(offset),
                "is_missing_padding": 0,
            }
        )
    storage.insert_open_trade_bundle(make_trade_row(), make_event_row(), windows, feature)

    close_feature = make_feature_row("evt_close", event_type="CLOSE", price=103.0)
    close_update = {
        "trade_id": "trd_1",
        "status": "CLOSED",
        "exit_event_id": "evt_close",
        "exit_bar_index": 110,
        "exit_bar_time_bjt": NOW,
        "exit_real_time_bjt": NOW,
        "exit_price_proxy": 103.0,
        "holding_bars": 10,
        "final_return_pct": 3.0,
        "updated_at": NOW,
    }
    storage.close_trade_bundle(
        make_event_row("evt_close", event_type="CLOSE", bar_index=110, price=103.0),
        make_window_rows(),
        close_feature,
        close_update,
        "evt_open",
        3.0,
        10,
    )


def test_export_session_writes_analysis_outputs_and_keeps_ml_features_clean(tmp_path):
    storage = _storage(tmp_path)
    _insert_session(storage)
    _insert_trade_with_labels(storage)

    export_dir = Exporter(storage).export_session(SESSION_ID, tmp_path / "exports")

    expected = [
        "analysis_audit.json",
        "analysis_audit.md",
        "enhanced_event_features.csv",
        "strategy_labels.csv",
        "feature_binning_summary.csv",
        "feature_binning_summary.json",
        "candidate_rules.csv",
        "candidate_rules.json",
        "strategy_research_report.md",
        "strategy_consistency.json",
        "strategy_consistency_report.md",
    ]
    for filename in expected:
        assert (export_dir / filename).exists(), filename

    ml_features = pd.read_csv(export_dir / "ml_features.csv")
    forbidden = [c for c in ml_features.columns if c.startswith(("fwd_", "post_")) or c in {"mfe_10", "mae_10"}]
    assert forbidden == []

    manifest = json.loads((export_dir / "export_manifest.json").read_text(encoding="utf-8"))
    for key in ["enhanced_event_features", "strategy_labels", "feature_binning_summary", "candidate_rules"]:
        assert key in manifest["files"]
        assert key in manifest["row_counts"]
    assert "analysis_audit" in manifest["files"]
    assert "strategy_research_report" in manifest["files"]
    assert "strategy_consistency" in manifest["files"]
    assert "time_series_returns" in manifest["files"]
    assert manifest["files"]["time_series_summary"]["source"] == "event_windows_only"
    summary = json.loads((export_dir / "time_series_summary.json").read_text(encoding="utf-8"))
    assert any("fragmented" in warning for warning in summary["warnings"])
