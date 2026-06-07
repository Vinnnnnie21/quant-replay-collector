"""Main-window status and lightweight chart presentation helpers."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore

try:
    from app_config import BJT, DEFAULT_INTERVAL, DEFAULT_SYMBOL
    from market_data import clamp
    from presenters.formatters import fmt_num, short_id
except ImportError:  # pragma: no cover - package import path
    from ..app_config import BJT, DEFAULT_INTERVAL, DEFAULT_SYMBOL
    from ..market_data import clamp
    from .formatters import fmt_num, short_id


def show_market_dirty_feedback(window) -> None:
    window.status.setText(window.tr("market_params_changed"))
    window._update_load_play_button()


def update_load_play_button(window) -> None:
    if not hasattr(window, "btnLoadPlay"):
        return
    if window._loading_data:
        window.btnLoadPlay.setText(window.tr("loading"))
        window.btnLoadPlay.setEnabled(False)
    elif window.df.empty:
        window.btnLoadPlay.setText(window.tr("load_klines"))
        window.btnLoadPlay.setEnabled(True)
    elif window._is_market_params_dirty():
        window.market_dirty = True
        window.btnLoadPlay.setText(window.tr("reload_klines"))
        window.btnLoadPlay.setEnabled(True)
    elif window.playing:
        window.btnLoadPlay.setText(f"{window.tr('pause')} (Space)")
        window.btnLoadPlay.setEnabled(True)
    else:
        window.btnLoadPlay.setText(f"{window.tr('play')} (Space)")
        window.btnLoadPlay.setEnabled(True)


def update_trade_buttons_enabled(window) -> None:
    allowed = window._is_trade_recording_allowed() and not getattr(window, "_trade_transaction_active", False)
    tooltip = "" if allowed else window.tr("trade_disabled_due_to_display_interval")
    for button_name in ("btnOpenLong", "btnOpenShort", "btnCloseLong", "btnCloseShort"):
        button = getattr(window, button_name, None)
        if button is not None:
            button.setEnabled(allowed)
            button.setToolTip(tooltip)


def update_header(window) -> None:
    if not hasattr(window, "headerSymbolValue"):
        return
    symbol = window.symbolBox.currentText().strip().upper() if hasattr(window, "symbolBox") else DEFAULT_SYMBOL
    interval = window.intervalBox.currentText().strip() if hasattr(window, "intervalBox") else DEFAULT_INTERVAL
    total = max(0, len(window.df) - 1)
    close_text = "-"
    time_text = "-"
    if not window.df.empty:
        idx = int(clamp(window.cursor, 0, len(window.df) - 1))
        row = window.df.iloc[idx]
        close_text = fmt_num(row.get("close"))
        time_text = pd.to_datetime(row.get("open_time_bjt")).tz_convert(BJT).strftime("%m-%d %H:%M")
    window.headerSymbolValue.setText(symbol or "-")
    window.headerIntervalValue.setText(interval or "-")
    window.headerCloseValue.setText(close_text)
    window.headerTimeValue.setText(time_text)
    window.headerCursorValue.setText(f"{window.cursor} / {total}")
    window.headerPlayBadge.setText(window.tr("playing") if window.playing else window.tr("paused"))
    window._set_widget_role(window.headerPlayBadge, "pillLive" if window.playing else "pillMuted")
    window.headerViewBadge.setText(window.tr("follow_latest") if window.follow_latest else window.tr("free_view"))
    window._set_widget_role(window.headerViewBadge, "pillLive" if window.follow_latest else "pill")
    short_session = short_id(window.session_id) if window.session_id else "-"
    window.headerSessionBadge.setText(f"{window.tr('session')} {short_session}")
    window._update_load_play_button()
    window._update_trade_buttons_enabled()


def refresh_premium_plot(window) -> None:
    started = time.perf_counter()
    try:
        rows = window.storage.fetch_recent_premium_samples(limit=240)
        if not rows:
            window.premiumBuyCurve.setData([], [])
            window.premiumSellCurve.setData([], [])
            window.premiumAvgCurve.setData([], [])
            return
        frame = pd.DataFrame(rows)
        frame = frame[frame["sample_status"] == "OK"].copy()
        if frame.empty:
            window.premiumBuyCurve.setData([], [])
            window.premiumSellCurve.setData([], [])
            window.premiumAvgCurve.setData([], [])
            return
        x = np.arange(len(frame), dtype=float)
        window.premiumBuyCurve.setData(x, frame["buy_premium_pct"].astype(float).to_numpy())
        window.premiumSellCurve.setData(x, frame["sell_premium_pct"].astype(float).to_numpy())
        window.premiumAvgCurve.setData(x, frame["avg_premium_pct"].astype(float).to_numpy())
    finally:
        log_slow = getattr(window, "_log_slow_operation", None)
        if callable(log_slow):
            log_slow("_refresh_premium_plot", started)


def update_current_price_line(window, vx0: float, vx1: float) -> None:
    if window.df.empty:
        window.currentPriceLine.hide()
        window.currentPriceLabel.hide()
        return
    idx = int(clamp(window.cursor, 0, len(window.df) - 1))
    row = window.df.iloc[idx]
    price = float(row["close"])
    prev_close = float(window.df.iloc[max(0, idx - 1)]["close"]) if idx > 0 else price
    up = price >= prev_close
    line_color = window.theme_settings["current_price_up"] if up else window.theme_settings["current_price_down"]
    text_color = window.theme_settings["current_price_label_text"]
    window.currentPriceLine.setPen(pg.mkPen(line_color, style=QtCore.Qt.DashLine, width=1))
    window.currentPriceLine.setValue(price)
    label_x = vx1 - max(0.05, (vx1 - vx0) * 0.006)
    window.currentPriceLabel.setColor(text_color)
    try:
        window.currentPriceLabel.fill = pg.mkBrush(line_color)
        window.currentPriceLabel.border = pg.mkPen(line_color)
        window.currentPriceLabel.update()
    except Exception:
        pass
    window.currentPriceLabel.setText(f"{price:.4f}")
    window.currentPriceLabel.setPos(label_x, price)
    window.currentPriceLine.show()
    window.currentPriceLabel.show()


__all__ = [
    "refresh_premium_plot",
    "show_market_dirty_feedback",
    "update_current_price_line",
    "update_header",
    "update_load_play_button",
    "update_trade_buttons_enabled",
]
