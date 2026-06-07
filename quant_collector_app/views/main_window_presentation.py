"""Main window language and theme application helpers."""

from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

try:
    from app_config import (
        APP_NAME,
        APP_VERSION,
        DEFAULT_THEME,
        THEME_PRESETS,
        save_theme_settings,
    )
    from ui_style import build_app_qss
except ImportError:  # pragma: no cover - package import path
    from ..app_config import (
        APP_NAME,
        APP_VERSION,
        DEFAULT_THEME,
        THEME_PRESETS,
        save_theme_settings,
    )
    from ..ui_style import build_app_qss


def retranslate_main_window_ui(window) -> None:
    if not hasattr(window, "btnExport"):
        return
    window.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - {window.tr('trading_replay')}")
    for key, label in getattr(window, "headerMetricLabels", {}).items():
        label.setText(window.tr(key))
    for widget_name, key in (
        ("dataBox", "market_data"),
        ("replayBox", "replay_control"),
        ("tradeBox", "trade_actions"),
        ("tagBox", "event_tags_notes"),
        ("toolsBox", "tools"),
    ):
        widget = getattr(window, widget_name, None)
        if widget is not None:
            widget.setTitle(window.tr(key))
    window.btnStep.setText(f"{window.tr('step_next')} (→)")
    window.btnToEnd.setText(window.tr("jump_to_end"))
    window.btnFollow.setText(f"{window.tr('follow_latest')} (F)")
    window.btnResetView.setText(f"{window.tr('reset_view')} (K)")
    window.btnResetView.setToolTip(window.tr("reset_view_hint"))
    window.btnOpenLong.setText(f"{window.tr('open_long')} (B)")
    window.btnOpenShort.setText(f"{window.tr('open_short')} (S)")
    window.btnCloseLong.setText(f"{window.tr('close_long')} (C)")
    window.btnCloseShort.setText(f"{window.tr('close_short')} (X)")
    window.btnUndo.setText(f"{window.tr('undo')} (Ctrl+Z)")
    window.btnRedo.setText(f"{window.tr('redo')} (Ctrl+Y)")
    window.btnClearTradeRecords.setText(window.tr("clear_trade_records"))
    window.btnExport.setText(f"{window.tr('export_session')} (E)")
    window.btnAnalysis.setText(window.tr("data_analysis"))
    window.btnSettings.setText(window.tr("settings"))
    window.rightTabs.setTabText(window.rightTabs.indexOf(window.openTradesTable), window.tr("current_positions"))
    window.rightTabs.setTabText(window.rightTabs.indexOf(window.eventTab), window.tr("events"))
    window.rightTabs.setTabText(
        window.rightTabs.indexOf(window.multiTimeframePanel),
        window.tr("multi_timeframe_context"),
    )
    window.rightTabs.setTabText(window.rightTabs.indexOf(window.detailBox), window.tr("details"))
    window.multiTimeframePanel.retranslate_ui(window.current_language)
    if hasattr(window, "backtestPanel") and hasattr(window.backtestPanel, "retranslate_ui"):
        window.backtestPanel.retranslate_ui()
    if hasattr(window, "strategyConsistencyPanel") and hasattr(window.strategyConsistencyPanel, "retranslate_ui"):
        window.strategyConsistencyPanel.retranslate_ui()
    window._update_header()
    window._update_load_play_button()


def apply_main_window_theme(window, theme: dict) -> None:
    window.theme_settings = dict(DEFAULT_THEME)
    window.theme_settings.update(theme or {})
    if window.theme_settings.get("name") not in THEME_PRESETS:
        window.theme_settings["name"] = DEFAULT_THEME.get("name", "交易暗色")
    app = QtWidgets.QApplication.instance()
    pal = QtGui.QPalette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(window.theme_settings["window_bg"]))
    pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(window.theme_settings["text"]))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor(window.theme_settings["base_bg"]))
    pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(window.theme_settings["panel_bg"]))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor(window.theme_settings["text"]))
    pal.setColor(QtGui.QPalette.Button, QtGui.QColor(window.theme_settings["panel_bg"]))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(window.theme_settings["text"]))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(45, 125, 255))
    pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(0, 0, 0))
    app.setPalette(pal)

    window.setStyleSheet(build_app_qss(window.theme_settings))

    grid_alpha = max(0.0, min(1.0, window.theme_settings["grid_alpha"] / 100.0))
    try:
        window.glw.setBackground(window.theme_settings["base_bg"])
    except Exception:
        pass

    for plot in (window.pricePlot, window.volPlot):
        vb = plot.getViewBox()
        if vb is not None and hasattr(vb, "setBackgroundColor"):
            try:
                vb.setBackgroundColor(window.theme_settings["base_bg"])
            except Exception:
                pass
        plot.showGrid(x=True, y=True, alpha=grid_alpha)
        for side in ("left", "bottom", "right", "top"):
            ax = plot.getAxis(side)
            if ax is not None:
                ax.setPen(pg.mkPen(window.theme_settings["axis"]))
                ax.setTextPen(pg.mkPen(window.theme_settings["axis"]))

    try:
        window.premiumPlot.setBackground(window.theme_settings["base_bg"])
    except Exception:
        pass
    window.premiumPlot.showGrid(x=True, y=True, alpha=grid_alpha)
    premium_item = window.premiumPlot.getPlotItem() if hasattr(window.premiumPlot, "getPlotItem") else None
    if premium_item is not None:
        for side in ("left", "bottom", "right", "top"):
            ax = premium_item.getAxis(side)
            if ax is not None:
                ax.setPen(pg.mkPen(window.theme_settings["axis"]))
                ax.setTextPen(pg.mkPen(window.theme_settings["axis"]))

    window.candleItem._pen_up = pg.mkPen(window.theme_settings["candle_up"])
    window.candleItem._pen_dn = pg.mkPen(window.theme_settings["candle_down"])
    window.candleItem._brush_up = pg.mkBrush(window.theme_settings["candle_up"])
    window.candleItem._brush_dn = pg.mkBrush(window.theme_settings["candle_down"])
    window.candleItem._wick_pen = pg.mkPen(window.theme_settings["wick"])
    window.volItem._brush_up = pg.mkBrush(window.theme_settings["volume_up"])
    window.volItem._brush_dn = pg.mkBrush(window.theme_settings["volume_down"])
    window.scatter_open_long.setBrush(pg.mkBrush(window.theme_settings["candle_up"]))
    window.scatter_open_long.setPen(pg.mkPen(window.theme_settings["candle_up"]))
    window.scatter_open_short.setBrush(pg.mkBrush(window.theme_settings["premium_sell"]))
    window.scatter_open_short.setPen(pg.mkPen(window.theme_settings["premium_sell"]))
    window.scatter_close_long.setBrush(pg.mkBrush("#26C6DA"))
    window.scatter_close_long.setPen(pg.mkPen("#26C6DA"))
    window.scatter_close_short.setBrush(pg.mkBrush(window.theme_settings["premium_avg"]))
    window.scatter_close_short.setPen(pg.mkPen(window.theme_settings["premium_avg"]))
    window.premiumBuyCurve.setPen(
        pg.mkPen(window.theme_settings["premium_buy"], width=1.5, style=QtCore.Qt.DashLine)
    )
    window.premiumSellCurve.setPen(
        pg.mkPen(window.theme_settings["premium_sell"], width=1.5, style=QtCore.Qt.DotLine)
    )
    window.premiumAvgCurve.setPen(pg.mkPen(window.theme_settings["premium_avg"], width=1.8))
    window.candleItem._rebuild()
    window.volItem._rebuild()
    window._last_rebuild_key = None
    window._last_marker_sync_key = None
    window._chart_render_state().mark_theme_changed()
    window._update_header()
    save_theme_settings(window.theme_settings)
    window._render(force=True)


__all__ = ["apply_main_window_theme", "retranslate_main_window_ui"]
