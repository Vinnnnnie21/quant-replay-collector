from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtGui = pytest.importorskip("PySide6.QtGui")
QtCore = pytest.importorskip("PySide6.QtCore")
pytest.importorskip("pyqtgraph")

from ui_style import COLORS, build_app_qss, style_primary_button
from app_i18n import tr as i18n_tr
from views.main_window_layout import build_main_window_ui
from views.date_picker import DatePicker
from views.main_window_presentation import (
    apply_main_window_theme,
    retranslate_main_window_ui,
)


def _qss_block(qss: str, selector: str) -> str:
    start = qss.index(selector)
    end = qss.index("}", start)
    return qss[start:end]


class _RenderState:
    theme_changed = False

    def mark_theme_changed(self) -> None:
        self.theme_changed = True


class _LayoutHost(QtWidgets.QMainWindow):
    current_language = "zh_CN"

    def __init__(self):
        super().__init__()
        self._render_state = _RenderState()
        self._last_rebuild_key = object()
        self._last_marker_sync_key = object()
        self.render_forced = False
        self.shortcut_bindings = []

    def _set_fill_mode_value(self, _value) -> None:
        pass

    def _setup_table(self, table) -> None:
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

    def _add_shortcut(self, sequence, handler) -> None:
        self.shortcut_bindings.append((sequence, handler))

    def toggle_play(self) -> None:
        pass

    def step_once(self) -> None:
        pass

    def speed_down(self) -> None:
        pass

    def speed_up(self) -> None:
        pass

    def toggle_follow(self) -> None:
        pass

    def request_open_trade(self, _side) -> None:
        pass

    def request_close_trade(self, _side) -> None:
        pass

    def undo(self) -> None:
        pass

    def redo(self) -> None:
        pass

    def export_session(self) -> None:
        pass

    def reset_view(self) -> None:
        pass

    def _update_header(self) -> None:
        pass

    def _update_load_play_button(self) -> None:
        pass

    def retranslate_ui(self) -> None:
        retranslate_main_window_ui(self)

    def tr(self, key: str, default: str | None = None) -> str:
        return {
            "reset_view": "重置缩放",
            "reset_view_hint": "仅重置缩放和可视范围，不清空K线数据。",
            "trading_replay": "交易回放",
        }.get(key, i18n_tr(key, self.current_language, default))

    def _chart_render_state(self):
        return self._render_state

    def _render(self, force: bool = False) -> None:
        self.render_forced = force


def test_main_window_layout_builds_existing_primary_widgets():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()

    build_main_window_ui(host)

    assert host.centralWidget() is not None
    assert host.symbolBox.currentText() == "BTCUSDT"
    assert host.intervalBox.currentText() == "1m"
    assert hasattr(host, "btnApplyMarket")
    assert host.btnLoadData is host.btnApplyMarket
    assert host.btnApplyMarket.text() in {"应用行情", "Apply Market"}
    assert not hasattr(host, "btnReloadData")
    assert host.dataBox.parentWidget() is not host.replayWorkspace
    assert host.btnApplyMarket.parentWidget().objectName() == "marketToolbar"
    assert host.headerEquityValue.parentWidget().objectName() == "marketToolbar"
    assert host.headerReturnValue.parentWidget().objectName() == "marketToolbar"
    market_layout = host.btnApplyMarket.parentWidget().layout()
    assert market_layout.indexOf(host.btnApplyMarket) < market_layout.indexOf(host.headerMainLabel)
    assert market_layout.indexOf(host.headerMainLabel) < market_layout.indexOf(host.headerEquityValue)
    assert market_layout.indexOf(host.headerEquityValue) < market_layout.indexOf(host.headerReturnValue)
    assert host.marketDirtyHint is not None
    assert host.marketDirtyHint.isHidden()
    assert host.openTradesTable.columnCount() == 10
    assert host.closedTradesTable.columnCount() == 13
    assert host.eventTable.columnCount() == 8
    assert host.eventStudyTable.columnCount() == 9
    assert host.multiTimeframePanel is not None
    assert getattr(host.headerSymbolValue.parentWidget(), "property")("role") != "metricBlock"
    assert host.headerTitleLabel.text() == "Quant Replay Collector v1.5.0"
    assert "BTCUSDT" in host.headerMainLabel.text()
    assert "1m" in host.headerMainLabel.text()
    assert "O " in host.headerMainLabel.text()
    assert host.headerMainLabel.text().count("|") < 2
    assert host.headerMainLabel.parentWidget().objectName() == "marketToolbar"
    assert host.btnReplayWorkspace.property("role") == "workspaceNavButton"
    assert host.btnAnalysisWorkspace.property("role") == "workspaceNavButton"
    assert not hasattr(host, "btnDepthView")
    assert not hasattr(host, "btnChartSettings")
    assert not hasattr(host, "btnChartFullscreen")
    supported_intervals = {host.intervalBox.itemText(index) for index in range(host.intervalBox.count())}
    assert set(host.chartIntervalButtons) == supported_intervals
    assert isinstance(host.recentEventsList, QtWidgets.QWidget)
    assert not isinstance(host.recentEventsList, QtWidgets.QTableWidget)
    assert host.emptyTradeResults is not None
    assert host.emptyEventStudy is not None
    assert host.btnToggleLog.isChecked()
    assert not host.log.isVisible()
    assert host.speedSlider.minimum() == 0
    assert host.speedSlider.maximum() == 6
    assert host.speedSlider.value() == 3
    assert host.speedLabel.text().endswith("1.0x")
    shortcut_keys = {binding[0] for binding in host.shortcut_bindings}
    assert QtCore.Qt.Key_Left in shortcut_keys
    assert QtCore.Qt.Key_Right in shortcut_keys
    assert "Shift+Right" in shortcut_keys
    assert host.executionSettingsBox.isVisibleTo(host)
    notional_label = next(
        label
        for label in host.executionSettingsBox.findChildren(QtWidgets.QLabel)
        if label.text() == "每笔名义金额"
    )
    assert notional_label.minimumWidth() >= notional_label.fontMetrics().horizontalAdvance(
        notional_label.text()
    )
    assert host.takeProfitPctSpin.minimum() == 0.0
    assert host.stopLossPctSpin.minimum() == 0.0
    assert host.takeProfitPctSpin.specialValueText() == "空"
    assert host.accountOverviewCard is not None
    assert host.accountEquityValue.text() == "-"
    assert host.openPositionsMiniTable.columnCount() == 6
    assert isinstance(host.tradePositionScroll, QtWidgets.QScrollArea)
    assert host.tradePositionScroll.widget() is host.tradePositionCards
    assert host.tradePositionEmptyHost.layout().indexOf(host.tradePositionEmptyState) == 1
    assert [host.closedTradesTable.horizontalHeaderItem(index).text() for index in range(2, 6)] == [
        "开仓时间", "平仓时间", "开仓成交", "平仓成交"
    ]
    assert isinstance(host.startDate, DatePicker)
    assert isinstance(host.endDate, DatePicker)
    trade_page_layout = host.rightTradePage.widget().layout()
    assert trade_page_layout.indexOf(host.tradeCurrentPositionCard) < trade_page_layout.indexOf(host.tradeBox)
    original_start_date = host.startDate.date()
    from PySide6 import QtGui
    wheel_event = QtGui.QWheelEvent(
        QtCore.QPointF(2, 2), QtCore.QPointF(2, 2), QtCore.QPoint(), QtCore.QPoint(0, 120),
        QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.ScrollUpdate, False,
    )
    app.sendEvent(host.startDate, wheel_event)
    assert host.startDate.date() == original_start_date
    host.startDate.setDate(host.endDate.date().addDays(3))
    assert host.endDate.date() == host.startDate.date()
    assert host.pricePlot.getAxis("right").isVisible()
    assert host.barDetailLabels["open"].text() == "开盘价"
    assert host.barDetailLabels["high"].text() == "最高价"
    assert host.barDetailLabels["low"].text() == "最低价"
    assert host.barDetailLabels["close"].text() == "收盘价"
    assert host.barDetailLabels["volume"].text() == "成交量"
    assert host.barDetailLabels["index"].text() == "K线序号"
    assert "Volume" not in {label.text() for label in host.barDetailLabels.values()}
    assert "bar index" not in {label.text() for label in host.barDetailLabels.values()}
    assert host.workspaceStack.currentWidget() is host.replayWorkspace
    assert host.btnReplayWorkspace.isChecked()
    assert host.btnAnalysisWorkspace.text() == "数据分析"
    assert host.rightTabs.tabText(0) == "交易"
    assert host.rightTabs.tabText(1) == "状态"
    assert host.rightTabs.tabText(2) == "标注"
    assert host.rightTabs.currentWidget() is host.rightTradePage
    assert not host.leftSidebar.isVisibleTo(host)
    assert len(host.rightRailButtons) == 3
    assert host.rightPanelRail.isHidden()
    host.btnToggleRightPanel.setChecked(False)
    assert host.rightTabs.isHidden()
    assert not host.rightPanelRail.isHidden()
    assert host.rightPanel.maximumWidth() == 48
    host.btnToggleRightPanel.setChecked(True)
    assert not host.rightTabs.isHidden()
    assert host.rightPanelRail.isHidden()
    assert host.rightPanel.maximumWidth() == 460
    host.multiTimeframePanel.shutdown()
    host.close()
    app.processEvents()


def test_current_price_uses_right_axis_badge_below_candles():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    build_main_window_ui(host)

    try:
        right_axis = host.pricePlot.getAxis("right")

        assert callable(getattr(right_axis, "set_current_price", None))
        assert not hasattr(host, "currentPriceLabel")
        assert host.currentPriceLine.zValue() < host.candleItem.zValue()
    finally:
        host.multiTimeframePanel.shutdown()
        host.close()
        app.processEvents()


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (1920, 1080),
        (1600, 900),
        (1366, 768),
        (1280, 720),
    ],
)
def test_main_window_layout_remains_usable_at_common_window_sizes(width, height):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    build_main_window_ui(host)

    try:
        host.resize(width, height)
        host.show()
        app.processEvents()

        assert host.width() <= width
        assert host.height() <= height

        for widget in (
            host.glw,
            host.btnLoadPlay,
            host.btnApplyMarket,
            host.btnOpenLong,
            host.btnOpenShort,
            host.rightTabs,
            host.bottomTabs,
        ):
            assert widget.isVisibleTo(host)
            assert widget.geometry().width() > 0
            assert widget.geometry().height() > 0

        body_sizes = host.bodySplitter.sizes()
        center_sizes = host.centerSplitter.sizes()
        assert len(body_sizes) == 2
        assert all(size > 0 for size in body_sizes)
        assert len(center_sizes) == 2
        assert all(size > 0 for size in center_sizes)
        assert host.bottomTabs.count() >= 5
        empty_host_rect = host.tradePositionEmptyHost.contentsRect()
        empty_rect = host.tradePositionEmptyState.geometry()
        assert abs(empty_rect.center().y() - empty_host_rect.center().y()) <= 2
    finally:
        host.multiTimeframePanel.shutdown()
        host.close()
        app.processEvents()


def test_main_window_presentation_updates_language_and_theme(monkeypatch):
    import views.main_window_presentation as presentation

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    build_main_window_ui(host)
    monkeypatch.setattr(presentation, "save_theme_settings", lambda _theme: None)

    retranslate_main_window_ui(host)
    apply_main_window_theme(host, {"name": "交易暗色"})

    assert host.btnApplyMarket.text() == "应用行情"
    assert host.btnResetView.text() == "重置缩放 (K)"
    assert "不清空K线" in host.btnResetView.toolTip()
    assert host._render_state.theme_changed is True
    assert host._last_rebuild_key is None
    assert host._last_marker_sync_key is None
    assert host.render_forced is True
    highlight = QtWidgets.QApplication.instance().palette().color(QtGui.QPalette.Highlight)
    highlighted_text = QtWidgets.QApplication.instance().palette().color(QtGui.QPalette.HighlightedText)
    qss = build_app_qss(host.theme_settings)
    assert highlight != QtGui.QColor("#2D7DFF")
    assert highlight != QtGui.QColor("#3B82F6")
    assert highlight != QtGui.QColor("#F0B90B")
    assert highlight == QtGui.QColor(COLORS["selection"])
    assert highlighted_text == QtGui.QColor(COLORS["text_primary"])
    assert COLORS["brand"].lower() != "#f0b90b"
    assert COLORS["crosshair"] != COLORS["brand"]
    assert COLORS["selection"] != COLORS["brand"]
    assert "#2D7DFF" not in qss
    assert "#3B82F6" not in qss
    assert "#F0B90B" not in qss
    assert "rgb(240, 185, 11)" not in qss
    assert "rgba(240,185,11" not in qss
    assert "background-color: {0}".format(COLORS["brand"]) not in _qss_block(qss, "QPushButton {")
    assert "background-color: {0}".format(COLORS["brand"]) not in _qss_block(qss, "QTableWidget {")
    assert COLORS["selection"] in _qss_block(qss, "QTableWidget::item:selected")
    assert COLORS["brand"] not in _qss_block(qss, "QTableWidget::item:selected")
    assert COLORS["brand"] not in _qss_block(qss, "QSlider::sub-page:horizontal")
    assert COLORS["brand"] in _qss_block(qss, 'QPushButton[role="intervalChip"]:checked')
    assert "background-color: {0}".format(COLORS["brand"]) not in style_primary_button()
    host.current_language = "en_US"
    retranslate_main_window_ui(host)
    assert host.btnApplyMarket.text() == "Apply Market"
    assert host.marketDirtyHint.text() == "Market parameters changed. Apply to reload."
    assert host.candleTitleLabel.text() == "Current Candle"
    assert host.barDetailLabels["open"].text() == "Open"
    assert host.barDetailLabels["high"].text() == "High"
    assert host.barDetailLabels["low"].text() == "Low"
    assert host.barDetailLabels["close"].text() == "Close"
    assert host.barDetailLabels["volume"].text() == "Volume"
    assert host.barDetailLabels["index"].text() == "Bar Index"
    host.current_language = "zh_CN"
    retranslate_main_window_ui(host)
    assert host.candleTitleLabel.text() == "当前K线详情"
    assert host.barDetailLabels["volume"].text() == "成交量"
    assert host.barDetailLabels["index"].text() == "K线序号"
    host.multiTimeframePanel.shutdown()
    host.close()
    app.processEvents()
