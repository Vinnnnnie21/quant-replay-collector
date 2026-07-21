from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

import storage as storage_module
from app_config import APP_VERSION
from storage import StorageManager
from errors import DatabaseSchemaTooNewError


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


def test_higher_schema_uses_dedicated_compatibility_error_and_chinese_message(tmp_path):
    db_path = tmp_path / "newer.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version=20")

    with pytest.raises(DatabaseSchemaTooNewError) as captured:
        StorageManager(db_path)

    error = captured.value
    assert error.database_schema_version == 20
    assert error.supported_schema_version == StorageManager.SCHEMA_VERSION
    assert error.database_path == db_path.resolve()
    message = error.user_message_zh(APP_VERSION)
    assert APP_VERSION in message
    assert "19" in message
    assert "20" in message
    assert str(db_path.resolve()) in message
    assert "禁止" in message
    assert "降级" in message


def test_schema_19_is_rejected_by_a_simulated_schema_6_application(tmp_path):
    class SchemaSixStorage(StorageManager):
        SCHEMA_VERSION = 6

    db_path = tmp_path / "schema-19.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA user_version=19")

    with pytest.raises(DatabaseSchemaTooNewError) as captured:
        SchemaSixStorage(db_path)

    assert captured.value.database_schema_version == 19
    assert captured.value.supported_schema_version == 6


def test_startup_shows_schema_compatibility_message_without_raw_traceback(
    monkeypatch,
    tmp_path,
):
    import main_app

    error = DatabaseSchemaTooNewError(
        database_schema_version=20,
        supported_schema_version=19,
        database_path=tmp_path / "newer.db",
    )
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(main_app, "bootstrap_runtime_dirs", lambda: None)
    monkeypatch.setattr(main_app, "configure_logging", lambda: tmp_path / "app.log")
    monkeypatch.setattr(main_app, "install_exception_hook", lambda: None)
    monkeypatch.setattr(main_app.QtWidgets, "QApplication", lambda _argv: object())
    monkeypatch.setattr(main_app, "ensure_ui_font_support", lambda _app: None)
    monkeypatch.setattr(main_app, "apply_application_icon", lambda _app: None)
    monkeypatch.setattr(
        main_app,
        "MainWindow",
        lambda: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(
        main_app.QtWidgets,
        "QMessageBox",
        SimpleNamespace(
            critical=lambda _parent, title, message: shown.append((title, message))
        ),
    )

    assert main_app.main() == 2
    assert shown and shown[0][0] == "数据库版本不兼容"
    assert APP_VERSION in shown[0][1]
    assert "数据库版本：20" in shown[0][1]
    assert "Traceback" not in shown[0][1]


def test_v14_adds_immutable_entry_outcome_audit_tables(tmp_path):
    storage = StorageManager(tmp_path / "entry_outcome_schema.db")

    with storage.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        triggers = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        comparison_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(entry_outcome_comparisons)"
            ).fetchall()
        }

    assert {"entry_outcome_comparisons", "entry_outcome_matches"} <= tables
    assert "input_feature_fingerprint" in comparison_columns
    assert {
        "trg_entry_outcome_comparisons_no_update",
        "trg_entry_outcome_comparisons_no_delete",
        "trg_entry_outcome_matches_no_update",
        "trg_entry_outcome_matches_no_delete",
    } <= triggers


def test_schema_14_upgrade_adds_exit_review_tables_and_keeps_prior_rows(
    tmp_path,
):
    db_path = tmp_path / "schema_14.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(db_path, backup_dir=backup_dir)
    with legacy.connect() as conn:
        conn.execute(
            "INSERT INTO sessions(session_id, symbol) VALUES (?, ?)",
            ("session_before_v15", "BTCUSDT"),
        )
        conn.executescript(
            """
            DROP TABLE exit_review_reveals;
            DROP TABLE exit_judgment_versions;
            DROP TABLE exit_review_batch_items;
            DROP TABLE exit_review_batches;
            DROP TABLE exit_original_actions;
            DROP TABLE exit_account_pressure_snapshots;
            DROP TABLE exit_position_snapshots;
            DROP TABLE exit_decision_events;
            PRAGMA user_version=14;
            """
        )

    upgraded = StorageManager(db_path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.fetch_table(
        "sessions",
        "session_id=?",
        ("session_before_v15",),
    )[0]["symbol"] == "BTCUSDT"
    with upgraded.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "exit_decision_events",
        "exit_position_snapshots",
        "exit_account_pressure_snapshots",
        "exit_original_actions",
        "exit_review_batches",
        "exit_review_batch_items",
        "exit_judgment_versions",
        "exit_review_reveals",
    } <= tables
    assert list(
        backup_dir.glob(f"*v14_to_v{StorageManager.SCHEMA_VERSION}*.db")
    )


def test_schema_13_upgrade_adds_outcome_tables_and_keeps_prior_rows(tmp_path):
    db_path = tmp_path / "schema_13.db"
    backup_dir = tmp_path / "backups"
    legacy = StorageManager(db_path, backup_dir=backup_dir)
    with legacy.connect() as conn:
        conn.execute(
            "INSERT INTO sessions(session_id, symbol) VALUES (?, ?)",
            ("session_before_v14", "BTCUSDT"),
        )
        conn.executescript(
            """
            DROP TABLE entry_outcome_matches;
            DROP TABLE entry_outcome_comparisons;
            PRAGMA user_version=13;
            """
        )

    upgraded = StorageManager(db_path, backup_dir=backup_dir)

    assert upgraded.schema_version() == StorageManager.SCHEMA_VERSION
    assert upgraded.fetch_table(
        "sessions",
        "session_id=?",
        ("session_before_v14",),
    )[0]["symbol"] == "BTCUSDT"
    assert list(
        backup_dir.glob(f"*v13_to_v{StorageManager.SCHEMA_VERSION}*.db")
    )


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


def test_entry_outcome_tables_are_available_to_public_storage_audits(tmp_path):
    storage = StorageManager(tmp_path / "entry_outcome_audit.db")

    assert storage.fetch_table("entry_outcome_comparisons") == []
    assert storage.fetch_table("entry_outcome_matches") == []


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


def test_fetch_klines_for_range_keeps_legacy_curve_fields_in_time_order(tmp_path):
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

    assert [
        (
            row["bar_index"],
            row["open_time_bjt"],
            row["open_time_utc_ms"],
            row["close"],
        )
        for row in rows
    ] == [
        (0, "time-60000", 60_000, 101.0),
        (1, "time-120000", 120_000, 102.0),
    ]
    assert all(row["quote_volume"] is None for row in rows)


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

    backups = list(
        backup_dir.glob(
            "quant_replay_pre_upgrade_"
            f"v0_to_v{StorageManager.SCHEMA_VERSION}_*.db"
        )
    )
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT session_id FROM sessions").fetchone()[0] == "before_upgrade"


def test_reopening_current_schema_skips_all_migration_work(tmp_path, monkeypatch):
    path = tmp_path / "current.db"
    StorageManager(path)

    monkeypatch.setattr(
        storage_module.migrations,
        "migrate_to_v1",
        lambda _conn: (_ for _ in ()).throw(
            AssertionError("current schemas must not rerun migrations")
        ),
    )

    reopened = StorageManager(path)

    assert reopened.schema_version() == StorageManager.SCHEMA_VERSION


def test_new_database_migration_chain_uses_a_bounded_connection_count(
    tmp_path,
    monkeypatch,
):
    original_connect = StorageManager.connect
    connection_count = 0

    def counted_connect(self):
        nonlocal connection_count
        connection_count += 1
        return original_connect(self)

    monkeypatch.setattr(StorageManager, "connect", counted_connect)

    storage = StorageManager(tmp_path / "bounded-init.db")

    assert storage.schema_version() == StorageManager.SCHEMA_VERSION
    assert connection_count <= 3
