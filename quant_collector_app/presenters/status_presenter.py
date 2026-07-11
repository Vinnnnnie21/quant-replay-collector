"""Main-window status and lightweight chart presentation helpers."""

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

try:
    from app_config import BJT, DEFAULT_INTERVAL, DEFAULT_SYMBOL
    from analytics.metrics import max_drawdown, payoff_ratio, profit_factor, sharpe_ratio
    from market_data import clamp
    from presenters.formatters import fmt_num, safe_float, short_id
except ImportError:  # pragma: no cover - package import path
    from ..app_config import BJT, DEFAULT_INTERVAL, DEFAULT_SYMBOL
    from ..analytics.metrics import max_drawdown, payoff_ratio, profit_factor, sharpe_ratio
    from ..market_data import clamp
    from .formatters import fmt_num, safe_float, short_id


def _set_label_role(label, role: str) -> None:
    if label is None:
        return
    label.setProperty("role", role)
    style = label.style()
    if style is not None:
        style.unpolish(label)
        style.polish(label)
    label.update()


def _set_text_if_present(window, attr: str, text: str) -> None:
    widget = getattr(window, attr, None)
    if widget is not None:
        widget.setText(text)


def _format_bar_time(value) -> str:
    try:
        return pd.to_datetime(value).tz_convert(BJT).strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "-"


def _current_row(window):
    if window.df.empty:
        return None, 0
    idx = int(clamp(window.cursor, 0, len(window.df) - 1))
    return window.df.iloc[idx], idx


def _update_current_bar_panel(window, row, idx: int) -> None:
    if row is None:
        for attr in (
            "barTimeValue",
            "barOpenValue",
            "barHighValue",
            "barLowValue",
            "barCloseValue",
            "barVolumeValue",
            "barIndexValue",
        ):
            _set_text_if_present(window, attr, "-")
        return
    _set_text_if_present(window, "barTimeValue", _format_bar_time(row.get("open_time_bjt")))
    _set_text_if_present(window, "barOpenValue", fmt_num(row.get("open")))
    _set_text_if_present(window, "barHighValue", fmt_num(row.get("high")))
    _set_text_if_present(window, "barLowValue", fmt_num(row.get("low")))
    _set_text_if_present(window, "barCloseValue", fmt_num(row.get("close")))
    _set_label_role(getattr(window, "barCloseValue", None), "valueAccent")
    _set_text_if_present(window, "barVolumeValue", fmt_num(row.get("volume")))
    _set_text_if_present(window, "barIndexValue", str(row.get("bar_index", idx)))


def _entry_price(trade: dict) -> float:
    value = trade.get("entry_fill_price")
    if value is None:
        value = trade.get("entry_price_proxy")
    return safe_float(value, default=float("nan"))


def _spin_float(window, attr: str, default: float) -> float:
    widget = getattr(window, attr, None)
    if widget is None or not hasattr(widget, "value"):
        return float(default)
    try:
        value = float(widget.value())
    except (TypeError, ValueError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def _trade_notional(trade: dict, default_notional: float) -> float:
    value = safe_float(trade.get("notional_quote"), default=default_notional)
    return value if math.isfinite(value) and value > 0 else max(0.0, default_notional)


def _trade_net_pnl(trade: dict, default_notional: float) -> float:
    value = safe_float(trade.get("net_pnl_quote"), default=float("nan"))
    if math.isfinite(value):
        return value
    ret = safe_float(trade.get("net_return_pct"), default=float("nan"))
    if not math.isfinite(ret):
        ret = safe_float(trade.get("final_return_pct"), default=0.0)
    return ret / 100.0 * _trade_notional(trade, default_notional)


def _floating_pnl(trade: dict, current_price: float, default_notional: float) -> float:
    entry = _entry_price(trade)
    notional = _trade_notional(trade, default_notional)
    if not math.isfinite(entry) or entry <= 0 or notional <= 0 or not math.isfinite(current_price):
        return 0.0
    qty = notional / entry
    direction = 1.0 if str(trade.get("side") or "").upper() == "LONG" else -1.0
    return (current_price - entry) * qty * direction


def _trade_return_pct(trade: dict, default_notional: float) -> float:
    value = safe_float(trade.get("net_return_pct"), default=float("nan"))
    if math.isfinite(value):
        return value
    notional = _trade_notional(trade, default_notional)
    return _trade_net_pnl(trade, default_notional) / notional * 100.0 if notional > 0 else 0.0


def _money(value: float) -> str:
    return f"{value:.2f}" if math.isfinite(value) else "-"


def _pct(value: float) -> str:
    return f"{value:.2f}%" if math.isfinite(value) else "-"


def _update_account_overview_panel(window, row) -> None:
    labels = (
        "accountEquityValue",
        "accountReturnValue",
        "accountPnlValue",
        "accountWinRateValue",
        "accountSharpeValue",
        "accountProfitFactorValue",
        "accountPayoffValue",
        "accountMaxDrawdownValue",
    )
    if not all(hasattr(window, attr) for attr in labels):
        return
    initial = _spin_float(window, "initialEquitySpin", 10_000.0)
    default_notional = _spin_float(window, "tradeNotionalSpin", 1_000.0)
    current_price = safe_float(row.get("close"), default=float("nan")) if row is not None else float("nan")
    trades = list(getattr(window, "trades", []) or [])
    closed = [trade for trade in trades if str(trade.get("status") or "").upper() == "CLOSED"]
    open_trades = [trade for trade in trades if str(trade.get("status") or "").upper() == "OPEN"]
    realized = sum(_trade_net_pnl(trade, default_notional) for trade in closed)
    unrealized = sum(_floating_pnl(trade, current_price, default_notional) for trade in open_trades)
    equity = initial + realized + unrealized
    pnl = equity - initial
    total_return = pnl / initial * 100.0 if initial > 0 else float("nan")
    returns = [_trade_return_pct(trade, default_notional) for trade in closed]
    pnls = [_trade_net_pnl(trade, default_notional) for trade in closed]
    wins = [value for value in pnls if value > 0]
    win_rate = len(wins) / len(closed) * 100.0 if closed else float("nan")
    equity_path = [initial]
    running = initial
    for trade in sorted(closed, key=lambda item: (item.get("exit_bar_index") is None, item.get("exit_bar_index") or 0, item.get("updated_at") or "")):
        running += _trade_net_pnl(trade, default_notional)
        equity_path.append(running)
    if open_trades:
        equity_path.append(equity)
    dd = max_drawdown(equity_path).get("max_drawdown_pct")
    sharpe = sharpe_ratio([ret / 100.0 for ret in returns])
    pf = profit_factor(pnls)
    payoff = payoff_ratio(pnls)
    role = "valuePositive" if pnl > 0 else "valueNegative" if pnl < 0 else "statusValue"
    _set_text_if_present(window, "accountEquityValue", _money(equity))
    _set_text_if_present(window, "accountReturnValue", _pct(total_return))
    _set_text_if_present(window, "accountPnlValue", _money(pnl))
    _set_text_if_present(window, "accountWinRateValue", _pct(win_rate))
    _set_text_if_present(window, "accountSharpeValue", fmt_num(sharpe) if sharpe is not None else "-")
    _set_text_if_present(window, "accountProfitFactorValue", fmt_num(pf) if pf is not None else "-")
    _set_text_if_present(window, "accountPayoffValue", fmt_num(payoff) if payoff is not None else "-")
    _set_text_if_present(window, "accountMaxDrawdownValue", _pct(dd) if dd is not None else "-")
    _set_label_role(getattr(window, "accountPnlValue", None), role)
    _set_label_role(getattr(window, "accountReturnValue", None), role)


def _update_position_panel(window, row) -> None:
    empty = getattr(window, "positionEmptyState", None)
    details = getattr(window, "positionDetails", None)
    mini_table = getattr(window, "openPositionsMiniTable", None)
    labels = (
        "positionSideValue",
        "positionQtyValue",
        "positionEntryValue",
        "positionCurrentValue",
        "positionPnlValue",
        "positionPnlPctValue",
    )
    if row is None:
        if empty is not None:
            empty.setVisible(True)
        if details is not None:
            details.setVisible(False)
        for attr in labels:
            _set_text_if_present(window, attr, "-")
        if mini_table is not None:
            mini_table.setRowCount(0)
            mini_table.setVisible(False)
        return
    current_price = safe_float(row.get("close"), default=float("nan"))
    open_trades = [trade for trade in getattr(window, "trades", []) if str(trade.get("status") or "").upper() == "OPEN"]
    if not open_trades or not math.isfinite(current_price) or current_price <= 0:
        if empty is not None:
            empty.setVisible(True)
        if details is not None:
            details.setVisible(False)
        _set_text_if_present(window, "positionSideValue", "无持仓")
        _set_text_if_present(window, "positionQtyValue", "-")
        _set_text_if_present(window, "positionEntryValue", "-")
        _set_text_if_present(window, "positionCurrentValue", fmt_num(current_price) if math.isfinite(current_price) else "-")
        _set_text_if_present(window, "positionPnlValue", "-")
        _set_text_if_present(window, "positionPnlPctValue", "-")
        _set_label_role(getattr(window, "positionPnlValue", None), "statusValue")
        _set_label_role(getattr(window, "positionPnlPctValue", None), "statusValue")
        if mini_table is not None:
            mini_table.setRowCount(0)
            mini_table.setVisible(False)
        return

    if empty is not None:
        empty.setVisible(False)
    if details is not None:
        details.setVisible(True)
    sides = {str(trade.get("side") or "").upper() for trade in open_trades}
    side_text = next(iter(sides)) if len(sides) == 1 else f"混合 {len(open_trades)}"
    total_qty = 0.0
    weighted_entry = 0.0
    total_notional = 0.0
    pnl = 0.0
    for trade in open_trades:
        entry = _entry_price(trade)
        notional = safe_float(trade.get("notional_quote"), default=0.0)
        if not math.isfinite(entry) or entry <= 0 or notional <= 0:
            continue
        qty = notional / entry
        direction = 1.0 if str(trade.get("side") or "").upper() == "LONG" else -1.0
        total_qty += qty
        weighted_entry += entry * qty
        total_notional += notional
        pnl += (current_price - entry) * qty * direction
    entry_avg = weighted_entry / total_qty if total_qty > 0 else float("nan")
    pnl_pct = pnl / total_notional * 100.0 if total_notional > 0 else float("nan")
    pnl_role = "valuePositive" if pnl > 0 else "valueNegative" if pnl < 0 else "statusValue"
    _set_text_if_present(window, "positionSideValue", side_text)
    _set_text_if_present(window, "positionQtyValue", fmt_num(total_qty) if total_qty > 0 else "-")
    _set_text_if_present(window, "positionEntryValue", fmt_num(entry_avg) if math.isfinite(entry_avg) else "-")
    _set_text_if_present(window, "positionCurrentValue", fmt_num(current_price))
    _set_text_if_present(window, "positionPnlValue", fmt_num(pnl))
    _set_text_if_present(window, "positionPnlPctValue", f"{fmt_num(pnl_pct)}%" if math.isfinite(pnl_pct) else "-")
    _set_label_role(getattr(window, "positionPnlValue", None), pnl_role)
    _set_label_role(getattr(window, "positionPnlPctValue", None), pnl_role)
    if mini_table is not None:
        mini_table.setVisible(True)
        mini_table.setRowCount(len(open_trades))
        for row_index, trade in enumerate(sorted(open_trades, key=lambda item: (item.get("entry_bar_index") or 0, item.get("created_at") or ""))):
            trade_pnl = _floating_pnl(trade, current_price, _trade_notional(trade, total_notional or 1_000.0))
            values = (
                short_id(trade.get("trade_id") or ""),
                str(trade.get("side") or "-"),
                fmt_num(_entry_price(trade)),
                f"{trade_pnl:.2f}",
                fmt_num(trade.get("take_profit_price")),
                fmt_num(trade.get("stop_loss_price")),
            )
            for col, value in enumerate(values):
                table_item = QtWidgets.QTableWidgetItem(value)
                if col in {2, 3, 4, 5}:
                    table_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                mini_table.setItem(row_index, col, table_item)


def show_market_dirty_feedback(window) -> None:
    message = window.tr("market_params_dirty_hint")
    window.status.setText(message)
    hint = getattr(window, "marketDirtyHint", None)
    if hint is not None:
        hint.setText(message)
        hint.setVisible(True)
    window._update_load_play_button()


def update_load_play_button(window) -> None:
    if not hasattr(window, "btnLoadPlay"):
        return
    if window._loading_data:
        window.btnLoadPlay.setText(window.tr("loading"))
        window.btnLoadPlay.setEnabled(False)
        return
    dirty = bool(getattr(window, "market_dirty", False) or window._is_market_params_dirty())
    if window.df.empty or dirty:
        if dirty:
            window.market_dirty = True
        window.btnLoadPlay.setText(f"{window.tr('play')} (Space)")
        window.btnLoadPlay.setEnabled(False)
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
    if not hasattr(window, "headerMainLabel") and not hasattr(window, "headerSymbolValue"):
        return
    symbol = window.symbolBox.currentText().strip().upper() if hasattr(window, "symbolBox") else DEFAULT_SYMBOL
    interval = window.intervalBox.currentText().strip() if hasattr(window, "intervalBox") else DEFAULT_INTERVAL
    display_interval = window._display_interval() if hasattr(window, "_display_interval") else interval
    sample_interval = window._sample_interval() if hasattr(window, "_sample_interval") else interval
    row, idx = _current_row(window)
    ohlc_text = "-"
    time_text = "-"
    change_text = "-"
    change_role = "statusValue"
    if row is not None:
        open_price = safe_float(row.get("open"), default=float("nan"))
        close_price = safe_float(row.get("close"), default=float("nan"))
        ohlc_text = (
            f"O {fmt_num(row.get('open'))}  H {fmt_num(row.get('high'))}  "
            f"L {fmt_num(row.get('low'))}  C {fmt_num(row.get('close'))}"
        )
        time_text = _format_bar_time(row.get("open_time_bjt"))
        if math.isfinite(open_price) and open_price:
            change_pct = (close_price / open_price - 1.0) * 100.0
            change_text = f"{change_pct:+.2f}%"
            change_role = "valuePositive" if change_pct > 0 else "valueNegative" if change_pct < 0 else "statusValue"
    main_text = (
        f"{symbol or '-'} · {display_interval or '-'} · sample {sample_interval or '-'} · "
        f"{time_text} · {ohlc_text} · {change_text}"
    )
    if hasattr(window, "headerMainLabel"):
        window.headerMainLabel.setText(main_text)
        _set_label_role(window.headerMainLabel, "headerMain")
        for attr, text in (
            ("headerSymbolValue", symbol or "-"),
            ("headerIntervalValue", display_interval or "-"),
            ("headerSampleIntervalValue", f"sample {sample_interval or '-'}"),
            ("headerOhlcValue", ohlc_text),
            ("headerTimeValue", time_text),
            ("headerDeltaValue", change_text),
        ):
            _set_text_if_present(window, attr, text)
    else:
        window.headerSymbolValue.setText(symbol or "-")
        window.headerIntervalValue.setText(display_interval or "-")
        if hasattr(window, "headerSampleIntervalValue"):
            window.headerSampleIntervalValue.setText(f"sample {sample_interval or '-'}")
        if hasattr(window, "headerOhlcValue"):
            window.headerOhlcValue.setText(ohlc_text)
        elif hasattr(window, "headerCloseValue"):
            window.headerCloseValue.setText(ohlc_text)
        window.headerTimeValue.setText(time_text)
        if hasattr(window, "headerDeltaValue"):
            window.headerDeltaValue.setText(change_text)
            _set_label_role(window.headerDeltaValue, change_role)
    window.headerPlayBadge.setText(window.tr("playing") if window.playing else window.tr("paused"))
    window._set_widget_role(window.headerPlayBadge, "pillLive" if window.playing else "pillMuted")
    window.headerViewBadge.setText(window.tr("follow_latest") if window.follow_latest else window.tr("free_view"))
    window._set_widget_role(window.headerViewBadge, "pillLive" if window.follow_latest else "pill")
    short_session = short_id(window.session_id) if window.session_id else "-"
    window.headerSessionBadge.setText(f"{window.tr('session')} {short_session}")
    for interval_key, button in getattr(window, "chartIntervalButtons", {}).items():
        button.setChecked(interval_key == display_interval)
    _update_current_bar_panel(window, row, idx)
    _update_position_panel(window, row)
    _update_account_overview_panel(window, row)
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
        window.axis_current_price.set_current_price(None)
        return
    idx = int(clamp(window.cursor, 0, len(window.df) - 1))
    row = window.df.iloc[idx]
    price = float(row["close"])
    prev_close = float(window.df.iloc[max(0, idx - 1)]["close"]) if idx > 0 else price
    if price > prev_close:
        line_color = window.theme_settings["current_price_up"]
    elif price < prev_close:
        line_color = window.theme_settings["current_price_down"]
    else:
        line_color = window.theme_settings.get("current_price_neutral", window.theme_settings.get("crosshair", "#8C8983"))
    text_color = window.theme_settings["current_price_label_text"]
    window.currentPriceLine.setPen(pg.mkPen(line_color, style=QtCore.Qt.DashLine, width=1))
    window.currentPriceLine.setValue(price)
    window.axis_current_price.set_current_price(price, line_color, text_color)
    window.currentPriceLine.show()


__all__ = [
    "refresh_premium_plot",
    "show_market_dirty_feedback",
    "update_current_price_line",
    "update_header",
    "update_load_play_button",
    "update_trade_buttons_enabled",
]
