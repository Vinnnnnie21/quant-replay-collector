from __future__ import annotations

from typing import Any

try:
    from accounting import build_equity_curve
    from storage_core.trade_repository import replace_equity_curve
except ImportError:  # pragma: no cover - package import path
    from ..accounting import build_equity_curve
    from .trade_repository import replace_equity_curve


_SELECTED_IDS_TABLE = "selected_trade_sample_ids"
TRADE_SAMPLE_TABLES = (
    "account_equity",
    "event_features",
    "event_windows",
    "trade_events",
    "trades",
)


def _select_trade_ids(conn, trade_ids: list[str] | tuple[str, ...]) -> None:
    normalized = sorted(
        {
            str(trade_id).strip()
            for trade_id in trade_ids
            if str(trade_id).strip()
        }
    )
    conn.execute(f"DROP TABLE IF EXISTS temp.{_SELECTED_IDS_TABLE}")
    conn.execute(
        f"CREATE TEMP TABLE {_SELECTED_IDS_TABLE} "
        "(trade_id TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    conn.executemany(
        f"INSERT INTO {_SELECTED_IDS_TABLE} (trade_id) VALUES (?)",
        ((trade_id,) for trade_id in normalized),
    )


def list_trade_samples_for_time_range(
    conn,
    *,
    start_time: str,
    end_time: str,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """List trades whose OPEN or CLOSE replay event falls in ``[start, end)``."""

    start = str(start_time or "").strip()
    end = str(end_time or "").strip()
    if not start or not end or start >= end:
        raise ValueError("start_time must be earlier than end_time")
    session = str(session_id).strip() if session_id else None
    rows = conn.execute(
        """
        WITH matched_trades AS (
            SELECT DISTINCT trade_id
            FROM trade_events
            WHERE event_type IN ('OPEN', 'CLOSE')
              AND bar_open_time_bjt >= ?
              AND bar_open_time_bjt < ?
              AND (? IS NULL OR session_id = ?)
        )
        SELECT
            t.trade_id,
            t.session_id,
            t.side,
            t.status,
            t.entry_bar_index,
            t.exit_bar_index,
            MIN(CASE WHEN e.event_type = 'OPEN' THEN e.bar_open_time_bjt END) AS entry_time,
            MAX(CASE WHEN e.event_type = 'CLOSE' THEN e.bar_open_time_bjt END) AS exit_time,
            t.net_pnl_quote,
            t.net_return_pct,
            t.final_return_pct
        FROM matched_trades AS matched
        JOIN trades AS t ON t.trade_id = matched.trade_id
        LEFT JOIN trade_events AS e ON e.trade_id = t.trade_id
        GROUP BY
            t.trade_id,
            t.session_id,
            t.side,
            t.status,
            t.entry_bar_index,
            t.exit_bar_index,
            t.net_pnl_quote,
            t.net_return_pct,
            t.final_return_pct
        ORDER BY COALESCE(entry_time, exit_time) ASC, t.trade_id ASC
        """,
        (start, end, session, session),
    ).fetchall()
    return [dict(row) for row in rows]


def list_trade_samples_for_session(
    conn,
    session_id: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return a bounded, display-only trade list for one performance session."""

    session = str(session_id or "").strip()
    if not session:
        return []
    bounded_limit = max(1, min(int(limit), 2_000))
    rows = conn.execute(
        """
        SELECT
            trade_id,
            session_id,
            symbol,
            interval,
            side,
            status,
            entry_bar_time_bjt AS entry_time,
            exit_bar_time_bjt AS exit_time,
            COALESCE(entry_fill_price, entry_price_proxy) AS entry_price,
            COALESCE(exit_fill_price, exit_price_proxy) AS exit_price,
            quantity,
            COALESCE(net_pnl_quote, gross_pnl_quote) AS pnl
        FROM trades
        WHERE session_id = ?
        ORDER BY COALESCE(entry_bar_time_bjt, created_at) ASC, trade_id ASC
        LIMIT ?
        """,
        (session, bounded_limit),
    ).fetchall()
    return [dict(row) for row in rows]


def preview_delete_trade_samples(
    conn,
    trade_ids: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Return bounded deletion counts for existing selected trades."""

    _select_trade_ids(conn, trade_ids)
    trade_rows = conn.execute(
        f"""
        SELECT t.trade_id, t.session_id
        FROM trades AS t
        JOIN {_SELECTED_IDS_TABLE} AS selected ON selected.trade_id = t.trade_id
        ORDER BY t.session_id ASC, t.trade_id ASC
        """
    ).fetchall()
    event_rows = conn.execute(
        f"""
        SELECT e.event_id
        FROM trade_events AS e
        JOIN {_SELECTED_IDS_TABLE} AS selected ON selected.trade_id = e.trade_id
        ORDER BY e.event_id ASC
        """
    ).fetchall()
    event_windows = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM event_windows AS window
            JOIN trade_events AS event ON event.event_id = window.event_id
            JOIN {_SELECTED_IDS_TABLE} AS selected ON selected.trade_id = event.trade_id
            """
        ).fetchone()[0]
    )
    event_features = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM event_features AS feature
            JOIN trade_events AS event ON event.event_id = feature.event_id
            JOIN {_SELECTED_IDS_TABLE} AS selected ON selected.trade_id = event.trade_id
            """
        ).fetchone()[0]
    )
    account_equity = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM account_equity AS equity
            WHERE equity.session_id IN (
                SELECT DISTINCT trade.session_id
                FROM trades AS trade
                JOIN {_SELECTED_IDS_TABLE} AS selected
                  ON selected.trade_id = trade.trade_id
            )
            """
        ).fetchone()[0]
    )
    return {
        "trades": len(trade_rows),
        "trade_events": len(event_rows),
        "event_windows": event_windows,
        "event_features": event_features,
        "account_equity": account_equity,
        "trade_ids": [str(row["trade_id"]) for row in trade_rows],
        "event_ids": [str(row["event_id"]) for row in event_rows],
        "session_ids": sorted({str(row["session_id"]) for row in trade_rows}),
    }


def _rebuild_account_equity(conn, session_id: str) -> None:
    session = conn.execute(
        """
        SELECT initial_equity, trade_notional
        FROM sessions
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    initial_equity = float(session["initial_equity"] or 10_000.0) if session else 10_000.0
    trade_notional = float(session["trade_notional"] or 1_000.0) if session else 1_000.0
    trades = [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                trade_id,
                status,
                exit_event_id,
                notional_quote,
                final_return_pct,
                gross_return_pct,
                net_pnl_quote,
                gross_pnl_quote,
                entry_fee_quote,
                exit_fee_quote,
                exit_bar_time_bjt,
                exit_real_time_bjt,
                updated_at
            FROM trades
            WHERE session_id = ?
            ORDER BY COALESCE(updated_at, exit_real_time_bjt, exit_bar_time_bjt) ASC,
                     trade_id ASC
            """,
            (session_id,),
        ).fetchall()
    ]
    rows = build_equity_curve(
        trades,
        session_id,
        initial_equity,
        trade_notional,
    )
    replace_equity_curve(conn, session_id, rows)


def delete_trade_samples(
    conn,
    trade_ids: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Delete selected trade samples and rebuild affected session equity."""

    preview = preview_delete_trade_samples(conn, trade_ids)
    if not preview["trade_ids"]:
        return preview
    conn.execute(
        f"""
        DELETE FROM event_windows
        WHERE EXISTS (
            SELECT 1
            FROM trade_events AS event
            JOIN {_SELECTED_IDS_TABLE} AS selected ON selected.trade_id = event.trade_id
            WHERE event.event_id = event_windows.event_id
        )
        """
    )
    conn.execute(
        f"""
        DELETE FROM event_features
        WHERE EXISTS (
            SELECT 1
            FROM trade_events AS event
            JOIN {_SELECTED_IDS_TABLE} AS selected ON selected.trade_id = event.trade_id
            WHERE event.event_id = event_features.event_id
        )
        """
    )
    conn.execute(
        f"""
        DELETE FROM trade_events
        WHERE EXISTS (
            SELECT 1
            FROM {_SELECTED_IDS_TABLE} AS selected
            WHERE selected.trade_id = trade_events.trade_id
        )
        """
    )
    conn.execute(
        f"""
        DELETE FROM trades
        WHERE EXISTS (
            SELECT 1
            FROM {_SELECTED_IDS_TABLE} AS selected
            WHERE selected.trade_id = trades.trade_id
        )
        """
    )
    for session_id in preview["session_ids"]:
        _rebuild_account_equity(conn, session_id)
    return preview


def preview_all_trade_sample_deletion(conn) -> dict[str, Any]:
    counts = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in TRADE_SAMPLE_TABLES
    }
    session_rows = conn.execute(
        """
        SELECT session_id FROM trades WHERE session_id IS NOT NULL
        UNION
        SELECT session_id FROM trade_events WHERE session_id IS NOT NULL
        UNION
        SELECT session_id FROM account_equity WHERE session_id IS NOT NULL
        ORDER BY session_id ASC
        """
    ).fetchall()
    counts["session_ids"] = [str(row["session_id"]) for row in session_rows]
    return counts


def clear_all_trade_samples(conn) -> dict[str, Any]:
    preview = preview_all_trade_sample_deletion(conn)
    for table in TRADE_SAMPLE_TABLES:
        conn.execute(f"DELETE FROM {table}")
    for session_id in preview["session_ids"]:
        _rebuild_account_equity(conn, session_id)
    return preview


__all__ = [
    "list_trade_samples_for_time_range",
    "list_trade_samples_for_session",
    "preview_delete_trade_samples",
    "delete_trade_samples",
    "preview_all_trade_sample_deletion",
    "clear_all_trade_samples",
    "TRADE_SAMPLE_TABLES",
]
