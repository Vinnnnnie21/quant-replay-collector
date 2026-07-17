from __future__ import annotations

import gc
import importlib
import json
import os
import re
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtGui = pytest.importorskip("PySide6.QtGui")
QtCore = pytest.importorskip("PySide6.QtCore")
pg = pytest.importorskip("pyqtgraph")

from ui_style import COLORS, build_app_qss, style_primary_button
from app_i18n import tr as i18n_tr
from views.main_window_layout import (
    _ManagedPlotWidget,
    _replace_disabled_plot_menu,
    build_main_window_ui,
)
from views.date_picker import DatePicker
from views.nullable_percent_input import NullablePercentInput
from views.main_window_presentation import (
    apply_main_window_theme,
    retranslate_main_window_ui,
)


def _qss_block(qss: str, selector: str) -> str:
    start = qss.index(selector)
    end = qss.index("}", start)
    return qss[start:end]


def _send_wheel(widget: QtWidgets.QWidget, delta: int = -120) -> None:
    local = QtCore.QPointF(widget.rect().center())
    event = QtGui.QWheelEvent(
        local,
        QtCore.QPointF(widget.mapToGlobal(local.toPoint())),
        QtCore.QPoint(),
        QtCore.QPoint(0, delta),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
        QtCore.Qt.ScrollUpdate,
        False,
    )
    QtWidgets.QApplication.sendEvent(widget, event)


class _RenderState:
    theme_changed = False

    def mark_theme_changed(self) -> None:
        self.theme_changed = True


class _LayoutHost(QtWidgets.QMainWindow):
    current_language = "zh_CN"

    def __init__(self):
        super().__init__()
        self._start_multi_timeframe_worker = False
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
        if self.current_language == "zh_CN":
            return {
                "reset_view": "重置缩放",
                "reset_view_hint": "仅重置缩放和可视范围，不清空K线数据。",
                "trading_replay": "交易回放",
            }.get(key, i18n_tr(key, self.current_language, default))
        return i18n_tr(key, self.current_language, default)

    def _chart_render_state(self):
        return self._render_state

    def _render(self, force: bool = False) -> None:
        self.render_forced = force

    def closeEvent(self, event) -> None:
        if hasattr(self, "multiTimeframePanel"):
            self.multiTimeframePanel.shutdown()
        if hasattr(self, "premiumPlot"):
            self.premiumPlot.shutdown()
        if hasattr(self, "glw"):
            self.glw.shutdown()
        event.accept()


def _close_layout_host(host: _LayoutHost, app: QtWidgets.QApplication) -> None:
    destroyed: list[bool] = []
    host.destroyed.connect(lambda: destroyed.append(True))
    assert host.close() is True
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()
    assert destroyed == [True]
    host.__dict__.clear()
    gc.collect()
    app.processEvents()


def _widget_user_texts(root: QtWidgets.QWidget) -> list[str]:
    texts: list[str] = []
    for widget in (root, *root.findChildren(QtWidgets.QWidget)):
        if isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
            texts.append(widget.text())
        if isinstance(widget, QtWidgets.QGroupBox):
            texts.append(widget.title())
        if isinstance(widget, QtWidgets.QTabWidget):
            texts.extend(widget.tabText(index) for index in range(widget.count()))
        if isinstance(widget, QtWidgets.QComboBox):
            texts.extend(widget.itemText(index) for index in range(widget.count()))
        if isinstance(widget, QtWidgets.QTableWidget):
            for index in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(index)
                if item is not None:
                    texts.append(item.text())
        if isinstance(widget, QtWidgets.QLineEdit):
            texts.append(widget.placeholderText())
        texts.extend((widget.toolTip(), widget.statusTip()))
    return sorted({text.strip() for text in texts if text and text.strip()})


def test_english_main_window_has_no_chinese_user_interface_text():
    class EnglishLayoutHost(_LayoutHost):
        current_language = "en_US"

        def tr(self, key: str, default: str | None = None) -> str:
            return i18n_tr(key, self.current_language, default)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = EnglishLayoutHost()
    try:
        build_main_window_ui(host)
        retranslate_main_window_ui(host)

        chinese_texts = [
            text for text in _widget_user_texts(host) if re.search(r"[\u3400-\u9fff]", text)
        ]

        assert chinese_texts == []
    finally:
        _close_layout_host(host, app)


def test_switching_main_window_to_english_retranslates_all_visible_user_interface_text():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    try:
        build_main_window_ui(host)
        host.current_language = "en_US"
        retranslate_main_window_ui(host)

        chinese_texts = [
            text for text in _widget_user_texts(host) if re.search(r"[\u3400-\u9fff]", text)
        ]

        assert chinese_texts == []
    finally:
        _close_layout_host(host, app)


def test_chinese_main_window_has_no_raw_translation_keys_or_english_actions():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    try:
        build_main_window_ui(host)
        retranslate_main_window_ui(host)

        texts = _widget_user_texts(host)
        translation_keys = set(
            json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "quant_collector_app"
                    / "translations"
                    / "zh_CN.json"
                ).read_text(encoding="utf-8")
            )
        )
        forbidden_actions = {
            "Trading Replay",
            "Data Analysis",
            "Apply Market",
            "Play (Space)",
            "Step Next (→)",
            "Open Long (B)",
            "Trade Actions",
            "Trade Data Management",
        }

        assert sorted(set(texts).intersection(translation_keys)) == []
        assert sorted(set(texts).intersection(forbidden_actions)) == []
    finally:
        _close_layout_host(host, app)


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
    assert host.headerLogoLabel.text() == ""
    assert host.headerLogoLabel.pixmap() is not None
    assert not host.headerLogoLabel.pixmap().isNull()
    assert host.headerLogoLabel.width() == host.headerLogoLabel.height()
    assert host.headerTitleLabel.text() == "Quant Replay Collector v1.5.2"
    header_layout = host.headerBar.layout()
    assert header_layout.indexOf(host.headerLogoLabel) < header_layout.indexOf(host.headerTitleLabel)
    assert header_layout.indexOf(host.headerTitleLabel) < header_layout.indexOf(host.btnReplayWorkspace)
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
    assert isinstance(host.replayPerformanceSessionBox, QtWidgets.QComboBox)
    assert host.btnContinuePerformanceSession.property("role") == "secondaryButton"
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
    assert isinstance(host.takeProfitPctSpin, NullablePercentInput)
    assert isinstance(host.stopLossPctSpin, NullablePercentInput)
    assert host.takeProfitPctSpin.value() is None
    assert host.stopLossPctSpin.value() is None
    assert host.takeProfitPctSpin.text() == ""
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
    assert host.dangerBox.title() == "交易数据管理"
    assert host.btnToggleDanger.text() == "交易数据管理"
    assert host.dangerActions.isHidden()
    assert isinstance(host.tradeManagementSessionBox, QtWidgets.QComboBox)
    assert isinstance(host.tradeManagementSessionTradeTable, QtWidgets.QTableWidget)
    assert host.tradeManagementSessionTradeTable.columnCount() == 10
    assert host.btnDeleteSessionTrade.property("role") == "dangerGhostButton"
    assert isinstance(host.tradeManagementStart, QtWidgets.QDateTimeEdit)
    assert isinstance(host.tradeManagementEnd, QtWidgets.QDateTimeEdit)
    assert bytes(host.tradeManagementStart.dateTime().timeZone().id()) == b"Asia/Shanghai"
    assert bytes(host.tradeManagementEnd.dateTime().timeZone().id()) == b"Asia/Shanghai"
    assert isinstance(host.tradeManagementCandidateBox, QtWidgets.QComboBox)
    assert host.btnPreviewTradeRange.text() == "预览时间段"
    assert host.btnPreviewTradeRange.property("role") == "secondaryButton"
    assert host.btnDeleteTradeRange.text() == "删除时间段交易数据"
    assert host.btnDeleteTradeRange.property("role") == "dangerGhostButton"
    assert host.btnDeleteSelectedTrade.text() == "删除选中交易样本"
    assert host.btnDeleteSelectedTrade.property("role") == "dangerGhostButton"
    assert host.btnClearTradeRecords.text() == "清空全部交易样本"
    assert host.btnClearTradeRecords.property("role") == "dangerGhostButton"
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
    assert host.pricePlot.ctrlMenu.parent() is host.glw
    assert host.volPlot.ctrlMenu.parent() is host.glw
    assert not isinstance(host.pricePlot.ctrlMenu, QtWidgets.QMenu)
    assert not isinstance(host.volPlot.ctrlMenu, QtWidgets.QMenu)
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
    _close_layout_host(host, app)


def test_main_window_core_value_inputs_do_not_change_on_wheel():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    build_main_window_ui(host)
    controls = (
        (host.startDate, host.startDate.date),
        (host.endDate, host.endDate.date),
        (host.tradeManagementStart, host.tradeManagementStart.dateTime),
        (host.tradeManagementEnd, host.tradeManagementEnd.dateTime),
        (host.feeBpsSpin, host.feeBpsSpin.value),
        (host.slippageBpsSpin, host.slippageBpsSpin.value),
        (host.tradeNotionalSpin, host.tradeNotionalSpin.value),
        (host.initialEquitySpin, host.initialEquitySpin.value),
        (host.takeProfitPctSpin, host.takeProfitPctSpin.value),
        (host.stopLossPctSpin, host.stopLossPctSpin.value),
    )

    try:
        before = [getter() for _control, getter in controls]
        for control, _getter in controls:
            _send_wheel(control)
        assert [getter() for _control, getter in controls] == before
    finally:
        _close_layout_host(host, app)


def test_main_window_sidebar_uses_global_scrollbar_theme_without_inline_override():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    build_main_window_ui(host)

    try:
        right_controls = host.rightTradePage
        assert right_controls.styleSheet() == ""
        host.resize(1280, 720)
        host.show()
        right_controls.widget().setMinimumHeight(900)
        app.processEvents()
        assert right_controls.verticalScrollBar().maximum() > 0
    finally:
        _close_layout_host(host, app)


def test_kline_chart_viewport_still_receives_wheel_events():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    build_main_window_ui(host)

    class WheelObserver(QtCore.QObject):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.count = 0

        def eventFilter(self, watched, event):  # noqa: N802 - Qt override
            if event.type() == QtCore.QEvent.Wheel:
                self.count += 1
            return False

    observer = WheelObserver(host)
    viewport = host.glw.viewport()
    viewport.installEventFilter(observer)

    try:
        _send_wheel(viewport)
        assert observer.count == 1
    finally:
        _close_layout_host(host, app)


def test_closing_layout_host_explicitly_shuts_down_pyqtgraph_scene():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _LayoutHost()
    build_main_window_ui(host)
    price_plot = host.pricePlot
    volume_plot = host.volPlot
    destroyed: list[bool] = []
    host.destroyed.connect(lambda: destroyed.append(True))

    assert host.testAttribute(QtCore.Qt.WA_DeleteOnClose) is True

    host.multiTimeframePanel.shutdown()
    host.close()
    assert host.glw.closed is True
    assert price_plot.ctrlMenu is None
    assert volume_plot.ctrlMenu is None
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()
    assert destroyed == [True]
    host.__dict__.clear()
    price_plot = None
    volume_plot = None
    gc.collect()
    app.processEvents()


def test_disabled_plot_menu_releases_native_menu_without_deferred_delete():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plot = pg.PlotItem()
    owner = pg.PlotWidget(plotItem=plot)
    original_menu = plot.ctrlMenu
    destroyed: list[bool] = []
    original_menu.destroyed.connect(lambda: destroyed.append(True))

    _replace_disabled_plot_menu(plot, owner)
    owner.show()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()

    # Retaining the Python wrapper proves replacement did not queue a competing
    # DeferredDelete. Normal wrapper ownership releases it once this reference
    # is dropped.
    assert destroyed == []
    assert plot.ctrlMenu is not original_menu
    assert not isinstance(plot.ctrlMenu, QtWidgets.QMenu)
    assert plot.ctrlMenu.parent() is owner
    assert plot.ctrlMenu.isEnabled() is False
    assert plot.ctrlMenu.actions() == []
    assert plot.ctrl.gridAlphaSlider is not None

    original_menu = None
    gc.collect()
    app.processEvents()
    assert destroyed == [True]

    owner.close()
    owner.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    app.processEvents()


def test_disabled_plot_widget_does_not_construct_a_native_qmenu(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    plot_item_module = importlib.import_module(
        "pyqtgraph.graphicsItems.PlotItem.PlotItem"
    )
    native_qmenu = plot_item_module.QtWidgets.QMenu
    constructions: list[bool] = []

    class CountingMenu(native_qmenu):
        def __init__(self, *args, **kwargs):
            constructions.append(True)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(plot_item_module.QtWidgets, "QMenu", CountingMenu)
    plot = _ManagedPlotWidget()

    assert constructions == []
    assert not isinstance(plot.plotItem.ctrlMenu, native_qmenu)

    plot.shutdown()
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_ignored_close_keeps_pyqtgraph_scene_alive():
    class _IgnoreCloseHost(_LayoutHost):
        ignore_close = True

        def closeEvent(self, event):
            if self.ignore_close:
                event.ignore()
                return
            super().closeEvent(event)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = _IgnoreCloseHost()
    build_main_window_ui(host)
    host.show()
    app.processEvents()

    try:
        assert host.close() is False
        app.processEvents()

        assert host.isVisible() is True
        assert host.glw.closed is False
        assert host.pricePlot.ctrlMenu is not None
        assert host.volPlot.ctrlMenu is not None
        assert host.pricePlot.getViewBox() is host.vb_price
        assert host.volPlot.getViewBox() is host.vb_vol
    finally:
        host.ignore_close = False
        _close_layout_host(host, app)


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
        _close_layout_host(host, app)


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
        _close_layout_host(host, app)


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
    assert host.btnContinuePerformanceSession.text() == "Continue Session"
    assert host.tradeManagementSessionLabel.text() == "By Performance Session"
    assert host.tradeManagementRangeLabel.text() == "By Replay Time Range"
    host.current_language = "zh_CN"
    retranslate_main_window_ui(host)
    assert host.candleTitleLabel.text() == "当前K线详情"
    assert host.barDetailLabels["volume"].text() == "成交量"
    assert host.barDetailLabels["index"].text() == "K线序号"
    _close_layout_host(host, app)
