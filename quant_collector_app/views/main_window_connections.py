"""Qt-only MainWindow table, shortcut and signal wiring helpers."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


def setup_table(table: QtWidgets.QTableWidget) -> None:
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustIgnored)
    table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    table.setMinimumWidth(0)
    table.verticalHeader().setDefaultSectionSize(28)
    header = table.horizontalHeader()
    header.setStretchLastSection(True)
    header.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    header.setMinimumSectionSize(56)
    header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)


def focus_is_text_entry() -> bool:
    widget = QtWidgets.QApplication.focusWidget()
    text_widgets = (
        QtWidgets.QLineEdit,
        QtWidgets.QTextEdit,
        QtWidgets.QPlainTextEdit,
        QtWidgets.QSpinBox,
        QtWidgets.QDoubleSpinBox,
        QtWidgets.QComboBox,
        QtWidgets.QDateEdit,
    )
    while widget is not None:
        if isinstance(widget, text_widgets):
            return True
        widget = widget.parentWidget()
    return False


def add_window_shortcut(window, sequence, handler):
    shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), window)
    shortcut.setContext(QtCore.Qt.WindowShortcut)

    def guarded_handler():
        if window._focus_is_text_entry():
            return
        handler()

    shortcut.activated.connect(guarded_handler)
    window._shortcuts.append(shortcut)
    return shortcut


def connect_main_window_signals(window) -> None:
    if hasattr(window, "btnApplyMarket"):
        window.btnApplyMarket.clicked.connect(window.load_data)
    window.btnLoadPlay.clicked.connect(window.load_or_toggle_play)
    window.btnStep.clicked.connect(window.step_once)
    window.btnToEnd.clicked.connect(window.jump_to_end)
    window.btnFollow.clicked.connect(window.toggle_follow)
    window.btnResetView.clicked.connect(window.reset_view)
    window.btnExport.clicked.connect(window.export_session)
    window.btnAnalysis.clicked.connect(window.open_analysis_workspace)
    window.btnSettings.clicked.connect(window.open_settings_dialog)
    window.btnOpenLong.clicked.connect(lambda: window.request_open_trade("LONG"))
    window.btnOpenShort.clicked.connect(lambda: window.request_open_trade("SHORT"))
    window.btnCloseLong.clicked.connect(lambda: window.request_close_trade("LONG"))
    window.btnCloseShort.clicked.connect(lambda: window.request_close_trade("SHORT"))
    window.btnUndo.clicked.connect(window.undo)
    window.btnRedo.clicked.connect(window.redo)
    window.btnClearTradeRecords.clicked.connect(window.confirm_clear_trade_records)
    if hasattr(window, "btnToggleDanger"):
        window.btnToggleDanger.toggled.connect(window.dangerActions.setVisible)
        window.btnToggleDanger.toggled.connect(
            lambda checked: window.btnToggleDanger.setText("隐藏危险操作" if checked else "显示危险操作")
        )
    window.btnApplyEventMeta.clicked.connect(window.apply_labels_to_selected_event)
    window.symbolSearchEdit.textChanged.connect(window.filter_symbol_list)
    window.symbolList.itemClicked.connect(window.on_symbol_item_selected)
    window.symbolList.itemActivated.connect(window.on_symbol_item_selected)
    window.symbolBox.currentTextChanged.connect(window.on_market_params_changed)
    window.intervalBox.currentTextChanged.connect(window.on_market_params_changed)
    for interval, button in getattr(window, "chartIntervalButtons", {}).items():
        def switch_chart_interval(_checked=False, value=interval):
            blocked = window.intervalBox.blockSignals(True)
            window.intervalBox.setCurrentText(value)
            window.intervalBox.blockSignals(blocked)
            window.on_interval_changed_for_dynamic_switch(value)

        button.clicked.connect(switch_chart_interval)
    window.startDate.dateChanged.connect(window.on_market_params_changed)
    window.endDate.dateChanged.connect(window.on_market_params_changed)
    window.speedSlider.valueChanged.connect(window.on_speed_changed)
    for widget in (
        window.fillModeBox,
        window.feeBpsSpin,
        window.slippageBpsSpin,
        window.tradeNotionalSpin,
        window.initialEquitySpin,
    ):
        try:
            widget.valueChanged.connect(window.on_execution_settings_changed)
        except AttributeError:
            widget.currentTextChanged.connect(window.on_execution_settings_changed)
    window.requestLoad.connect(window.loader.load, QtCore.Qt.QueuedConnection)
    window.loader.progress.connect(window.on_load_progress)
    window.loader.finished.connect(window.on_loaded)
    window.multiTimeframePanel.loadFailed.connect(window.on_multi_timeframe_load_failed)
    window.requestPremium.connect(window.premium_worker.fetch_once, QtCore.Qt.QueuedConnection)
    window.premium_worker.finished.connect(window.on_premium_sample)
    window.vb_price.userInteracted.connect(window.on_user_interaction)
    window.vb_vol.userInteracted.connect(window.on_user_interaction)
    window.vb_price.sigXRangeChanged.connect(window.on_price_view_range_changed)
    window.openTradesTable.itemSelectionChanged.connect(window.on_open_trade_selected)
    window.closedTradesTable.itemSelectionChanged.connect(window.on_closed_trade_selected)
    window.eventTable.itemSelectionChanged.connect(window.on_event_selected)
    window.eventFilterTag.currentTextChanged.connect(lambda _text: window._refresh_tables())
    window.eventFilterSide.currentIndexChanged.connect(lambda _index: window._refresh_tables())
    window.eventFilterType.currentIndexChanged.connect(lambda _index: window._refresh_tables())
    window.openTradesTable.itemDoubleClicked.connect(lambda item: window.jump_to_trade_row(item))
    window.closedTradesTable.itemDoubleClicked.connect(lambda item: window.jump_to_trade_row(item))
    window.eventTable.itemDoubleClicked.connect(lambda item: window.jump_to_event_row(item))
    window.btnToggleDetail.toggled.connect(window.toggle_detail_panel)
    window.btnToggleLog.toggled.connect(window.toggle_log_drawer)


__all__ = [
    "add_window_shortcut",
    "connect_main_window_signals",
    "focus_is_text_entry",
    "setup_table",
]
