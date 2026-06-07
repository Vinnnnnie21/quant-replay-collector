from __future__ import annotations

import json
from typing import Any, Iterable

try:
    from storage_core.connection import require_rowcount
except ImportError:  # pragma: no cover - package import path
    from .connection import require_rowcount


def insert_event(conn, row: dict[str, Any]) -> None:
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


def update_event_labels(conn, event_id: str, label_tags: list[str], note: str) -> None:
    cur = conn.execute(
        "UPDATE trade_events SET label_tags_json=?, note=? WHERE event_id=?",
        (json.dumps(label_tags, ensure_ascii=False), note, event_id),
    )
    require_rowcount(cur, 1, f"更新事件标签失败：event_id={event_id}")


def delete_event(conn, event_id: str) -> None:
    conn.execute("DELETE FROM trade_events WHERE event_id=?", (event_id,))


def save_event_windows(conn, session_id: str, event_id: str, rows: Iterable[dict[str, Any]]) -> None:
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
                row.get("offset"),
                row.get("is_event_bar"),
                row.get("bar_index"),
                row.get("bar_open_time_bjt"),
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("volume"),
                row.get("is_missing_padding"),
            )
            for row in rows
        ],
    )


def delete_event_windows(conn, event_id: str) -> None:
    conn.execute("DELETE FROM event_windows WHERE event_id=?", (event_id,))


def save_event_features(conn, row: dict[str, Any]) -> None:
    columns = list(row.keys())
    placeholders = ", ".join(["?"] * len(columns))
    conn.execute(
        f"INSERT OR REPLACE INTO event_features ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(row[column] for column in columns),
    )


def delete_event_features(conn, event_id: str) -> None:
    conn.execute("DELETE FROM event_features WHERE event_id=?", (event_id,))


def update_event_trade_outcome(
    conn,
    event_id: str,
    final_return_pct: float | None,
    holding_bars: int | None,
) -> None:
    conn.execute(
        """
        UPDATE event_features SET
            manual_trade_final_return_pct=?,
            manual_trade_holding_bars=?
        WHERE event_id=?
        """,
        (final_return_pct, holding_bars, event_id),
    )


def fetch_event(conn, event_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM trade_events WHERE event_id=?", (event_id,)).fetchone()
    if not row:
        return None
    out = dict(row)
    out["label_tags"] = json.loads(out.get("label_tags_json") or "[]")
    return out
