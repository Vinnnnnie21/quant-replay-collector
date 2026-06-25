from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtGui = pytest.importorskip("PySide6.QtGui")
pytest.importorskip("pyqtgraph")

from ui_style import COLORS, build_app_qss, style_primary_button
from app_i18n import tr as i18n_tr
from views.main_window_layout import build_main_window_ui
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

    def _set_fill_mode_value(self, _value) -> None:
        pass

    def _setup_table(self, table) -> None:
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

    def _add_shortcut(self, *_args) -> None:
        pass

    def toggle_play(self) -> None:
        pass

    def step_once(self) -> None:
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
    market_buttons = [
        button
        for button in host.dataBox.findChildren(QtWidgets.QPushButton)
        if not button.isHidden()
    ]
    assert market_buttons == [host.btnApplyMarket]
    assert host.marketDirtyHint is not None
    assert host.marketDirtyHint.isHidden()
    assert host.openTradesTable.columnCount() == 10
    assert host.closedTradesTable.columnCount() == 13
    assert host.eventTable.columnCount() == 8
    assert host.eventStudyTable.columnCount() == 9
    assert host.multiTimeframePanel is not None
    assert getattr(host.headerSymbolValue.parentWidget(), "property")("role") != "metricBlock"
    assert host.headerTitleLabel.text() == "Quant Replay Collector v1.4.1"
    assert "BTCUSDT" in host.headerMainLabel.text()
    assert "1m" in host.headerMainLabel.text()
    assert "O " in host.headerMainLabel.text()
    assert host.headerMainLabel.text().count("|") < 2
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
    assert host.barDetailLabels["open"].text() == "开盘价"
    assert host.barDetailLabels["high"].text() == "最高价"
    assert host.barDetailLabels["low"].text() == "最低价"
    assert host.barDetailLabels["close"].text() == "收盘价"
    assert host.barDetailLabels["volume"].text() == "成交量"
    assert host.barDetailLabels["index"].text() == "K线序号"
    assert "Volume" not in {label.text() for label in host.barDetailLabels.values()}
    assert "bar index" not in {label.text() for label in host.barDetailLabels.values()}
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
            host.dataBox,
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
        assert len(body_sizes) == 3
        assert all(size > 0 for size in body_sizes)
        assert len(center_sizes) == 2
        assert all(size > 0 for size in center_sizes)
        assert host.bottomTabs.count() >= 5
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
