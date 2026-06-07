from __future__ import annotations

from typing import Any, Iterable

try:
    from storage_core.connection import require_rowcount
    from storage_core.event_repository import insert_event, save_event_features, save_event_windows
except ImportError:  # pragma: no cover - package import path
    from .connection import require_rowcount
    from .event_repository import insert_event, save_event_features, save_event_windows


def insert_trade_row(conn, row: dict[str, Any], columns: list[str]) -> None:
    placeholders = ", ".join(["?"] * len(columns))
    conn.execute(
        f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(row.get(column) for column in columns),
    )


def update_trade_close(conn, row: dict[str, Any]) -> None:
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


def reopen_trade(conn, row: dict[str, Any]) -> None:
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


def delete_trade(conn, trade_id: str) -> None:
    conn.execute("DELETE FROM trades WHERE trade_id=?", (trade_id,))


def insert_open_trade_bundle(
    conn,
    trade_row: dict[str, Any],
    event_row: dict[str, Any],
    window_rows: Iterable[dict[str, Any]],
    feature_row: dict[str, Any],
    trade_columns: list[str],
) -> None:
    insert_trade_row(conn, trade_row, trade_columns)
    insert_event(conn, event_row)
    save_event_windows(conn, trade_row.get("session_id"), event_row.get("event_id"), window_rows)
    save_event_features(conn, feature_row)


def undo_open_trade_bundle(conn, trade_id: str, event_id: str) -> None:
    conn.execute("DELETE FROM event_features WHERE event_id=?", (event_id,))
    conn.execute("DELETE FROM event_windows WHERE event_id=?", (event_id,))
    event_cur = conn.execute("DELETE FROM trade_events WHERE event_id=?", (event_id,))
    trade_cur = conn.execute("DELETE FROM trades WHERE trade_id=?", (trade_id,))
    require_rowcount(event_cur, 1, f"撤销开仓失败：未找到事件 event_id={event_id}")
    require_rowcount(trade_cur, 1, f"撤销开仓失败：未找到交易 trade_id={trade_id}")


def close_trade_bundle(
    conn,
    event_row: dict[str, Any],
    window_rows: Iterable[dict[str, Any]],
    feature_row: dict[str, Any],
    close_update: dict[str, Any],
    entry_event_id: str,
    final_return_pct: float | None,
    holding_bars: int | None,
) -> None:
    insert_event(conn, event_row)
    save_event_windows(conn, event_row.get("session_id"), event_row.get("event_id"), window_rows)
    save_event_features(conn, feature_row)
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
    require_rowcount(trade_cur, 1, f"平仓失败：交易不存在或不是未平仓状态 trade_id={close_update.get('trade_id')}")
    conn.execute(
        """
        UPDATE event_features SET
            manual_trade_final_return_pct=?,
            manual_trade_holding_bars=?
        WHERE event_id=?
        """,
        (final_return_pct, holding_bars, entry_event_id),
    )


def undo_close_trade_bundle(conn, trade_id: str, event_id: str, entry_event_id: str, updated_at: str) -> None:
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
    require_rowcount(event_cur, 1, f"撤销平仓失败：未找到平仓事件 event_id={event_id}")
    require_rowcount(trade_cur, 1, f"撤销平仓失败：未找到交易 trade_id={trade_id}")
    conn.execute(
        """
        UPDATE event_features SET
            manual_trade_final_return_pct=?,
            manual_trade_holding_bars=?
        WHERE event_id=?
        """,
        (None, None, entry_event_id),
    )


def replace_equity_curve(conn, session_id: str, rows: Iterable[dict[str, Any]]) -> None:
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


def fetch_trade(conn, trade_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone()
    return dict(row) if row else None
