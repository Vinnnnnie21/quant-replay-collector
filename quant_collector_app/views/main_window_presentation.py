"""Main window language and theme application helpers."""

from __future__ import annotations

from pathlib import Path

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
    from ui_style import (
        LOCAL_STYLE_BUTTON_ROLES,
        build_app_qss,
        normalize_theme_settings,
        role_button_local_qss,
        themed_input_qss,
    )
    from views.widget_effects import apply_button_shadow, apply_role_button_shadows
except ImportError:  # pragma: no cover - package import path
    from ..app_config import (
        APP_NAME,
        APP_VERSION,
        DEFAULT_THEME,
        THEME_PRESETS,
        save_theme_settings,
    )
    from ..ui_style import (
        LOCAL_STYLE_BUTTON_ROLES,
        build_app_qss,
        normalize_theme_settings,
        role_button_local_qss,
        themed_input_qss,
    )
    from .widget_effects import apply_button_shadow, apply_role_button_shadows


def _set_tab_text(tabs: QtWidgets.QTabWidget, widget: QtWidgets.QWidget | None, text: str) -> None:
    if widget is None:
        return
    index = tabs.indexOf(widget)
    if index >= 0:
        tabs.setTabText(index, text)


def retranslate_main_window_ui(window) -> None:
    if not hasattr(window, "btnExport"):
        return
    window.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - {window.tr('trading_replay')}")
    header_defaults = {
        "symbol": window.tr("symbol", "品种"),
        "time_interval": window.tr("display_interval", "显示周期"),
        "sample_interval": window.tr("sample_interval", "样本周期"),
        "kline_time": window.tr("kline_time", "当前K线"),
        "ohlc": "O/H/L/C",
        "change": "涨跌",
    }
    for key, label in getattr(window, "headerMetricLabels", {}).items():
        label.setText(header_defaults.get(key, window.tr(key)))
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
    if hasattr(window, "btnApplyMarket"):
        window.btnApplyMarket.setText(window.tr("apply_market"))
    if hasattr(window, "marketDirtyHint"):
        window.marketDirtyHint.setText(window.tr("market_params_dirty_hint"))
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

    if hasattr(window, "rightTabs"):
        _set_tab_text(window.rightTabs, getattr(window, "multiTimeframePanel", None), window.tr("multi_timeframe_context"))
        _set_tab_text(window.rightTabs, getattr(window, "detailBox", None), window.tr("details"))
    if hasattr(window, "candleTitleLabel"):
        window.candleTitleLabel.setText(window.tr("current_bar_details"))
    if hasattr(window, "barDetailLabels"):
        for key, label_key in (
            ("time", "bar_time"),
            ("open", "bar_open"),
            ("high", "bar_high"),
            ("low", "bar_low"),
            ("close", "bar_close"),
            ("volume", "bar_volume"),
            ("index", "bar_index"),
        ):
            label = window.barDetailLabels.get(key)
            if label is not None:
                label.setText(window.tr(label_key))
    if hasattr(window, "bottomTabs"):
        for index, text in enumerate(
            ("持仓与成交", "账户收益", window.tr("trading_performance"), window.tr("event_study"), "样本概览")
        ):
            if index < window.bottomTabs.count():
                window.bottomTabs.setTabText(index, text)
    if hasattr(window, "tradeResultsTabs"):
        for index, text in enumerate((window.tr("current_positions"), window.tr("closed_trades"))):
            if index < window.tradeResultsTabs.count():
                window.tradeResultsTabs.setTabText(index, text)
    if hasattr(window, "eventResearchTabs"):
        for index, text in enumerate((window.tr("event_study"), window.tr("events"))):
            if index < window.eventResearchTabs.count():
                window.eventResearchTabs.setTabText(index, text)
    window.multiTimeframePanel.retranslate_ui(window.current_language)
    if hasattr(window, "backtestPanel") and hasattr(window.backtestPanel, "retranslate_ui"):
        window.backtestPanel.retranslate_ui()
    if hasattr(window, "strategyConsistencyPanel") and hasattr(window.strategyConsistencyPanel, "retranslate_ui"):
        window.strategyConsistencyPanel.retranslate_ui()
    window._update_header()
    window._update_load_play_button()


def apply_role_button_styles(root, theme: dict) -> int:
    """Set a LOCAL stylesheet on every role button beneath ``root``.

    Window-level QSS paints these buttons' border/text/radius but not their
    background fill in deep widget trees on Fusion; a local stylesheet forces the
    fill to render. Returns the number of buttons styled (handy for tests).
    """
    if root is None:
        return 0
    count = 0
    for widget_cls, selector in ((QtWidgets.QPushButton, "QPushButton"), (QtWidgets.QToolButton, "QToolButton")):
        try:
            controls = root.findChildren(widget_cls)
        except Exception:
            continue
        for button in controls:
            try:
                role = button.property("role")
                if role in LOCAL_STYLE_BUTTON_ROLES:
                    button.setStyleSheet(role_button_local_qss(role, theme, widget=selector))
                    count += 1
            except Exception:
                continue
    return count


def apply_themed_input_styles(root, theme: dict) -> int:
    """Give combo boxes, date editors and event-tag checkboxes the same dark pill
    look via a LOCAL stylesheet (window-level QSS does not paint their fill on
    Fusion). Returns the number of controls styled."""
    if root is None:
        return 0
    count = 0
    try:
        for combo in root.findChildren(QtWidgets.QComboBox):
            combo.setStyleSheet(themed_input_qss("combo", theme))
            apply_button_shadow(combo, blur=12, y_offset=2, alpha=120)
            count += 1
        for date_edit in root.findChildren(QtWidgets.QDateEdit):
            date_edit.setStyleSheet(themed_input_qss("date", theme))
            apply_button_shadow(date_edit, blur=12, y_offset=2, alpha=120)
            count += 1
        for check in root.findChildren(QtWidgets.QCheckBox):
            if check.property("role") == "tagChip":
                check.setStyleSheet(themed_input_qss("tagcheck", theme))
                count += 1
        for line_edit in root.findChildren(QtWidgets.QLineEdit):
            if line_edit.property("role") == "searchInput":
                line_edit.setStyleSheet(themed_input_qss("lineedit", theme))
                apply_button_shadow(line_edit, blur=12, y_offset=2, alpha=120)
                count += 1
    except Exception:
        return count
    return count


def apply_main_window_theme(window, theme: dict) -> None:
    tokens = normalize_theme_settings(theme or DEFAULT_THEME)
    window.theme_settings = tokens
    if window.theme_settings.get("name") not in THEME_PRESETS:
        window.theme_settings["name"] = DEFAULT_THEME.get("name", "交易暗色")
    app = QtWidgets.QApplication.instance()
    pal = QtGui.QPalette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(tokens["bg_primary"]))
    pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(tokens["text_primary"]))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor(tokens["bg_input"]))
    pal.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(tokens["bg_secondary"]))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor(tokens["text_primary"]))
    pal.setColor(QtGui.QPalette.Button, QtGui.QColor(tokens["bg_card"]))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(tokens["text_primary"]))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(tokens["selection"]))
    pal.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(tokens["text_primary"]))
    pal.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(tokens["text_tertiary"]))
    app.setPalette(pal)

    window.setStyleSheet(build_app_qss(window.theme_settings))
    # A window-level stylesheet does not reliably paint QPushButton backgrounds in
    # deep trees on Fusion; set the fill via a LOCAL stylesheet on each role button.
    apply_role_button_styles(window, window.theme_settings)
    apply_themed_input_styles(window, window.theme_settings)
    # Local stylesheet first, THEN the drop shadow (safe only over a local fill).
    apply_role_button_shadows(window)

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
    window.scatter_close_long.setBrush(pg.mkBrush(window.theme_settings["marker_close_long"]))
    window.scatter_close_long.setPen(pg.mkPen(window.theme_settings["marker_close_long"]))
    window.scatter_close_short.setBrush(pg.mkBrush(window.theme_settings["marker_close_short"]))
    window.scatter_close_short.setPen(pg.mkPen(window.theme_settings["marker_close_short"]))
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


def _palette_hex(widget: QtWidgets.QWidget, role: QtGui.QPalette.ColorRole) -> str:
    return widget.palette().color(role).name().upper()


def dump_widget_theme(window: QtWidgets.QWidget, output_path: str | Path | None = None) -> str:
    names = (
        "appRoot",
        "headerBar",
        "leftSidebar",
        "sidebarScroll",
        "sidebarScrollViewport",
        "sidebarContent",
        "marketSection",
        "chartCard",
        "rightPanel",
        "currentStatusCard",
        "bottomTabs",
        "logDrawer",
    )
    lines: list[str] = []
    for name in names:
        widget = window.findChild(QtWidgets.QWidget, name)
        if widget is None:
            lines.append(f"objectName={name} missing=True")
            continue
        parent = widget.parentWidget()
        lines.append(
            " ".join(
                (
                    f"objectName={widget.objectName() or '-'}",
                    f"class={widget.metaObject().className()}",
                    f"role={widget.property('role') or '-'}",
                    f"paletteWindow={_palette_hex(widget, QtGui.QPalette.Window)}",
                    f"paletteBase={_palette_hex(widget, QtGui.QPalette.Base)}",
                    f"paletteButton={_palette_hex(widget, QtGui.QPalette.Button)}",
                    f"autoFillBackground={widget.autoFillBackground()}",
                    f"localStyleSheet={bool(widget.styleSheet())}",
                    f"parent={parent.objectName() if parent is not None and parent.objectName() else '-'}",
                )
            )
        )
    dump = "\n".join(lines) + "\n"
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump, encoding="utf-8")
    return dump


__all__ = ["apply_main_window_theme", "dump_widget_theme", "retranslate_main_window_ui"]
