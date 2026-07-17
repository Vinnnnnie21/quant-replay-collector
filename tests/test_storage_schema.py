from __future__ import annotations

import json
import sqlite3

import pytest

import storage as storage_module
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


def test_trade_event_replay_time_has_management_range_index(tmp_path):
    storage = StorageManager(tmp_path / "trade_management_index.db")

    with storage.connect() as conn:
        indexes = {
            row["name"]
            for row in conn.execute("PRAGMA index_list(trade_events)").fetchall()
        }
        columns = [
            row["name"]
            for row in conn.execute(
                "PRAGMA index_info(idx_trade_events_replay_time)"
            ).fetchall()
        ]

    assert "idx_trade_events_replay_time" in indexes
    assert columns == ["bar_open_time_bjt", "event_type", "trade_id"]


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
    assert {
        "symbol",
        "interval",
        "initial_equity",
        "fee_bps",
        "fill_mode",
        "take_profit_pct",
        "stop_loss_pct",
    } <= session_columns
    assert {
        "symbol",
        "interval",
        "entry_fill_price",
        "net_pnl_quote",
        "net_return_pct",
        "take_profit_pct",
        "stop_loss_pct",
        "take_profit_price",
        "stop_loss_price",
        "exit_reason",
    } <= trade_columns


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


def test_fetch_klines_for_range_returns_narrow_ordered_curve_rows(tmp_path):
    storage = StorageManager(tmp_path / "market_history.db")
    storage.upsert_klines(
        [
            {
                "symbol": symbol,
                "interval": interval,
                "open_time_utc_ms": open_time,
                "open_time_bjt": f"time-{open_time}",
                "close_time_utc_ms": open_time + 59_999,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1.0,
            }
            for symbol, interval, open_time, close in (
                ("BTCUSDT", "1m", 180_000, 103.0),
                ("BTCUSDT", "1m", 60_000, 101.0),
                ("BTCUSDT", "1m", 120_000, 102.0),
                ("ETHUSDT", "1m", 120_000, 999.0),
                ("BTCUSDT", "5m", 120_000, 999.0),
            )
        ]
    )

    rows = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=60_000,
        end_time_utc_ms=120_000,
    )

    assert rows == [
        {
            "bar_index": 0,
            "open_time_bjt": "time-60000",
            "open_time_utc_ms": 60_000,
            "close": 101.0,
        },
        {
            "bar_index": 1,
            "open_time_bjt": "time-120000",
            "open_time_utc_ms": 120_000,
            "close": 102.0,
        },
    ]


def test_fetch_klines_for_range_cooperatively_cancels_between_batches(tmp_path):
    storage = StorageManager(tmp_path / "market_history_cancel.db")
    row_count = 5_001
    storage.upsert_klines(
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "open_time_utc_ms": index * 60_000,
            "open_time_bjt": f"time-{index}",
            "close_time_utc_ms": index * 60_000 + 59_999,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        }
        for index in range(row_count)
    )
    cancellation_checks = 0

    def cancelled() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 2

    rows = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=0,
        end_time_utc_ms=row_count * 60_000,
        cancelled=cancelled,
    )

    assert rows == []
    assert cancellation_checks == 2


def test_existing_database_is_backed_up_before_schema_upgrade(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    backup_dir = tmp_path / "backups"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO sessions VALUES ('before_upgrade')")

    monkeypatch.setattr(
        storage_module.migrations,
        "migrate_to_v1",
        lambda _conn: (_ for _ in ()).throw(RuntimeError("migration stopped")),
    )

    with pytest.raises(RuntimeError, match="migration stopped"):
        StorageManager(path, backup_dir=backup_dir)

    backups = list(backup_dir.glob("quant_replay_pre_upgrade_v0_to_v6_*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT session_id FROM sessions").fetchone()[0] == "before_upgrade"
