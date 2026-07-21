from __future__ import annotations

import sqlite3

from storage import StorageManager


def test_v3_database_upgrades_to_v4_without_losing_legacy_event_features(tmp_path):
    path = tmp_path / "v3.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (session_id TEXT PRIMARY KEY);
            CREATE TABLE trades (
                trade_id TEXT PRIMARY KEY,
                session_id TEXT,
                status TEXT
            );
            CREATE TABLE event_features (
                event_id TEXT PRIMARY KEY,
                session_id TEXT,
                symbol TEXT,
                interval TEXT,
                created_at TEXT
            );
            INSERT INTO sessions (session_id) VALUES ('s_legacy');
            INSERT INTO event_features (
                event_id, session_id, symbol, interval, created_at
            ) VALUES (
                'e_legacy', 's_legacy', 'BTCUSDT', '1m', '2026-01-01T00:00:00+00:00'
            );
            PRAGMA user_version=3;
            """
        )

    storage = StorageManager(path)

    assert storage.schema_version() == StorageManager.SCHEMA_VERSION
    with storage.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert {
        "strategy_profiles",
        "observation_universe",
        "strategy_samples",
        "event_context_features",
        "research_outcome_labels",
    } <= tables
    assert storage.fetch_table("event_features")[0]["event_id"] == "e_legacy"


def test_v4_keeps_legacy_event_features_available_for_existing_exports(tmp_path):
    storage = StorageManager(tmp_path / "v4.db")

    assert "event_features" in StorageManager.ALLOWED_TABLES
    assert storage.fetch_table("event_features") == []
