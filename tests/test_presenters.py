from __future__ import annotations

import pandas as pd
import pytest
from types import SimpleNamespace


QtCore = pytest.importorskip("PySide6.QtCore")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from presenters.formatters import (
    event_type_label,
    fmt_num,
    format_event_detail,
    format_trade_detail,
    short_id,
    side_label,
    status_label,
)
from presenters.table_presenter import (
    populate_equity_table,
    populate_event_study_table,
    populate_event_table,
    populate_recent_event_list,
    populate_trade_tables,
)


def _app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_formatters_preserve_main_window_display_text():
    assert side_label("LONG") == "多"
    assert status_label("CLOSED") == "已平仓"
    assert event_type_label("OPEN") == "开仓"
    assert short_id("trade_1234567890") == "trade_34567890"
    assert fmt_num(12.3456789) == "12.345679"
    assert fmt_num(1234.5678) == "1234.57"

    trade_detail = format_trade_detail(
        {
            "trade_id": "trade_1234567890",
            "side": "LONG",
            "status": "CLOSED",
            "entry_fill_price": 100.0,
            "exit_fill_price": 102.0,
            "net_return_pct": 2.0,
            "fill_mode": "CLOSE",
        }
    )
    assert "交易详情" in trade_detail
    assert "方向          : 多" in trade_detail
    assert "成交模式      : 收盘价" in trade_detail

    event_detail = format_event_detail(
        {
            "event_id": "evt_1",
            "trade_id": "trade_1",
            "event_type": "OPEN",
            "side": "SHORT",
            "price_proxy": 99.5,
            "label_tags": ["wick", "panic"],
        }
    )
    assert "事件详情" in event_detail
    assert "方向          : 空" in event_detail
    assert "wick, panic" in event_detail


def test_trade_and_event_tables_are_populated_with_short_ids_and_roles():
    _app()
    open_table = QtWidgets.QTableWidget()
    open_table.setColumnCount(10)
    closed_table = QtWidgets.QTableWidget()
    closed_table.setColumnCount(13)
    event_table = QtWidgets.QTableWidget()
    event_table.setColumnCount(8)

    trades = [
        {
            "trade_id": "trd_open_1234567890",
            "side": "LONG",
            "status": "OPEN",
            "entry_bar_time_bjt": "2026-01-01T00:00:00+08:00",
            "entry_price_proxy": 100.0,
            "entry_fee_quote": 0.4,
            "notional_quote": 1000.0,
            "entry_bar_index": 1,
            "fill_mode": "CLOSE",
            "created_at": "2026-01-01T00:00:00+08:00",
        },
        {
            "trade_id": "trd_closed_1234567890",
            "side": "SHORT",
            "status": "CLOSED",
            "entry_bar_time_bjt": "2026-01-01T00:00:00+08:00",
            "exit_bar_time_bjt": "2026-01-01T00:05:00+08:00",
            "entry_price_proxy": 100.0,
            "exit_price_proxy": 98.0,
            "final_return_pct": 2.0,
            "net_pnl_quote": 20.0,
            "holding_bars": 5,
            "fill_mode": "CLOSE",
            "updated_at": "2026-01-01T00:05:00+08:00",
        },
    ]
    events = [
        {
            "event_id": "evt_open_1234567890",
            "trade_id": "trd_open_1234567890",
            "event_type": "OPEN",
            "side": "LONG",
            "bar_open_time_bjt": "2026-01-01T00:00:00+08:00",
            "price_proxy": 100.0,
            "label_tags": ["wick"],
            "note": "note",
            "created_at": "2026-01-01T00:00:00+08:00",
        }
    ]

    populate_trade_tables(open_table, closed_table, trades)
    populate_event_table(event_table, events, selected_tag="wick")

    assert open_table.rowCount() == 1
    assert closed_table.rowCount() == 1
    assert open_table.item(0, 0).text() == "trd_34567890"
    assert open_table.item(0, 0).data(QtCore.Qt.UserRole) == "trd_open_1234567890"
    assert closed_table.item(0, 1).text() == "空"
    assert event_table.item(0, 0).text() == "evt_34567890"
    assert event_table.item(0, 0).data(QtCore.Qt.UserRole) == "evt_open_1234567890"


def test_equity_and_event_study_tables_are_presented_without_main_window():
    _app()
    equity_table = QtWidgets.QTableWidget()
    equity_table.setColumnCount(8)
    study_table = QtWidgets.QTableWidget()
    study_table.setColumnCount(9)

    populate_equity_table(
        equity_table,
        [
            {
                "sequence_no": 1,
                "trade_id": "trd_1234567890",
                "equity_before": 10000.0,
                "realized_net_pnl": 25.5,
                "realized_fee": 0.4,
                "equity_after": 10025.5,
                "equity_return_pct": 0.255,
                "drawdown_pct": -0.1,
            }
        ],
    )
    populate_event_study_table(
        study_table,
        pd.DataFrame(
            [
                {
                    "label_tag": "wick",
                    "event_type": "OPEN",
                    "side": "LONG",
                    "sample_count": 3,
                    "fwd_ret_1_mean": 0.01,
                    "fwd_ret_3_mean": -0.02,
                    "fwd_ret_5_mean": 0.03,
                    "fwd_ret_10_mean": 0.04,
                    "fwd_ret_1_win_rate_pct": 66.666,
                }
            ]
        ),
    )

    assert equity_table.item(0, 1).text() == "trd_34567890"
    assert equity_table.item(0, 1).data(QtCore.Qt.UserRole) == "trd_1234567890"
    assert study_table.item(0, 0).text() == "wick"
    assert study_table.item(0, 4).text() == "0.010000"


def test_recent_event_list_toggles_empty_state_without_table_widget():
    _app()
    list_widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(list_widget)
    empty_widget = QtWidgets.QLabel("empty")
    events = [
        {
            "event_id": "evt_open_1234567890",
            "event_type": "OPEN",
            "side": "LONG",
            "bar_open_time_bjt": "2026-01-01T00:00:00+08:00",
            "price_proxy": 100.0,
            "created_at": "2026-01-01T00:00:00+08:00",
        }
    ]

    populate_recent_event_list(list_widget, empty_widget, events)

    assert list_widget.isVisible()
    assert not empty_widget.isVisible()
    assert layout.count() == 2
    assert layout.itemAt(0).widget().property("role") == "recentEventItem"

    populate_recent_event_list(list_widget, empty_widget, [])

    assert not list_widget.isVisible()
    assert empty_widget.isVisible()


def test_main_window_table_refresh_uses_presenters_without_full_window():
    _app()
    from main_app import MainWindow

    window = SimpleNamespace(
        openTradesTable=QtWidgets.QTableWidget(),
        closedTradesTable=QtWidgets.QTableWidget(),
        eventTable=QtWidgets.QTableWidget(),
        equityTable=QtWidgets.QTableWidget(),
        eventFilterTag=SimpleNamespace(currentText=lambda: "全部标签"),
        eventFilterSide=SimpleNamespace(currentData=lambda: ""),
        eventFilterType=SimpleNamespace(currentData=lambda: ""),
        trades=[
            {
                "trade_id": "trd_open_1234567890",
                "side": "LONG",
                "status": "OPEN",
                "entry_bar_time_bjt": "2026-01-01T00:00:00+08:00",
                "entry_price_proxy": 100.0,
                "entry_fee_quote": 0.4,
                "notional_quote": 1000.0,
                "entry_bar_index": 1,
                "fill_mode": "CLOSE",
                "created_at": "2026-01-01T00:00:00+08:00",
            }
        ],
        events=[
            {
                "event_id": "evt_open_1234567890",
                "trade_id": "trd_open_1234567890",
                "event_type": "OPEN",
                "side": "LONG",
                "bar_open_time_bjt": "2026-01-01T00:00:00+08:00",
                "price_proxy": 100.0,
                "label_tags": ["wick"],
                "note": "note",
                "created_at": "2026-01-01T00:00:00+08:00",
            }
        ],
        _current_equity_rows=lambda: [
            {
                "sequence_no": 1,
                "trade_id": "trd_open_1234567890",
                "equity_before": 10000.0,
                "realized_net_pnl": 0.0,
                "realized_fee": 0.4,
                "equity_after": 9999.6,
                "equity_return_pct": -0.004,
                "drawdown_pct": -0.004,
            }
        ],
        _populate_event_study_table=lambda: None,
        _refresh_dataset_summary=lambda: None,
    )
    for table, columns in (
        (window.openTradesTable, 10),
        (window.closedTradesTable, 13),
        (window.eventTable, 8),
        (window.equityTable, 8),
    ):
        table.setColumnCount(columns)

    MainWindow._populate_tables(window, include_heavy=False)

    assert window.openTradesTable.rowCount() == 1
    assert window.eventTable.rowCount() == 1
    assert window.equityTable.rowCount() == 1
    assert window.openTradesTable.item(0, 0).data(QtCore.Qt.UserRole) == "trd_open_1234567890"
