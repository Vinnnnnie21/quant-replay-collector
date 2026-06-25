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


def _event_dot_color(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "").upper()
    side = str(event.get("side") or "").upper()
    if side == "LONG":
        return COLORS["green"]
    if side == "SHORT":
        return COLORS["red"]
    if event_type in {"LABEL", "NOTE"}:
        return COLORS["info"]
    return COLORS["text_muted"]


def _recent_event_title(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "").upper()
    side = str(event.get("side") or "").upper()
    labels = {
        ("OPEN", "LONG"): "开多",
        ("CLOSE", "LONG"): "平多",
        ("OPEN", "SHORT"): "开空",
        ("CLOSE", "SHORT"): "平空",
    }
    return labels.get((event_type, side), event_type_label(event.get("event_type")) or "事件")


def _recent_event_time(event: dict[str, Any]) -> str:
    value = event.get("bar_open_time_bjt") or event.get("created_at") or ""
    try:
        return pd.to_datetime(value).strftime("%m-%d %H:%M")
    except Exception:
        return str(value)


def _clear_layout(layout: QtWidgets.QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def populate_recent_event_list(
    list_widget: QtWidgets.QWidget,
    empty_widget: QtWidgets.QWidget | None,
    events: list[dict[str, Any]],
    limit: int = 6,
) -> None:
    layout = list_widget.layout()
    if layout is None:
        return
    visible_events = sorted(events, key=lambda row: row.get("created_at") or row.get("bar_open_time_bjt") or "")
    recent = list(reversed(visible_events[-max(0, int(limit)) :]))
    _clear_layout(layout)
    has_events = bool(recent)
    list_widget.setVisible(has_events)
    if empty_widget is not None:
        empty_widget.setVisible(not has_events)
    if not has_events:
        return
    for event in recent:
        row = QtWidgets.QFrame()
        row.setProperty("role", "recentEventItem")
        row_l = QtWidgets.QHBoxLayout(row)
        row_l.setContentsMargins(8, 6, 8, 6)
        row_l.setSpacing(8)
        dot = QtWidgets.QLabel("●")
        dot.setStyleSheet(f"color: {_event_dot_color(event)}; background: transparent;")
        dot.setFixedWidth(12)
        title = QtWidgets.QLabel(_recent_event_title(event))
        title.setProperty("role", "statusValue")
        time_label = QtWidgets.QLabel(_recent_event_time(event))
        time_label.setProperty("role", "tiny")
        meta = QtWidgets.QVBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(0)
        meta.addWidget(title)
        meta.addWidget(time_label)
        price = QtWidgets.QLabel(fmt_num(event.get("price_proxy")))
        price.setProperty("role", "statusValue")
        price.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        row_l.addWidget(dot)
        row_l.addLayout(meta, stretch=1)
        row_l.addWidget(price)
        layout.addWidget(row)
    layout.addStretch(1)


def populate_recent_event_table(table: QtWidgets.QTableWidget, events: list[dict[str, Any]], limit: int = 6) -> None:
    visible_events = sorted(events, key=lambda row: row.get("created_at") or row.get("bar_open_time_bjt") or "")
    recent = list(reversed(visible_events[-max(0, int(limit)) :]))
    table.setRowCount(len(recent))
    for row_index, event in enumerate(recent):
        dot = make_table_item("●")
        dot.setForeground(QtGui.QBrush(QtGui.QColor(_event_dot_color(event))))
        items = [
            dot,
            make_table_item(event.get("bar_open_time_bjt") or event.get("created_at") or ""),
            make_table_item(event_type_label(event.get("event_type"))),
            make_table_item(fmt_num(event.get("price_proxy")), numeric=True),
        ]
        for col_index, item in enumerate(items):
            table.setItem(row_index, col_index, item)


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
