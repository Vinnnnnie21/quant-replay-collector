from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from views.main_window_connections import setup_table
from views.main_window_connections import connect_main_window_signals


class _Signal:
    def __init__(self):
        self.connections = []

    def connect(self, callback, *_args, **_kwargs):
        self.connections.append(callback)


class _Worker:
    def __init__(self):
        self.progress = _Signal()
        self.finished = _Signal()

    def load(self, *_args, **_kwargs):
        pass

    def fetch_once(self, *_args, **_kwargs):
        pass


class _ViewBox:
    def __init__(self):
        self.userInteracted = _Signal()
        self.sigXRangeChanged = _Signal()


class _DummyWindow:
    def __init__(self):
        self.calls = []
        for name in (
            "btnApplyMarket",
            "btnLoadPlay",
            "btnStep",
            "btnToEnd",
            "btnFollow",
            "btnResetView",
            "btnExport",
            "btnAnalysis",
            "btnSettings",
            "btnOpenLong",
            "btnOpenShort",
            "btnCloseLong",
            "btnCloseShort",
            "btnUndo",
            "btnRedo",
            "btnClearTradeRecords",
            "btnToggleDanger",
            "btnApplyEventMeta",
            "btnToggleDetail",
            "btnToggleLog",
        ):
            setattr(self, name, QtWidgets.QPushButton())
        self.symbolSearchEdit = QtWidgets.QLineEdit()
        self.symbolList = QtWidgets.QListWidget()
        self.symbolBox = QtWidgets.QComboBox()
        self.symbolBox.addItem("BTCUSDT")
        self.intervalBox = QtWidgets.QComboBox()
        self.intervalBox.addItems(["1m", "5m"])
        self.chartIntervalButtons = {"1m": QtWidgets.QPushButton(), "5m": QtWidgets.QPushButton()}
        self.startDate = QtWidgets.QDateEdit()
        self.endDate = QtWidgets.QDateEdit()
        self.speedSlider = QtWidgets.QSlider()
        self.fillModeBox = QtWidgets.QComboBox()
        self.feeBpsSpin = QtWidgets.QDoubleSpinBox()
        self.slippageBpsSpin = QtWidgets.QDoubleSpinBox()
        self.tradeNotionalSpin = QtWidgets.QDoubleSpinBox()
        self.initialEquitySpin = QtWidgets.QDoubleSpinBox()
        self.requestLoad = _Signal()
        self.requestPremium = _Signal()
        self.loader = _Worker()
        self.premium_worker = _Worker()
        self.multiTimeframePanel = type("Panel", (), {"loadFailed": _Signal()})()
        self.dangerActions = QtWidgets.QWidget()
        self.vb_price = _ViewBox()
        self.vb_vol = _ViewBox()
        self.openTradesTable = QtWidgets.QTableWidget()
        self.closedTradesTable = QtWidgets.QTableWidget()
        self.eventTable = QtWidgets.QTableWidget()
        self.eventFilterTag = QtWidgets.QComboBox()
        self.eventFilterSide = QtWidgets.QComboBox()
        self.eventFilterType = QtWidgets.QComboBox()

    def _record(self, name, *args):
        self.calls.append((name, args))

    def load_data(self):
        self._record("load_data")

    def load_or_toggle_play(self):
        self._record("load_or_toggle_play")

    def step_once(self): self._record("step_once")
    def jump_to_end(self): self._record("jump_to_end")
    def toggle_follow(self): self._record("toggle_follow")
    def reset_view(self): self._record("reset_view")
    def export_session(self): self._record("export_session")
    def open_analysis_workspace(self): self._record("open_analysis_workspace")
    def open_settings_dialog(self): self._record("open_settings_dialog")
    def request_open_trade(self, side): self._record("request_open_trade", side)
    def request_close_trade(self, side): self._record("request_close_trade", side)
    def undo(self): self._record("undo")
    def redo(self): self._record("redo")
    def confirm_clear_trade_records(self): self._record("confirm_clear_trade_records")
    def apply_labels_to_selected_event(self): self._record("apply_labels_to_selected_event")
    def filter_symbol_list(self, text): self._record("filter_symbol_list", text)
    def on_symbol_item_selected(self, item): self._record("on_symbol_item_selected", item)
    def on_market_params_changed(self, *args): self._record("on_market_params_changed", *args)
    def on_interval_changed_for_dynamic_switch(self, value): self._record("on_interval_changed_for_dynamic_switch", value)
    def on_speed_changed(self, value): self._record("on_speed_changed", value)
    def on_execution_settings_changed(self, *args): self._record("on_execution_settings_changed", *args)
    def on_load_progress(self, message): self._record("on_load_progress", message)
    def on_loaded(self, *args): self._record("on_loaded", *args)
    def on_multi_timeframe_load_failed(self, *args): self._record("on_multi_timeframe_load_failed", *args)
    def on_premium_sample(self, *args): self._record("on_premium_sample", *args)
    def on_user_interaction(self, *args): self._record("on_user_interaction", *args)
    def on_price_view_range_changed(self, *args): self._record("on_price_view_range_changed", *args)
    def on_open_trade_selected(self): self._record("on_open_trade_selected")
    def on_closed_trade_selected(self): self._record("on_closed_trade_selected")
    def on_event_selected(self): self._record("on_event_selected")
    def _refresh_tables(self): self._record("_refresh_tables")
    def jump_to_trade_row(self, item): self._record("jump_to_trade_row", item)
    def jump_to_event_row(self, item): self._record("jump_to_event_row", item)
    def toggle_detail_panel(self, value): self._record("toggle_detail_panel", value)
    def toggle_log_drawer(self, value): self._record("toggle_log_drawer", value)


def test_setup_table_preserves_read_only_single_row_selection_contract():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    table = QtWidgets.QTableWidget()

    setup_table(table)

    assert table.selectionBehavior() == QtWidgets.QAbstractItemView.SelectRows
    assert table.selectionMode() == QtWidgets.QAbstractItemView.SingleSelection
    assert table.editTriggers() == QtWidgets.QAbstractItemView.NoEditTriggers
    assert table.showGrid() is False
    table.close()
    app.processEvents()


def test_market_and_play_buttons_have_separate_connections():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = _DummyWindow()

    connect_main_window_signals(window)
    window.btnApplyMarket.click()
    window.btnLoadPlay.click()
    window.intervalBox.setCurrentText("5m")
    window.chartIntervalButtons["1m"].click()

    assert ("load_data", ()) in window.calls
    assert ("load_or_toggle_play", ()) in window.calls
    assert any(call[0] == "on_market_params_changed" for call in window.calls)
    assert ("on_interval_changed_for_dynamic_switch", ("1m",)) in window.calls
    assert not hasattr(window, "btnReloadData")
    app.processEvents()


def test_visible_main_window_buttons_are_wired_or_stateful():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = _DummyWindow()

    connect_main_window_signals(window)

    click_buttons = (
        "btnApplyMarket",
        "btnLoadPlay",
        "btnStep",
        "btnToEnd",
        "btnFollow",
        "btnResetView",
        "btnExport",
        "btnAnalysis",
        "btnSettings",
        "btnOpenLong",
        "btnOpenShort",
        "btnCloseLong",
        "btnCloseShort",
        "btnUndo",
        "btnRedo",
        "btnClearTradeRecords",
        "btnApplyEventMeta",
    )
    for name in click_buttons:
        assert getattr(window, name).receivers("2clicked()") > 0, name
    for name in ("btnToggleDanger", "btnToggleDetail", "btnToggleLog"):
        assert getattr(window, name).receivers("2toggled(bool)") > 0, name
    for interval, button in window.chartIntervalButtons.items():
        assert button.receivers("2clicked()") > 0, interval
    app.processEvents()
