from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from app_config import DB_PATH


class StorageManager:
    ALLOWED_TABLES = {
        "sessions",
        "trades",
        "trade_events",
        "event_windows",
        "event_features",
        "account_equity",
        "usdt_premium_history",
    }
    TRADE_COLUMNS = [
        "trade_id", "session_id", "symbol", "interval", "side", "status",
        "entry_event_id", "exit_event_id", "entry_bar_index", "exit_bar_index",
        "entry_bar_time_bjt", "exit_bar_time_bjt", "entry_real_time_bjt", "exit_real_time_bjt",
        "entry_price_proxy", "exit_price_proxy", "holding_bars", "final_return_pct",
        "fill_mode", "fee_bps", "slippage_bps", "notional_quote", "quantity",
        "entry_price_raw", "exit_price_raw", "entry_fill_price", "exit_fill_price",
        "entry_fee_quote", "exit_fee_quote", "gross_pnl_quote", "net_pnl_quote",
        "gross_return_pct", "net_return_pct", "fee_return_pct",
        "created_at", "updated_at",
    ]

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = str(db_path)
        self._init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    interval TEXT,
                    start_date_bjt TEXT,
                    end_date_bjt TEXT,
                    cursor_bar_index INTEGER,
                    follow_latest INTEGER,
                    speed REAL,
                    last_opened_at TEXT,
                    last_saved_at TEXT,
                    app_version TEXT,
                    initial_equity REAL,
                    trade_notional REAL,
                    fee_bps REAL,
                    slippage_bps REAL,
                    fill_mode TEXT
                );

                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    symbol TEXT,
                    interval TEXT,
                    side TEXT,
                    status TEXT,
                    entry_event_id TEXT,
                    exit_event_id TEXT,
                    entry_bar_index INTEGER,
                    exit_bar_index INTEGER,
                    entry_bar_time_bjt TEXT,
                    exit_bar_time_bjt TEXT,
                    entry_real_time_bjt TEXT,
                    exit_real_time_bjt TEXT,
                    entry_price_proxy REAL,
                    exit_price_proxy REAL,
                    holding_bars INTEGER,
                    final_return_pct REAL,
                    fill_mode TEXT,
                    fee_bps REAL,
                    slippage_bps REAL,
                    notional_quote REAL,
                    quantity REAL,
                    entry_price_raw REAL,
                    exit_price_raw REAL,
                    entry_fill_price REAL,
                    exit_fill_price REAL,
                    entry_fee_quote REAL,
                    exit_fee_quote REAL,
                    gross_pnl_quote REAL,
                    net_pnl_quote REAL,
                    gross_return_pct REAL,
                    net_return_pct REAL,
                    fee_return_pct REAL,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_trades_session_status ON trades(session_id, status);

                CREATE TABLE IF NOT EXISTS trade_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    trade_id TEXT,
                    event_type TEXT,
                    side TEXT,
                    symbol TEXT,
                    interval TEXT,
                    bar_index INTEGER,
                    bar_open_time_bjt TEXT,
                    real_key_time_bjt TEXT,
                    price_proxy REAL,
                    label_tags_json TEXT,
                    note TEXT,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_trade_events_session ON trade_events(session_id, created_at);

                CREATE TABLE IF NOT EXISTS event_windows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    event_id TEXT,
                    offset INTEGER,
                    is_event_bar INTEGER,
                    bar_index INTEGER,
                    bar_open_time_bjt TEXT,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    is_missing_padding INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_event_windows_event ON event_windows(event_id, offset);

                CREATE TABLE IF NOT EXISTS event_features (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    trade_id TEXT,
                    event_type TEXT,
                    side TEXT,
                    symbol TEXT,
                    interval TEXT,
                    price_proxy REAL,
                    event_body REAL,
                    event_upper_wick REAL,
                    event_lower_wick REAL,
                    event_range REAL,
                    event_volume REAL,
                    event_vol_ratio_5 REAL,
                    pre_ret_3 REAL,
                    pre_ret_5 REAL,
                    pre_ret_10 REAL,
                    pre_vol_3 REAL,
                    pre_vol_5 REAL,
                    pre_vol_10 REAL,
                    prev_high10_dist_pct REAL,
                    prev_low10_dist_pct REAL,
                    bull_run_count INTEGER,
                    bear_run_count INTEGER,
                    event_upper_ratio REAL,
                    event_lower_ratio REAL,
                    event_body_ratio REAL,
                    fwd_ret_1 REAL,
                    fwd_ret_3 REAL,
                    fwd_ret_5 REAL,
                    fwd_ret_10 REAL,
                    fwd_ret_1_side_adj REAL,
                    fwd_ret_3_side_adj REAL,
                    fwd_ret_5_side_adj REAL,
                    fwd_ret_10_side_adj REAL,
                    mfe_10 REAL,
                    mae_10 REAL,
                    manual_trade_final_return_pct REAL,
                    manual_trade_holding_bars INTEGER,
                    export_version TEXT,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_event_features_session ON event_features(session_id, created_at);

                CREATE TABLE IF NOT EXISTS account_equity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    sequence_no INTEGER,
                    trade_id TEXT,
                    event_id TEXT,
                    equity_before REAL,
                    realized_gross_pnl REAL,
                    realized_fee REAL,
                    realized_net_pnl REAL,
                    equity_after REAL,
                    equity_return_pct REAL,
                    drawdown_pct REAL,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_account_equity_session ON account_equity(session_id, sequence_no);

                CREATE TABLE IF NOT EXISTS usdt_premium_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_time_bjt TEXT,
                    p2p_buy_price_cny REAL,
                    p2p_sell_price_cny REAL,
                    p2p_avg_price_cny REAL,
                    usd_cny_rate REAL,
                    buy_premium_pct REAL,
                    sell_premium_pct REAL,
                    avg_premium_pct REAL,
                    premium_pct REAL,
                    fx_source TEXT,
                    sample_status TEXT,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_usdt_sample_time ON usdt_premium_history(sample_time_bjt);
                """
            )

            self._ensure_column(conn, "usdt_premium_history", "buy_premium_pct", "REAL")
            self._ensure_column(conn, "usdt_premium_history", "sell_premium_pct", "REAL")
            self._ensure_column(conn, "usdt_premium_history", "avg_premium_pct", "REAL")
            self._ensure_column(conn, "usdt_premium_history", "fx_source", "TEXT")
            for column, column_type in {
                "initial_equity": "REAL",
                "trade_notional": "REAL",
                "fee_bps": "REAL",
                "slippage_bps": "REAL",
                "fill_mode": "TEXT",
            }.items():
                self._ensure_column(conn, "sessions", column, column_type)
            for column, column_type in {
                "fill_mode": "TEXT",
                "fee_bps": "REAL",
                "slippage_bps": "REAL",
                "notional_quote": "REAL",
                "quantity": "REAL",
                "entry_price_raw": "REAL",
                "exit_price_raw": "REAL",
                "entry_fill_price": "REAL",
                "exit_fill_price": "REAL",
                "entry_fee_quote": "REAL",
                "exit_fee_quote": "REAL",
                "gross_pnl_quote": "REAL",
                "net_pnl_quote": "REAL",
                "gross_return_pct": "REAL",
                "net_return_pct": "REAL",
                "fee_return_pct": "REAL",
            }.items():
                self._ensure_column(conn, "trades", column, column_type)


    def _ensure_column(self, conn, table: str, column: str, column_type: str):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def _require_rowcount(self, cursor, expected: int, message: str):
        if cursor.rowcount != expected:
            raise RuntimeError(f"{message}，期望影响 {expected} 行，实际影响 {cursor.rowcount} 行")

    def _insert_trade_row(self, conn, row: dict[str, Any]):
        columns = self.TRADE_COLUMNS
        placeholders = ", ".join(["?"] * len(columns))
        conn.execute(
            f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(row.get(c) for c in columns),
        )

    def upsert_session(self, row: dict[str, Any]):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, symbol, interval, start_date_bjt, end_date_bjt,
                    cursor_bar_index, follow_latest, speed, last_opened_at, last_saved_at, app_version,
                    initial_equity, trade_notional, fee_bps, slippage_bps, fill_mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    interval=excluded.interval,
                    start_date_bjt=excluded.start_date_bjt,
                    end_date_bjt=excluded.end_date_bjt,
                    cursor_bar_index=excluded.cursor_bar_index,
                    follow_latest=excluded.follow_latest,
                    speed=excluded.speed,
                    last_opened_at=excluded.last_opened_at,
                    last_saved_at=excluded.last_saved_at,
                    app_version=excluded.app_version,
                    initial_equity=excluded.initial_equity,
                    trade_notional=excluded.trade_notional,
                    fee_bps=excluded.fee_bps,
                    slippage_bps=excluded.slippage_bps,
                    fill_mode=excluded.fill_mode
                """,
                (
                    row.get("session_id"),
                    row.get("symbol"),
                    row.get("interval"),
                    row.get("start_date_bjt"),
                    row.get("end_date_bjt"),
                    row.get("cursor_bar_index"),
                    row.get("follow_latest"),
                    row.get("speed"),
                    row.get("last_opened_at"),
                    row.get("last_saved_at"),
                    row.get("app_version"),
                    row.get("initial_equity"),
                    row.get("trade_notional"),
                    row.get("fee_bps"),
                    row.get("slippage_bps"),
                    row.get("fill_mode"),
                ),
            )

    def get_latest_session(self):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions ORDER BY COALESCE(last_saved_at, last_opened_at) DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def insert_trade(self, row: dict[str, Any]):
        with self.connect() as conn:
            self._insert_trade_row(conn, row)

    def update_trade_close(self, row: dict[str, Any]):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE trades SET
                    status=?,
                    exit_event_id=?,
                    exit_bar_index=?,
                    exit_bar_time_bjt=?,
                    exit_real_time_bjt=?,
                    exit_price_proxy=?,
                    holding_bars=?,
                    final_return_pct=?,
                    quantity=?,
                    exit_price_raw=?,
                    exit_fill_price=?,
                    exit_fee_quote=?,
                    gross_pnl_quote=?,
                    net_pnl_quote=?,
                    gross_return_pct=?,
                    net_return_pct=?,
                    fee_return_pct=?,
                    updated_at=?
                WHERE trade_id=?
                """,
                (
                    row.get("status"), row.get("exit_event_id"), row.get("exit_bar_index"),
                    row.get("exit_bar_time_bjt"), row.get("exit_real_time_bjt"), row.get("exit_price_proxy"),
                    row.get("holding_bars"), row.get("final_return_pct"), row.get("quantity"),
                    row.get("exit_price_raw"), row.get("exit_fill_price"), row.get("exit_fee_quote"),
                    row.get("gross_pnl_quote"), row.get("net_pnl_quote"), row.get("gross_return_pct"),
                    row.get("net_return_pct"), row.get("fee_return_pct"), row.get("updated_at"), row.get("trade_id"),
                ),
            )

    def reopen_trade(self, row: dict[str, Any]):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE trades SET
                    status='OPEN',
                    exit_event_id=NULL,
                    exit_bar_index=NULL,
                    exit_bar_time_bjt=NULL,
                    exit_real_time_bjt=NULL,
                    exit_price_proxy=NULL,
                    holding_bars=NULL,
                    final_return_pct=NULL,
                    quantity=NULL,
                    exit_price_raw=NULL,
                    exit_fill_price=NULL,
                    exit_fee_quote=NULL,
                    gross_pnl_quote=NULL,
                    net_pnl_quote=NULL,
                    gross_return_pct=NULL,
                    net_return_pct=NULL,
                    fee_return_pct=NULL,
                    updated_at=?
                WHERE trade_id=?
                """,
                (row.get("updated_at"), row.get("trade_id")),
            )

    def delete_trade(self, trade_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM trades WHERE trade_id=?", (trade_id,))

    def insert_event(self, row: dict[str, Any]):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_events (
                    event_id, session_id, trade_id, event_type, side, symbol, interval,
                    bar_index, bar_open_time_bjt, real_key_time_bjt, price_proxy,
                    label_tags_json, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("event_id"), row.get("session_id"), row.get("trade_id"), row.get("event_type"),
                    row.get("side"), row.get("symbol"), row.get("interval"), row.get("bar_index"),
                    row.get("bar_open_time_bjt"), row.get("real_key_time_bjt"), row.get("price_proxy"),
                    json.dumps(row.get("label_tags", []), ensure_ascii=False), row.get("note"), row.get("created_at"),
                ),
            )

    def update_event_labels(self, event_id: str, label_tags: list[str], note: str):
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE trade_events SET label_tags_json=?, note=? WHERE event_id=?",
                (json.dumps(label_tags, ensure_ascii=False), note, event_id),
            )
            self._require_rowcount(cur, 1, f"更新事件标签失败：event_id={event_id}")

    def delete_event(self, event_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM trade_events WHERE event_id=?", (event_id,))

    def save_event_windows(self, session_id: str, event_id: str, rows: Iterable[dict[str, Any]]):
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO event_windows (
                    session_id, event_id, offset, is_event_bar, bar_index, bar_open_time_bjt,
                    open, high, low, close, volume, is_missing_padding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        session_id,
                        event_id,
                        r.get("offset"),
                        r.get("is_event_bar"),
                        r.get("bar_index"),
                        r.get("bar_open_time_bjt"),
                        r.get("open"),
                        r.get("high"),
                        r.get("low"),
                        r.get("close"),
                        r.get("volume"),
                        r.get("is_missing_padding"),
                    )
                    for r in rows
                ],
            )

    def delete_event_windows(self, event_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM event_windows WHERE event_id=?", (event_id,))

    def save_event_features(self, row: dict[str, Any]):
        columns = list(row.keys())
        placeholders = ", ".join(["?"] * len(columns))
        with self.connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO event_features ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[c] for c in columns),
            )

    def delete_event_features(self, event_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM event_features WHERE event_id=?", (event_id,))

    def insert_open_trade_bundle(
        self,
        trade_row: dict[str, Any],
        event_row: dict[str, Any],
        window_rows: Iterable[dict[str, Any]],
        feature_row: dict[str, Any],
    ):
        with self.connect() as conn:
            self._insert_trade_row(conn, trade_row)
            conn.execute(
                """
                INSERT INTO trade_events (
                    event_id, session_id, trade_id, event_type, side, symbol, interval,
                    bar_index, bar_open_time_bjt, real_key_time_bjt, price_proxy,
                    label_tags_json, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_row.get("event_id"), event_row.get("session_id"), event_row.get("trade_id"), event_row.get("event_type"),
                    event_row.get("side"), event_row.get("symbol"), event_row.get("interval"), event_row.get("bar_index"),
                    event_row.get("bar_open_time_bjt"), event_row.get("real_key_time_bjt"), event_row.get("price_proxy"),
                    json.dumps(event_row.get("label_tags", []), ensure_ascii=False), event_row.get("note"), event_row.get("created_at"),
                ),
            )
            self._insert_event_windows(conn, trade_row.get("session_id"), event_row.get("event_id"), window_rows)
            self._insert_event_features(conn, feature_row)

    def undo_open_trade_bundle(self, trade_id: str, event_id: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM event_features WHERE event_id=?", (event_id,))
            conn.execute("DELETE FROM event_windows WHERE event_id=?", (event_id,))
            event_cur = conn.execute("DELETE FROM trade_events WHERE event_id=?", (event_id,))
            trade_cur = conn.execute("DELETE FROM trades WHERE trade_id=?", (trade_id,))
            self._require_rowcount(event_cur, 1, f"撤销开仓失败：未找到事件 event_id={event_id}")
            self._require_rowcount(trade_cur, 1, f"撤销开仓失败：未找到交易 trade_id={trade_id}")

    def close_trade_bundle(
        self,
        event_row: dict[str, Any],
        window_rows: Iterable[dict[str, Any]],
        feature_row: dict[str, Any],
        close_update: dict[str, Any],
        entry_event_id: str,
        final_return_pct: float | None,
        holding_bars: int | None,
    ):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_events (
                    event_id, session_id, trade_id, event_type, side, symbol, interval,
                    bar_index, bar_open_time_bjt, real_key_time_bjt, price_proxy,
                    label_tags_json, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_row.get("event_id"), event_row.get("session_id"), event_row.get("trade_id"), event_row.get("event_type"),
                    event_row.get("side"), event_row.get("symbol"), event_row.get("interval"), event_row.get("bar_index"),
                    event_row.get("bar_open_time_bjt"), event_row.get("real_key_time_bjt"), event_row.get("price_proxy"),
                    json.dumps(event_row.get("label_tags", []), ensure_ascii=False), event_row.get("note"), event_row.get("created_at"),
                ),
            )
            self._insert_event_windows(conn, event_row.get("session_id"), event_row.get("event_id"), window_rows)
            self._insert_event_features(conn, feature_row)
            trade_cur = conn.execute(
                """
                UPDATE trades SET
                    status=?,
                    exit_event_id=?,
                    exit_bar_index=?,
                    exit_bar_time_bjt=?,
                    exit_real_time_bjt=?,
                    exit_price_proxy=?,
                    holding_bars=?,
                    final_return_pct=?,
                    quantity=?,
                    exit_price_raw=?,
                    exit_fill_price=?,
                    exit_fee_quote=?,
                    gross_pnl_quote=?,
                    net_pnl_quote=?,
                    gross_return_pct=?,
                    net_return_pct=?,
                    fee_return_pct=?,
                    updated_at=?
                WHERE trade_id=? AND status='OPEN'
                """,
                (
                    close_update.get("status"), close_update.get("exit_event_id"), close_update.get("exit_bar_index"),
                    close_update.get("exit_bar_time_bjt"), close_update.get("exit_real_time_bjt"), close_update.get("exit_price_proxy"),
                    close_update.get("holding_bars"), close_update.get("final_return_pct"), close_update.get("quantity"),
                    close_update.get("exit_price_raw"), close_update.get("exit_fill_price"), close_update.get("exit_fee_quote"),
                    close_update.get("gross_pnl_quote"), close_update.get("net_pnl_quote"), close_update.get("gross_return_pct"),
                    close_update.get("net_return_pct"), close_update.get("fee_return_pct"), close_update.get("updated_at"),
                    close_update.get("trade_id"),
                ),
            )
            self._require_rowcount(trade_cur, 1, f"平仓失败：交易不存在或不是未平仓状态 trade_id={close_update.get('trade_id')}")
            conn.execute(
                """
                UPDATE event_features SET
                    manual_trade_final_return_pct=?,
                    manual_trade_holding_bars=?
                WHERE event_id=?
                """,
                (final_return_pct, holding_bars, entry_event_id),
            )

    def undo_close_trade_bundle(self, trade_id: str, event_id: str, entry_event_id: str, updated_at: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM event_features WHERE event_id=?", (event_id,))
            conn.execute("DELETE FROM event_windows WHERE event_id=?", (event_id,))
            event_cur = conn.execute("DELETE FROM trade_events WHERE event_id=?", (event_id,))
            trade_cur = conn.execute(
                """
                UPDATE trades SET
                    status='OPEN',
                    exit_event_id=NULL,
                    exit_bar_index=NULL,
                    exit_bar_time_bjt=NULL,
                    exit_real_time_bjt=NULL,
                    exit_price_proxy=NULL,
                    holding_bars=NULL,
                    final_return_pct=NULL,
                    quantity=NULL,
                    exit_price_raw=NULL,
                    exit_fill_price=NULL,
                    exit_fee_quote=NULL,
                    gross_pnl_quote=NULL,
                    net_pnl_quote=NULL,
                    gross_return_pct=NULL,
                    net_return_pct=NULL,
                    fee_return_pct=NULL,
                    updated_at=?
                WHERE trade_id=?
                """,
                (updated_at, trade_id),
            )
            self._require_rowcount(event_cur, 1, f"撤销平仓失败：未找到平仓事件 event_id={event_id}")
            self._require_rowcount(trade_cur, 1, f"撤销平仓失败：未找到交易 trade_id={trade_id}")
            conn.execute(
                """
                UPDATE event_features SET
                    manual_trade_final_return_pct=?,
                    manual_trade_holding_bars=?
                WHERE event_id=?
                """,
                (None, None, entry_event_id),
            )

    def _insert_event_windows(self, conn, session_id: str, event_id: str, rows: Iterable[dict[str, Any]]):
        conn.executemany(
            """
            INSERT INTO event_windows (
                session_id, event_id, offset, is_event_bar, bar_index, bar_open_time_bjt,
                open, high, low, close, volume, is_missing_padding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session_id,
                    event_id,
                    r.get("offset"),
                    r.get("is_event_bar"),
                    r.get("bar_index"),
                    r.get("bar_open_time_bjt"),
                    r.get("open"),
                    r.get("high"),
                    r.get("low"),
                    r.get("close"),
                    r.get("volume"),
                    r.get("is_missing_padding"),
                )
                for r in rows
            ],
        )

    def _insert_event_features(self, conn, row: dict[str, Any]):
        columns = list(row.keys())
        placeholders = ", ".join(["?"] * len(columns))
        conn.execute(
            f"INSERT OR REPLACE INTO event_features ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(row[c] for c in columns),
        )

    def update_event_trade_outcome(self, event_id: str, final_return_pct: float | None, holding_bars: int | None):
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE event_features SET
                    manual_trade_final_return_pct=?,
                    manual_trade_holding_bars=?
                WHERE event_id=?
                """,
                (final_return_pct, holding_bars, event_id),
            )

    def replace_equity_curve(self, session_id: str, rows: Iterable[dict[str, Any]]):
        with self.connect() as conn:
            conn.execute("DELETE FROM account_equity WHERE session_id=?", (session_id,))
            conn.executemany(
                """
                INSERT INTO account_equity (
                    session_id, sequence_no, trade_id, event_id, equity_before,
                    realized_gross_pnl, realized_fee, realized_net_pnl, equity_after,
                    equity_return_pct, drawdown_pct, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.get("session_id"),
                        row.get("sequence_no"),
                        row.get("trade_id"),
                        row.get("event_id"),
                        row.get("equity_before"),
                        row.get("realized_gross_pnl"),
                        row.get("realized_fee"),
                        row.get("realized_net_pnl"),
                        row.get("equity_after"),
                        row.get("equity_return_pct"),
                        row.get("drawdown_pct"),
                        row.get("created_at"),
                    )
                    for row in rows
                ],
            )

    def insert_premium_sample(self, row: dict[str, Any]):
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO usdt_premium_history (
                    sample_time_bjt, p2p_buy_price_cny, p2p_sell_price_cny,
                    p2p_avg_price_cny, usd_cny_rate,
                    buy_premium_pct, sell_premium_pct, avg_premium_pct,
                    premium_pct, fx_source, sample_status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("sample_time_bjt"), row.get("p2p_buy_price_cny"), row.get("p2p_sell_price_cny"),
                    row.get("p2p_avg_price_cny"), row.get("usd_cny_rate"),
                    row.get("buy_premium_pct"), row.get("sell_premium_pct"), row.get("avg_premium_pct"),
                    row.get("premium_pct"), row.get("fx_source"), row.get("sample_status"), row.get("error_message"),
                ),
            )

    def fetch_table(self, table: str, where: str = "", params: tuple[Any, ...] = ()):
        if table not in self.ALLOWED_TABLES:
            raise ValueError(f"不允许读取未知表：{table}")
        query = f"SELECT * FROM {table}"
        if where:
            query += f" WHERE {where}"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def fetch_trade(self, trade_id: str):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone()
            return dict(row) if row else None

    def fetch_event(self, event_id: str):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM trade_events WHERE event_id=?", (event_id,)).fetchone()
            if not row:
                return None
            out = dict(row)
            out["label_tags"] = json.loads(out.get("label_tags_json") or "[]")
            return out

    def load_session_snapshot(self, session_id: str):
        session = None
        with self.connect() as conn:
            srow = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if srow:
                session = dict(srow)
            trades = [dict(r) for r in conn.execute(
                "SELECT * FROM trades WHERE session_id=? ORDER BY created_at", (session_id,)
            ).fetchall()]
            events = []
            for r in conn.execute(
                "SELECT * FROM trade_events WHERE session_id=? ORDER BY created_at", (session_id,)
            ).fetchall():
                item = dict(r)
                item["label_tags"] = json.loads(item.get("label_tags_json") or "[]")
                events.append(item)
            return session, trades, events
