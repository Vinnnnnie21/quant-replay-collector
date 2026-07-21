from __future__ import annotations

import sqlite3

import pandas as pd

from market_data import BINANCE_RAW_COLUMNS, _normalize_kline_df
from storage import StorageManager


def _create_schema_v6_database(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE klines (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time_utc_ms INTEGER NOT NULL,
                open_time_bjt TEXT,
                close_time_utc_ms INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                source TEXT,
                downloaded_at TEXT,
                data_quality_status TEXT,
                PRIMARY KEY (symbol, interval, open_time_utc_ms)
            );
            CREATE INDEX idx_klines_symbol_interval_time
                ON klines(symbol, interval, open_time_utc_ms);
            PRAGMA user_version=6;
            """
        )


def _insert_schema_v6_kline(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO klines (
                symbol, interval, open_time_utc_ms, open_time_bjt,
                close_time_utc_ms, open, high, low, close, volume, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "BTCUSDT",
                "1m",
                60_000,
                "legacy-time",
                119_999,
                10.0,
                12.0,
                9.0,
                11.0,
                5.0,
                "legacy-cache",
            ),
        )


def _kline_row(**overrides):
    row = {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "open_time_utc_ms": 1_700_000_000_000,
        "open_time_bjt": "2023-11-15T06:13:20+08:00",
        "close_time_utc_ms": 1_700_000_059_999,
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 20.0,
        "quote_volume": 2_010.5,
        "trade_count": 42,
        "taker_buy_base_volume": 11.25,
        "taker_buy_quote_volume": 1_130.75,
        "source": "binance_online",
        "downloaded_at": "2026-07-18T00:00:00+00:00",
        "data_quality_status": "PASS",
    }
    row.update(overrides)
    return row


def test_schema_v6_upgrade_round_trips_ancillary_kline_fields_through_public_storage(
    tmp_path,
):
    database_path = tmp_path / "schema_v6.db"
    _create_schema_v6_database(database_path)

    storage = StorageManager(database_path, backup_dir=tmp_path / "backups")
    storage.upsert_klines([_kline_row()])
    restored = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=1_700_000_000_000,
        end_time_utc_ms=1_700_000_000_000,
    )

    assert storage.schema_version() == StorageManager.SCHEMA_VERSION
    assert len(restored) == 1
    assert {
        name: restored[0][name]
        for name in (
            "quote_volume",
            "trade_count",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
        )
    } == {
        "quote_volume": 2_010.5,
        "trade_count": 42,
        "taker_buy_base_volume": 11.25,
        "taker_buy_quote_volume": 1_130.75,
    }


def test_schema_v6_upgrade_preserves_old_rows_indexes_and_null_ancillary_values(
    tmp_path,
):
    database_path = tmp_path / "schema_v6_with_history.db"
    backup_dir = tmp_path / "backups"
    _create_schema_v6_database(database_path)
    _insert_schema_v6_kline(database_path)

    storage = StorageManager(database_path, backup_dir=backup_dir)
    restored = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=60_000,
        end_time_utc_ms=60_000,
    )

    assert len(restored) == 1
    assert restored[0]["open"] == 10.0
    assert restored[0]["close"] == 11.0
    assert restored[0]["volume"] == 5.0
    assert all(
        restored[0][name] is None
        for name in (
            "quote_volume",
            "trade_count",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
        )
    )
    with storage.connect() as conn:
        indexes = {
            row["name"]
            for row in conn.execute("PRAGMA index_list(klines)").fetchall()
        }
    assert "idx_klines_symbol_interval_time" in indexes

    backups = list(
        backup_dir.glob(
            "quant_replay_pre_upgrade_"
            f"v6_to_v{StorageManager.SCHEMA_VERSION}_*.db"
        )
    )
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        assert conn.execute("SELECT close FROM klines").fetchone()[0] == 11.0


def test_complete_upsert_fills_ancillary_nulls_on_an_existing_kline(tmp_path):
    database_path = tmp_path / "fill_existing_nulls.db"
    _create_schema_v6_database(database_path)
    _insert_schema_v6_kline(database_path)
    storage = StorageManager(database_path, backup_dir=tmp_path / "backups")

    storage.upsert_klines(
        [
            _kline_row(
                open_time_utc_ms=60_000,
                open_time_bjt="updated-time",
                close_time_utc_ms=119_999,
            )
        ]
    )
    restored = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=60_000,
        end_time_utc_ms=60_000,
    )[0]

    assert restored["open_time_bjt"] == "updated-time"
    assert restored["quote_volume"] == 2_010.5
    assert restored["trade_count"] == 42
    assert restored["taker_buy_base_volume"] == 11.25
    assert restored["taker_buy_quote_volume"] == 1_130.75


def test_ohlcv_only_upsert_updates_prices_without_erasing_ancillary_values(
    tmp_path,
):
    storage = StorageManager(tmp_path / "merge.db")
    storage.upsert_klines([_kline_row()])
    storage.upsert_klines(
        [
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "open_time_utc_ms": 1_700_000_000_000,
                "open_time_bjt": "2023-11-15T06:13:20+08:00",
                "close_time_utc_ms": 1_700_000_059_999,
                "open": 101.0,
                "high": 103.0,
                "low": 100.0,
                "close": 102.0,
                "volume": 21.0,
                "source": "legacy-ohlcv-caller",
            }
        ]
    )

    restored = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=1_700_000_000_000,
        end_time_utc_ms=1_700_000_000_000,
    )[0]

    assert {
        name: restored[name]
        for name in ("open", "high", "low", "close", "volume")
    } == {
        "open": 101.0,
        "high": 103.0,
        "low": 100.0,
        "close": 102.0,
        "volume": 21.0,
    }
    assert {
        name: restored[name]
        for name in (
            "quote_volume",
            "trade_count",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
        )
    } == {
        "quote_volume": 2_010.5,
        "trade_count": 42,
        "taker_buy_base_volume": 11.25,
        "taker_buy_quote_volume": 1_130.75,
    }


def test_missing_and_real_zero_ancillary_values_remain_distinct(tmp_path):
    storage = StorageManager(tmp_path / "null_and_zero.db")
    storage.upsert_klines(
        [
            _kline_row(
                open_time_utc_ms=60_000,
                close_time_utc_ms=119_999,
                quote_volume=None,
                trade_count=None,
                taker_buy_base_volume=None,
                taker_buy_quote_volume=None,
            ),
            _kline_row(
                open_time_utc_ms=120_000,
                close_time_utc_ms=179_999,
                quote_volume=0.0,
                trade_count=0,
                taker_buy_base_volume=0.0,
                taker_buy_quote_volume=0.0,
            ),
        ]
    )

    missing, zero = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=60_000,
        end_time_utc_ms=120_000,
    )

    field_names = (
        "quote_volume",
        "trade_count",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    )
    assert all(missing[name] is None for name in field_names)
    assert {name: zero[name] for name in field_names} == {
        "quote_volume": 0.0,
        "trade_count": 0,
        "taker_buy_base_volume": 0.0,
        "taker_buy_quote_volume": 0.0,
    }


def test_normalized_exchange_rows_stream_through_public_storage_without_loss(
    tmp_path,
):
    from market_data import iter_kline_storage_rows

    raw = pd.DataFrame(
        [
            [
                1_700_000_000_000,
                "100.0",
                "102.0",
                "99.0",
                "101.0",
                "20.0",
                1_700_000_059_999,
                "2010.5",
                "42",
                "11.25",
                "1130.75",
                0,
            ]
        ],
        columns=BINANCE_RAW_COLUMNS,
    )
    normalized, _stats = _normalize_kline_df(
        raw,
        pd.Timestamp("2023-11-15T06:13:20+08:00").to_pydatetime(),
        pd.Timestamp("2023-11-15T06:13:20+08:00").to_pydatetime(),
        "1m",
        "Binance download",
    )
    normalized.attrs["data_source"] = "binance_online"
    normalized.attrs["data_quality_report"] = {
        "created_at": "2026-07-18T00:00:00+00:00",
        "data_quality_status": "PASS",
    }

    storage = StorageManager(tmp_path / "parsed_exchange.db")
    storage.upsert_klines(
        iter_kline_storage_rows(
            normalized,
            symbol="BTCUSDT",
            interval="1m",
        )
    )
    restored = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=1_700_000_000_000,
        end_time_utc_ms=1_700_000_000_000,
    )[0]

    assert restored["quote_volume"] == 2_010.5
    assert restored["trade_count"] == 42
    assert restored["taker_buy_base_volume"] == 11.25
    assert restored["taker_buy_quote_volume"] == 1_130.75
    assert restored["source"] == "binance_online"
    assert restored["downloaded_at"] == "2026-07-18T00:00:00+00:00"
    assert restored["data_quality_status"] == "PASS"


def test_public_ancillary_completeness_audit_counts_missing_and_zero_separately(
    tmp_path,
):
    storage = StorageManager(tmp_path / "completeness.db")
    storage.upsert_klines(
        [
            _kline_row(
                open_time_utc_ms=60_000,
                close_time_utc_ms=119_999,
                quote_volume=100.0,
                trade_count=10,
                taker_buy_base_volume=5.0,
                taker_buy_quote_volume=50.0,
            ),
            _kline_row(
                open_time_utc_ms=120_000,
                close_time_utc_ms=179_999,
                quote_volume=0.0,
                trade_count=0,
                taker_buy_base_volume=0.0,
                taker_buy_quote_volume=0.0,
            ),
            _kline_row(
                open_time_utc_ms=180_000,
                close_time_utc_ms=239_999,
                quote_volume=None,
                trade_count=3,
                taker_buy_base_volume=None,
                taker_buy_quote_volume=0.0,
            ),
        ]
    )

    audit = storage.audit_kline_ancillary_completeness(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=60_000,
        end_time_utc_ms=180_000,
    )

    assert audit["symbol"] == "BTCUSDT"
    assert audit["interval"] == "1m"
    assert audit["requested_start_time_utc_ms"] == 60_000
    assert audit["requested_end_time_utc_ms"] == 180_000
    assert audit["first_open_time_utc_ms"] == 60_000
    assert audit["last_open_time_utc_ms"] == 180_000
    assert audit["total_rows"] == 3
    assert audit["fields"] == {
        "quote_volume": {
            "covered_rows": 2,
            "missing_rows": 1,
            "zero_rows": 1,
            "coverage_ratio": 2 / 3,
        },
        "trade_count": {
            "covered_rows": 3,
            "missing_rows": 0,
            "zero_rows": 1,
            "coverage_ratio": 1.0,
        },
        "taker_buy_base_volume": {
            "covered_rows": 2,
            "missing_rows": 1,
            "zero_rows": 1,
            "coverage_ratio": 2 / 3,
        },
        "taker_buy_quote_volume": {
            "covered_rows": 3,
            "missing_rows": 0,
            "zero_rows": 2,
            "coverage_ratio": 1.0,
        },
    }


def test_repeated_complete_kline_upsert_is_idempotent(tmp_path):
    storage = StorageManager(tmp_path / "idempotent.db")
    row = _kline_row()

    storage.upsert_klines([row])
    storage.upsert_klines([row])

    restored = storage.fetch_klines_for_range(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=1_700_000_000_000,
        end_time_utc_ms=1_700_000_000_000,
    )
    audit = storage.audit_kline_ancillary_completeness(
        symbol="BTCUSDT",
        interval="1m",
        start_time_utc_ms=1_700_000_000_000,
        end_time_utc_ms=1_700_000_000_000,
    )

    assert len(restored) == 1
    assert restored[0]["quote_volume"] == 2_010.5
    assert restored[0]["trade_count"] == 42
    assert audit["total_rows"] == 1
