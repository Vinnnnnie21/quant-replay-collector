from __future__ import annotations

import math
from typing import Any

import pandas as pd
from PySide6 import QtCore, QtGui, QtWidgets

from presenters.formatters import (
    event_type_label,
    fill_mode_label,
    fmt_num,
    safe_float,
    short_id,
    side_label,
    status_label,
)
from ui_style import COLORS


ROLE_ID = QtCore.Qt.UserRole


def make_table_item(
    value: Any,
    role_id: Any = None,
    numeric: bool = False,
    pnl: bool = False,
    shorten_id: bool = False,
) -> QtWidgets.QTableWidgetItem:
    display = short_id(value) if shorten_id else ("" if value is None else str(value))
    item = QtWidgets.QTableWidgetItem(display)
    if role_id is not None:
        item.setData(ROLE_ID, role_id)
    if numeric:
        item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
    if pnl:
        number = safe_float(value, default=float("nan"))
        if math.isfinite(number):
            if number > 0:
                item.setForeground(QtGui.QBrush(QtGui.QColor(COLORS["green"])))
            elif number < 0:
                item.setForeground(QtGui.QBrush(QtGui.QColor(COLORS["red"])))
    return item


def populate_trade_tables(
    open_table: QtWidgets.QTableWidget,
    closed_table: QtWidgets.QTableWidget,
    trades: list[dict[str, Any]],
) -> None:
    open_trades = [trade for trade in trades if trade.get("status") == "OPEN"]
    closed_trades = [trade for trade in trades if trade.get("status") == "CLOSED"]
    open_trades.sort(key=lambda row: row.get("created_at") or "")
    closed_trades.sort(key=lambda row: row.get("updated_at") or "")

    open_table.setRowCount(len(open_trades))
    for row_index, trade in enumerate(open_trades):
        values = [
            trade["trade_id"],
            side_label(trade.get("side")),
            trade.get("entry_bar_time_bjt") or "",
            fmt_num(trade.get("entry_price_proxy")),
            fmt_num(trade.get("entry_fill_price") if trade.get("entry_fill_price") is not None else trade.get("entry_price_proxy")),
            fmt_num(trade.get("entry_fee_quote")),
            fmt_num(trade.get("notional_quote")),
            trade.get("entry_bar_index"),
            status_label(trade.get("status")),
            fill_mode_label(trade.get("fill_mode")),
        ]
        for col_index, value in enumerate(values):
            open_table.setItem(
                row_index,
                col_index,
                make_table_item(
                    value,
                    role_id=trade["trade_id"] if col_index == 0 else None,
                    numeric=col_index in {3, 4, 5, 6, 7},
                    shorten_id=col_index == 0,
                ),
            )

    closed_table.setRowCount(len(closed_trades))
    for row_index, trade in enumerate(closed_trades):
        total_fee = safe_float(trade.get("entry_fee_quote")) + safe_float(trade.get("exit_fee_quote"))
        net_return = trade.get("net_return_pct") if trade.get("net_return_pct") is not None else trade.get("final_return_pct")
        values = [
            trade["trade_id"],
            side_label(trade.get("side")),
            trade.get("entry_bar_time_bjt") or "",
            trade.get("exit_bar_time_bjt") or "",
            fmt_num(trade.get("entry_fill_price") if trade.get("entry_fill_price") is not None else trade.get("entry_price_proxy")),
            fmt_num(trade.get("exit_fill_price") if trade.get("exit_fill_price") is not None else trade.get("exit_price_proxy")),
            fmt_num(trade.get("gross_return_pct") if trade.get("gross_return_pct") is not None else trade.get("final_return_pct")),
            fmt_num(net_return),
            fmt_num(total_fee),
            fmt_num(trade.get("net_pnl_quote")),
            trade.get("holding_bars"),
            status_label(trade.get("status")),
            fill_mode_label(trade.get("fill_mode")),
        ]
        for col_index, value in enumerate(values):
            closed_table.setItem(
                row_index,
                col_index,
                make_table_item(
                    value,
                    role_id=trade["trade_id"] if col_index == 0 else None,
                    numeric=col_index in {4, 5, 6, 7, 8, 9, 10},
                    pnl=col_index in {6, 7, 9},
                    shorten_id=col_index == 0,
                ),
            )


def populate_event_table(
    table: QtWidgets.QTableWidget,
    events: list[dict[str, Any]],
    *,
    selected_tag: str = "全部标签",
    selected_side: str = "",
    selected_type: str = "",
) -> None:
    visible_events = sorted(events, key=lambda row: row.get("created_at") or "")
    if selected_tag and selected_tag != "全部标签":
        visible_events = [event for event in visible_events if selected_tag in (event.get("label_tags") or [])]
    if selected_side:
        visible_events = [event for event in visible_events if event.get("side") == selected_side]
    if selected_type:
        visible_events = [event for event in visible_events if event.get("event_type") == selected_type]

    table.setRowCount(len(visible_events))
    for row_index, event in enumerate(visible_events):
        values = [
            event["event_id"],
            event["trade_id"],
            event_type_label(event.get("event_type")),
            side_label(event.get("side")),
            event.get("bar_open_time_bjt") or "",
            fmt_num(event.get("price_proxy")),
            ", ".join(event.get("label_tags", [])),
            event.get("note") or "",
        ]
        for col_index, value in enumerate(values):
            table.setItem(
                row_index,
                col_index,
                make_table_item(
                    value,
                    role_id=event["event_id"] if col_index == 0 else None,
                    numeric=col_index in {5},
                    shorten_id=col_index in {0, 1},
                ),
            )


def populate_equity_table(table: QtWidgets.QTableWidget, equity_rows: list[dict[str, Any]]) -> None:
    table.setRowCount(len(equity_rows))
    for row_index, row in enumerate(equity_rows):
        values = [
            row.get("sequence_no") or row_index + 1,
            row.get("trade_id") or "",
            fmt_num(row.get("equity_before")),
            fmt_num(row.get("realized_net_pnl")),
            fmt_num(row.get("realized_fee")),
            fmt_num(row.get("equity_after")),
            fmt_num(row.get("equity_return_pct")),
            fmt_num(row.get("drawdown_pct")),
        ]
        for col_index, value in enumerate(values):
            table.setItem(
                row_index,
                col_index,
                make_table_item(
                    value,
                    role_id=row.get("trade_id") if col_index == 1 else None,
                    numeric=col_index in {0, 2, 3, 4, 5, 6, 7},
                    pnl=col_index in {3, 6, 7},
                    shorten_id=col_index == 1,
                ),
            )


def populate_event_study_table(table: QtWidgets.QTableWidget, summary: pd.DataFrame) -> None:
    table.setRowCount(len(summary))
    for row_index, row in summary.iterrows():
        values = [
            row.get("label_tag") or "",
            row.get("event_type") or "",
            row.get("side") or "",
            int(row.get("sample_count") or 0),
            fmt_num(row.get("fwd_ret_1_mean")),
            fmt_num(row.get("fwd_ret_3_mean")),
            fmt_num(row.get("fwd_ret_5_mean")),
            fmt_num(row.get("fwd_ret_10_mean")),
            fmt_num(row.get("fwd_ret_1_win_rate_pct")),
        ]
        for col_index, value in enumerate(values):
            table.setItem(
                row_index,
                col_index,
                make_table_item(value, numeric=col_index >= 3, pnl=col_index in {4, 5, 6, 7, 8}),
            )
