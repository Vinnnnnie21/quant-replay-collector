from __future__ import annotations

import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pyqtgraph")

from views.main_window_layout import build_main_window_ui
from views.main_window_presentation import (
    apply_main_window_theme,
    retranslate_main_window_ui,
)


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
        }.get(key, default or key)

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
    assert host.openTradesTable.columnCount() == 10
    assert host.closedTradesTable.columnCount() == 13
    assert host.eventTable.columnCount() == 8
    assert host.eventStudyTable.columnCount() == 9
    assert host.multiTimeframePanel is not None
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

    assert host.btnResetView.text() == "重置缩放 (K)"
    assert "不清空K线" in host.btnResetView.toolTip()
    assert host._render_state.theme_changed is True
    assert host._last_rebuild_key is None
    assert host._last_marker_sync_key is None
    assert host.render_forced is True
    host.multiTimeframePanel.shutdown()
    host.close()
    app.processEvents()
