from __future__ import annotations

import json
from pathlib import Path

from exporter import Exporter
from storage import StorageManager
from test_storage_trade_flow import (
    INTERVAL,
    NOW,
    SESSION_ID,
    SYMBOL,
    insert_open_bundle,
    make_event_row,
    make_feature_row,
    make_window_rows,
)


def make_storage(tmp_path: Path) -> StorageManager:
    return StorageManager(tmp_path / "export_test.db")


def insert_session(storage: StorageManager):
    storage.upsert_session(
        {
            "session_id": SESSION_ID,
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "start_date_bjt": "2026-01-01",
            "end_date_bjt": "2026-01-01",
            "cursor_bar_index": 12,
            "follow_latest": 0,
            "speed": 1.0,
            "last_opened_at": NOW,
            "last_saved_at": NOW,
            "app_version": "test",
        }
    )


def insert_complete_trade(storage: StorageManager):
    insert_open_bundle(storage)
    close_event = make_event_row("evt_close", event_type="CLOSE", bar_index=12, price=103.0)
    close_feature = make_feature_row("evt_close", event_type="CLOSE", price=103.0)
    close_update = {
        "trade_id": "trd_1",
        "status": "CLOSED",
        "exit_event_id": "evt_close",
        "exit_bar_index": 12,
        "exit_bar_time_bjt": NOW,
        "exit_real_time_bjt": NOW,
        "exit_price_proxy": 103.0,
        "holding_bars": 2,
        "final_return_pct": 3.0,
        "updated_at": NOW,
    }
    storage.close_trade_bundle(
        close_event,
        make_window_rows(),
        close_feature,
        close_update,
        "evt_open",
        3.0,
        2,
    )


def test_export_session_writes_core_files(tmp_path):
    storage = make_storage(tmp_path)
    insert_session(storage)
    insert_complete_trade(storage)

    export_root = tmp_path / "exports"
    export_dir = Exporter(storage).export_session(SESSION_ID, export_root)

    assert export_dir.exists()
    for name in [
        "trades.csv",
        "trade_events.csv",
        "event_windows_long.csv",
        "event_wide.csv",
        "event_features.csv",
        "event_labels.csv",
        "event_features_full.csv",
        "event_wide_full.csv",
        "account_equity.csv",
        "event_study_summary.csv",
        "ml_features.csv",
        "ml_labels.csv",
        "sample_index.csv",
        "sessions.csv",
        "usdt_premium_history.csv",
    ]:
        assert (export_dir / name).exists(), name

    manifest_path = export_dir / "export_manifest.json"
    dictionary_path = export_dir / "data_dictionary.md"
    perf_csv = export_dir / "performance_summary.csv"
    perf_json = export_dir / "performance_summary.json"

    assert manifest_path.exists()
    assert dictionary_path.exists()
    assert perf_csv.exists() or perf_json.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["session_id"] == SESSION_ID
    assert manifest["symbol"] == SYMBOL
    assert manifest["interval"] == INTERVAL
    assert manifest["row_counts"]["trades"] == 1
    assert manifest["row_counts"]["trade_events"] == 2
    assert manifest["row_counts"]["performance_summary"] == 1
    assert "performance_summary" in manifest["files"]
    assert "ml_features" in manifest["files"]
    assert "event_study_summary" in manifest["files"]


def test_export_session_passes_selected_research_label(tmp_path):
    storage = make_storage(tmp_path)
    insert_session(storage)
    insert_complete_trade(storage)

    export_dir = Exporter(storage).export_session(
        SESSION_ID,
        tmp_path / "exports",
        selected_label="fwd_ret_5_side_adj",
    )
    research_manifest = json.loads((export_dir / "research" / "research_manifest.json").read_text(encoding="utf-8"))
    assert research_manifest["selected_label"] == "fwd_ret_5_side_adj"
