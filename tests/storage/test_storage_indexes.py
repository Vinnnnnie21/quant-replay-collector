from __future__ import annotations

from storage import StorageManager


def test_query_indexes_cover_replay_and_audit_access_paths(tmp_path):
    storage = StorageManager(tmp_path / "indexes.db")
    with storage.connect() as connection:
        indexes = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }

    assert {
        "idx_trades_session_status",
        "idx_sessions_symbol_interval",
        "idx_trades_session_symbol_interval",
        "idx_trade_events_session",
        "idx_trade_events_trade_time",
        "idx_trade_events_symbol_interval",
        "idx_event_windows_event",
        "idx_event_windows_session_event",
        "idx_event_features_session",
        "idx_event_features_symbol_interval",
        "idx_klines_symbol_interval_time",
        "idx_quality_symbol_interval_time",
    } <= indexes
