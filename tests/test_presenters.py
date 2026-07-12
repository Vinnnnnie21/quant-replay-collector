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
from presenters.status_presenter import _update_position_panel, update_header


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


def test_equity_table_supports_continuous_mark_to_market_rows():
    _app()
    equity_table = QtWidgets.QTableWidget()
    equity_table.setColumnCount(8)

    populate_equity_table(
        equity_table,
        [
            {
                "sequence_no": 2,
                "bar_index": 11,
                "realized_net_pnl": 20.0,
                "unrealized_pnl": 10.0,
                "open_position_count": 1,
                "current_equity": 1030.0,
                "total_return_pct": 3.0,
                "drawdown_pct": 0.0,
            }
        ],
    )

    assert equity_table.item(0, 1).text() == "11"
    assert equity_table.item(0, 3).text() == "10.00"
    assert equity_table.item(0, 4).text() == "1"
    assert equity_table.item(0, 5).text() == "1030.00"
    assert equity_table.item(0, 6).text() == "3.00"


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


def test_recent_event_list_defaults_to_latest_event_only():
    _app()
    list_widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(list_widget)
    empty_widget = QtWidgets.QLabel("empty")
    events = [
        {
            "event_id": f"evt_{index}",
            "event_type": "OPEN",
            "side": "LONG",
            "bar_open_time_bjt": f"2026-01-01T00:0{index}:00+08:00",
            "price_proxy": 100.0 + index,
            "created_at": f"2026-01-01T00:0{index}:00+08:00",
        }
        for index in range(3)
    ]

    populate_recent_event_list(list_widget, empty_widget, events)

    items = [
        layout.itemAt(index).widget()
        for index in range(layout.count())
        if layout.itemAt(index).widget() is not None
        and layout.itemAt(index).widget().property("role") == "recentEventItem"
    ]
    visible_text = " ".join(label.text() for label in list_widget.findChildren(QtWidgets.QLabel))

    assert len(items) == 1
    assert "102.00" in visible_text
    assert "101.00" not in visible_text


def test_status_account_overview_includes_unrealized_pnl():
    _app()
    labels = {
        name: QtWidgets.QLabel("-")
        for name in (
            "accountEquityValue",
            "accountReturnValue",
            "accountPnlValue",
            "accountWinRateValue",
            "accountSharpeValue",
            "accountProfitFactorValue",
            "accountPayoffValue",
            "accountMaxDrawdownValue",
            "headerMainLabel",
            "headerPlayBadge",
            "headerViewBadge",
            "headerSessionBadge",
        )
    }
    mini_table = QtWidgets.QTableWidget()
    mini_table.setColumnCount(6)
    window = SimpleNamespace(
        **labels,
        openPositionsMiniTable=mini_table,
        df=pd.DataFrame(
            [
                {
                    "bar_index": 2,
                    "open_time_bjt": "2026-01-01T00:02:00+08:00",
                    "open": 101.0,
                    "high": 103.0,
                    "low": 100.0,
                    "close": 102.0,
                    "volume": 10.0,
                }
            ]
        ),
        cursor=0,
        trades=[
            {"trade_id": "closed", "status": "CLOSED", "net_pnl_quote": 20.0, "net_return_pct": 2.0, "exit_bar_index": 1},
            {
                "trade_id": "open",
                "status": "OPEN",
                "side": "LONG",
                "entry_fill_price": 100.0,
                "notional_quote": 500.0,
            },
        ],
        symbolBox=SimpleNamespace(currentText=lambda: "BTCUSDT"),
        intervalBox=SimpleNamespace(currentText=lambda: "1m"),
        initialEquitySpin=SimpleNamespace(value=lambda: 1000.0),
        tradeNotionalSpin=SimpleNamespace(value=lambda: 500.0),
        playing=False,
        follow_latest=False,
        session_id="sess_1234567890",
        chartIntervalButtons={},
        _display_interval=lambda: "1m",
        _sample_interval=lambda: "1m",
        _set_widget_role=lambda *_args: None,
        _update_load_play_button=lambda: None,
        _update_trade_buttons_enabled=lambda: None,
        tr=lambda key, default=None: {"paused": "暂停", "free_view": "自由浏览", "session": "session"}.get(key, default or key),
    )

    update_header(window)

    assert window.accountEquityValue.text() == "1030.00"
    assert window.accountPnlValue.text() == "30.00"
    assert window.accountReturnValue.text() == "3.00%"
    assert window.accountWinRateValue.text() == "100.00%"
    assert mini_table.rowCount() == 1
    assert mini_table.item(0, 1).text() == "LONG"
    assert mini_table.item(0, 3).text() == "10.00"


def test_trade_position_cards_keep_each_open_trade_direction_and_pnl_separate():
    _app()
    cards = QtWidgets.QWidget()
    cards_layout = QtWidgets.QVBoxLayout(cards)
    cards_layout.setContentsMargins(0, 0, 0, 0)
    scroll = QtWidgets.QScrollArea()
    window = SimpleNamespace(
        tradePositionCardsLayout=cards_layout,
        tradePositionScroll=scroll,
        tradePositionEmptyState=QtWidgets.QLabel(),
        df=pd.DataFrame(),
        trades=[
            {"trade_id": "long", "status": "OPEN", "side": "LONG", "entry_fill_price": 100.0, "notional_quote": 500.0, "entry_bar_index": 1},
            {"trade_id": "short", "status": "OPEN", "side": "SHORT", "entry_fill_price": 100.0, "notional_quote": 500.0, "entry_bar_index": 2},
        ],
    )

    _update_position_panel(window, pd.Series({"close": 110.0}))

    position_cards = [
        cards_layout.itemAt(index).widget()
        for index in range(cards_layout.count())
        if cards_layout.itemAt(index).widget() is not None
    ]
    assert [card.property("side") for card in position_cards] == ["LONG", "SHORT"]
    assert scroll.isVisible()

    long_values = {label.property("field"): label for label in position_cards[0].findChildren(QtWidgets.QLabel) if label.property("field")}
    short_values = {label.property("field"): label for label in position_cards[1].findChildren(QtWidgets.QLabel) if label.property("field")}
    assert long_values["side"].text() == "做多"
    assert long_values["side"].property("role") == "valuePositive"
    assert long_values["notional"].text() == "500.00"
    assert long_values["pnl_pct"].property("role") == "valuePositive"
    assert short_values["side"].text() == "做空"
    assert short_values["side"].property("role") == "valueNegative"
    assert short_values["pnl"].property("role") == "valueNegative"


def test_trade_position_cards_are_reused_when_only_the_price_changes():
    _app()
    cards = QtWidgets.QWidget()
    cards_layout = QtWidgets.QVBoxLayout(cards)
    cards_layout.setContentsMargins(0, 0, 0, 0)
    window = SimpleNamespace(
        tradePositionCardsLayout=cards_layout,
        trades=[
            {"trade_id": "long", "status": "OPEN", "side": "LONG", "entry_fill_price": 100.0, "notional_quote": 500.0, "entry_bar_index": 1},
            {"trade_id": "short", "status": "OPEN", "side": "SHORT", "entry_fill_price": 100.0, "notional_quote": 500.0, "entry_bar_index": 2},
        ],
    )

    _update_position_panel(window, pd.Series({"close": 110.0}))
    first_cards = [cards_layout.itemAt(index).widget() for index in range(cards_layout.count() - 1)]

    _update_position_panel(window, pd.Series({"close": 120.0}))
    second_cards = [cards_layout.itemAt(index).widget() for index in range(cards_layout.count() - 1)]

    assert [card.property("tradeId") for card in second_cards] == ["long", "short"]
    assert second_cards == first_cards
    long_values = {label.property("field"): label for label in second_cards[0].findChildren(QtWidgets.QLabel) if label.property("field")}
    assert long_values["current"].text() == "120.00"


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
        _current_equity_rows=lambda: (_ for _ in ()).throw(
            AssertionError("light trade refresh must not rebuild the full equity curve")
        ),
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
    assert window.equityTable.rowCount() == 0
    assert window.openTradesTable.item(0, 0).data(QtCore.Qt.UserRole) == "trd_open_1234567890"
