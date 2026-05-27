from __future__ import annotations

import sqlite3

from storage import StorageManager


def test_v3_adds_query_indexes_without_removing_rows(tmp_path):
    path = tmp_path / "v2.db"
    storage = StorageManager(path)
    storage.upsert_session({"session_id": "s1", "symbol": "BTCUSDT", "interval": "1m"})
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=2")
        for name in [
            "idx_sessions_symbol_interval",
            "idx_trades_session_symbol_interval",
            "idx_trade_events_trade_time",
            "idx_trade_events_symbol_interval",
            "idx_event_windows_session_event",
            "idx_event_features_symbol_interval",
        ]:
            conn.execute(f"DROP INDEX IF EXISTS {name}")

    upgraded = StorageManager(path)
    with upgraded.connect() as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(trade_events)").fetchall()}
        session_count = conn.execute("SELECT COUNT(*) FROM sessions WHERE session_id='s1'").fetchone()[0]

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert {"idx_trade_events_trade_time", "idx_trade_events_symbol_interval"} <= indexes
    assert session_count == 1
