"""Map session DTOs to and from MainWindow-owned controls."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore

try:
    from services.session_service import SessionRestorePlan, SessionSaveInput
except ImportError:  # pragma: no cover - package import path
    from ..services.session_service import SessionRestorePlan, SessionSaveInput


def apply_session_restore_plan(view: Any, plan: SessionRestorePlan) -> None:
    """Apply a validated restore plan on the Qt main thread."""

    if plan.symbol:
        view._set_symbol_value(plan.symbol)
    if plan.interval:
        view.intervalBox.setCurrentText(plan.interval)
    if plan.start_date_bjt:
        view.startDate.setDate(QtCore.QDate.fromString(plan.start_date_bjt, "yyyy-MM-dd"))
    if plan.end_date_bjt:
        view.endDate.setDate(QtCore.QDate.fromString(plan.end_date_bjt, "yyyy-MM-dd"))
    view.follow_latest = plan.follow_latest
    view.speedSlider.setValue(plan.speed_slider_value)
    view.initialEquitySpin.setValue(plan.initial_equity)
    view.tradeNotionalSpin.setValue(plan.trade_notional)
    view.feeBpsSpin.setValue(plan.fee_bps)
    view.slippageBpsSpin.setValue(plan.slippage_bps)
    view.takeProfitPctSpin.setValue(plan.take_profit_pct)
    view.stopLossPctSpin.setValue(plan.stop_loss_pct)
    view._set_fill_mode_value(plan.fill_mode)


def build_session_save_input(
    view: Any,
    *,
    now_iso: str,
    app_version: str,
) -> SessionSaveInput:
    """Capture the session fields currently exposed by the MainWindow view."""

    market_key_getter = getattr(view, "_current_market_key", None)
    current_market_key = (
        market_key_getter()
        if callable(market_key_getter)
        else view._display_market_key
    )
    return SessionSaveInput(
        session_id=view.session_id,
        current_market_key=current_market_key,
        sample_market_key=view._sample_market_key,
        has_trade_samples=bool(view.trades or view.events),
        display_interval_matches_sample=view._is_display_interval_same_as_sample_interval(),
        cursor=int(view.cursor),
        sample_cursor_bar_index=int(view._sample_cursor_bar_index),
        follow_latest=bool(view.follow_latest),
        speed=view.current_speed(),
        now_iso=now_iso,
        app_version=app_version,
        initial_equity=float(view.initialEquitySpin.value()),
        trade_notional=float(view.tradeNotionalSpin.value()),
        fee_bps=float(view.feeBpsSpin.value()),
        slippage_bps=float(view.slippageBpsSpin.value()),
        fill_mode=view._fill_mode_value(),
        take_profit_pct=getattr(view, "take_profit_pct_value", lambda: None)(),
        stop_loss_pct=getattr(view, "stop_loss_pct_value", lambda: None)(),
    )


__all__ = ["apply_session_restore_plan", "build_session_save_input"]
