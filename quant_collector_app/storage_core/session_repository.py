from __future__ import annotations

import json
from typing import Any


def upsert_session(conn, row: dict[str, Any]) -> None:
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


def get_latest_session(conn) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM sessions ORDER BY COALESCE(last_saved_at, last_opened_at) DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def clear_manual_research_records(conn, tables: tuple[str, ...]) -> dict[str, int]:
    deleted = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }
    for table in tables:
        conn.execute(f"DELETE FROM {table}")
    return deleted


def load_session_snapshot(conn, session_id: str):
    session = None
    srow = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if srow:
        session = dict(srow)
    trades = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM trades WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    ]
    events = []
    for row in conn.execute(
        "SELECT * FROM trade_events WHERE session_id=? ORDER BY created_at",
        (session_id,),
    ).fetchall():
        item = dict(row)
        item["label_tags"] = json.loads(item.get("label_tags_json") or "[]")
        events.append(item)
    return session, trades, events
