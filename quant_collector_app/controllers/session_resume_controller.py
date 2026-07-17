"""Explicitly continue a saved performance session on the replay workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6 import QtWidgets

try:
    from app_config import (
        DEFAULT_FEE_BPS,
        DEFAULT_FILL_MODE,
        DEFAULT_INITIAL_EQUITY,
        DEFAULT_SLIPPAGE_BPS,
        DEFAULT_TRADE_NOTIONAL,
    )
    from services.session_service import (
        build_session_restore_plan,
        list_performance_session_options,
    )
    from views.session_ui_adapter import apply_session_restore_plan
except ImportError:  # pragma: no cover - package import path
    from ..app_config import (
        DEFAULT_FEE_BPS,
        DEFAULT_FILL_MODE,
        DEFAULT_INITIAL_EQUITY,
        DEFAULT_SLIPPAGE_BPS,
        DEFAULT_TRADE_NOTIONAL,
    )
    from ..services.session_service import (
        build_session_restore_plan,
        list_performance_session_options,
    )
    from ..views.session_ui_adapter import apply_session_restore_plan


@dataclass
class _ResumeRollback:
    session_id: str | None
    restoring_session_id: str | None
    restore_snapshot_pending: bool
    symbol: str
    interval: str
    start_date: Any
    end_date: Any
    follow_latest: bool
    speed: int
    initial_equity: float
    trade_notional: float
    fee_bps: float
    slippage_bps: float
    fill_mode: str
    take_profit_pct: float | None
    stop_loss_pct: float | None
    trades: list[dict]
    events: list[dict]
    trade_by_id: dict[str, dict]
    event_by_id: dict[str, dict]
    undo_stack: list[Any]
    redo_stack: list[Any]
    df: Any
    cursor: int
    playing: bool
    display_market_key: Any
    sample_market_key: Any


def _busy(window) -> bool:
    lifecycle = getattr(window, "task_lifecycle", None)
    return bool(
        getattr(window, "_loading_data", False)
        or getattr(window, "_trade_transaction_active", False)
        or getattr(getattr(getattr(window, "app_state", None), "export", None), "running", False)
        or getattr(lifecycle, "shutdown_in_progress", False)
        or tuple(getattr(lifecycle, "active_tasks", ()))
        or getattr(getattr(window, "analysis_refresh_controller", None), "is_running", False)
    )


def _capture(window) -> _ResumeRollback:
    return _ResumeRollback(
        session_id=getattr(window, "session_id", None),
        restoring_session_id=getattr(window, "restoring_session_id", None),
        restore_snapshot_pending=bool(getattr(window, "restore_snapshot_pending", False)),
        symbol=str(window.symbolBox.currentText()),
        interval=str(window.intervalBox.currentText()),
        start_date=window.startDate.date(),
        end_date=window.endDate.date(),
        follow_latest=bool(window.follow_latest),
        speed=int(window.speedSlider.value()),
        initial_equity=float(window.initialEquitySpin.value()),
        trade_notional=float(window.tradeNotionalSpin.value()),
        fee_bps=float(window.feeBpsSpin.value()),
        slippage_bps=float(window.slippageBpsSpin.value()),
        fill_mode=str(window._fill_mode_value()),
        take_profit_pct=window.take_profit_pct_value(),
        stop_loss_pct=window.stop_loss_pct_value(),
        trades=window.trades,
        events=window.events,
        trade_by_id=window._trade_by_id,
        event_by_id=window._event_by_id,
        undo_stack=window.undo_stack,
        redo_stack=window.redo_stack,
        df=window.df,
        cursor=int(window.cursor),
        playing=bool(window.playing),
        display_market_key=getattr(window, "_display_market_key", None),
        sample_market_key=getattr(window, "_sample_market_key", None),
    )


def _restore(window, state: _ResumeRollback) -> None:
    window._restoring_session_settings = True
    try:
        window._set_symbol_value(state.symbol)
        window.intervalBox.setCurrentText(state.interval)
        window.startDate.setDate(state.start_date)
        window.endDate.setDate(state.end_date)
        window.follow_latest = state.follow_latest
        window.speedSlider.setValue(state.speed)
        window.initialEquitySpin.setValue(state.initial_equity)
        window.tradeNotionalSpin.setValue(state.trade_notional)
        window.feeBpsSpin.setValue(state.fee_bps)
        window.slippageBpsSpin.setValue(state.slippage_bps)
        window.takeProfitPctSpin.setValue(state.take_profit_pct)
        window.stopLossPctSpin.setValue(state.stop_loss_pct)
        window._set_fill_mode_value(state.fill_mode)
    finally:
        window._restoring_session_settings = False
    window.session_id = state.session_id
    window.restoring_session_id = state.restoring_session_id
    window.restore_snapshot_pending = state.restore_snapshot_pending
    window.trades = state.trades
    window.events = state.events
    window._trade_by_id = state.trade_by_id
    window._event_by_id = state.event_by_id
    window.undo_stack = state.undo_stack
    window.redo_stack = state.redo_stack
    window.df = state.df
    window.cursor = state.cursor
    window.playing = state.playing
    window._display_market_key = state.display_market_key
    window._sample_market_key = state.sample_market_key
    replay = getattr(window, "replay_controller", None)
    if replay is not None and hasattr(replay, "load_state"):
        replay.load_state(window.cursor, window.playing, window.follow_latest, 0.0)


def abort_performance_session_resume(window) -> bool:
    state = getattr(window, "_session_resume_rollback", None)
    if state is None:
        return False
    _restore(window, state)
    window._session_resume_rollback = None
    return True


def complete_performance_session_resume(window) -> None:
    window._session_resume_rollback = None
    window.restoring_session_id = None


def refresh_replay_performance_sessions(window) -> None:
    combo = window.replayPerformanceSessionBox
    selected = str(combo.currentData() or "")
    options = list_performance_session_options(window.storage)
    combo.blockSignals(True)
    combo.clear()
    selected_index = -1
    for index, option in enumerate(options):
        combo.addItem(option.display_name, option.session_id)
        if option.session_id == selected:
            selected_index = index
    if selected_index >= 0:
        combo.setCurrentIndex(selected_index)
    combo.blockSignals(False)


def continue_performance_session(window) -> bool:
    if _busy(window):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("continue_performance_session_title"),
            window.tr("continue_performance_session_busy"),
        )
        return False
    target_id = str(window.replayPerformanceSessionBox.currentData() or "")
    if not target_id:
        return False
    current_id = str(getattr(window, "session_id", "") or "")
    if current_id == target_id:
        return True
    if current_id and current_id != target_id:
        response = QtWidgets.QMessageBox.warning(
            window,
            window.tr("continue_performance_session_title"),
            window.tr("continue_performance_session_switch_warning"),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return False
    rollback = _capture(window)
    try:
        if current_id and current_id != target_id:
            window.persist_session_state()
        row = window.storage.get_session(target_id)
        if not row:
            raise ValueError(window.tr("continue_performance_session_missing"))
        plan = build_session_restore_plan(
            row,
            default_initial_equity=DEFAULT_INITIAL_EQUITY,
            default_trade_notional=DEFAULT_TRADE_NOTIONAL,
            default_fee_bps=DEFAULT_FEE_BPS,
            default_slippage_bps=DEFAULT_SLIPPAGE_BPS,
            default_fill_mode=DEFAULT_FILL_MODE,
        )
        window._session_resume_rollback = rollback
        window.restoring_session_id = plan.session_id
        window.session_id = plan.session_id
        window._restoring_session_settings = True
        try:
            apply_session_restore_plan(window, plan)
        finally:
            window._restoring_session_settings = False
        window.restore_snapshot_pending = True
        accepted = window.load_data(restore=True, reset_session=False)
        if accepted is False:
            abort_performance_session_resume(window)
            return False
        return True
    except Exception as exc:
        if getattr(window, "_session_resume_rollback", None) is not None:
            abort_performance_session_resume(window)
        else:
            _restore(window, rollback)
        window._operation_error(window.tr("continue_performance_session_failed"), exc)
        return False


__all__ = [
    "abort_performance_session_resume",
    "complete_performance_session_resume",
    "continue_performance_session",
    "refresh_replay_performance_sessions",
]
