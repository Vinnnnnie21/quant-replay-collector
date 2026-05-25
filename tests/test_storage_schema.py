from __future__ import annotations

import json
import sqlite3

from storage import StorageManager


def test_initializes_versioned_quality_schema_and_connection_pragmas(tmp_path):
    storage = StorageManager(tmp_path / "quality.db")

    assert storage.schema_version() == StorageManager.SCHEMA_VERSION
    with storage.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
    assert {"sessions", "trades", "klines", "data_quality_reports"} <= tables


def test_legacy_database_is_upgraded_without_losing_existing_rows(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (session_id TEXT PRIMARY KEY);
            CREATE TABLE trades (
                trade_id TEXT PRIMARY KEY,
                session_id TEXT,
                status TEXT
            );
            INSERT INTO sessions (session_id) VALUES ('legacy_session');
            INSERT INTO trades (trade_id, session_id, status)
                VALUES ('legacy_trade', 'legacy_session', 'OPEN');
            """
        )

    storage = StorageManager(path)

    assert storage.schema_version() == StorageManager.SCHEMA_VERSION
    assert storage.fetch_trade("legacy_trade")["status"] == "OPEN"
    with storage.connect() as conn:
        session_columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        trade_columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
    assert {"symbol", "interval", "initial_equity", "fee_bps", "fill_mode"} <= session_columns
    assert {"symbol", "interval", "entry_fill_price", "net_pnl_quote", "net_return_pct"} <= trade_columns


def test_kline_and_quality_report_writes_are_upserts(tmp_path):
    storage = StorageManager(tmp_path / "market.db")
    kline = {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "open_time_utc_ms": 1_700_000_000_000,
        "open_time_bjt": "2026-01-01T08:00:00+08:00",
        "close_time_utc_ms": 1_700_000_059_999,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 20.0,
        "source": "binance",
        "downloaded_at": "2026-01-01T00:01:00+00:00",
        "data_quality_status": "PASS",
    }
    storage.upsert_klines([kline])
    storage.upsert_klines([{**kline, "close": 101.5}])

    report = {
        "report_id": "r1",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "expected_bars": 1,
        "actual_bars": 1,
        "missing_bars": 0,
        "duplicated_bars": 0,
        "invalid_rows": 0,
        "report_json": json.dumps({"status": "PASS"}),
    }
    storage.save_data_quality_report(report)

    klines = storage.fetch_table("klines")
    reports = storage.fetch_table("data_quality_reports")
    assert len(klines) == 1
    assert klines[0]["close"] == 101.5
    assert reports[0]["report_id"] == "r1"
