"""Main-window market loading and dynamic timeframe orchestration."""

from __future__ import annotations

import json
import re

import pandas as pd
from PySide6 import QtCore, QtWidgets

try:
    from app_config import BJT
    from app_logger import get_logger
    from market_data import LoadRequest
    from render_state import RenderState
    from services.session_service import load_session_snapshot_state
    from services.ui_message_localizer import localize_worker_message
    from controllers.session_resume_controller import (
        abort_performance_session_resume,
        complete_performance_session_resume,
    )
    from timeframe_switcher import (
        build_time_centered_xrange,
        capture_time_anchor,
        capture_view_time_span,
        find_bar_index_by_time,
    )
except ImportError:  # pragma: no cover - package import path
    from ..app_config import BJT
    from ..app_logger import get_logger
    from ..market_data import LoadRequest
    from ..render_state import RenderState
    from ..services.session_service import load_session_snapshot_state
    from ..services.ui_message_localizer import localize_worker_message
    from .session_resume_controller import (
        abort_performance_session_resume,
        complete_performance_session_resume,
    )
    from ..timeframe_switcher import (
        build_time_centered_xrange,
        capture_time_anchor,
        capture_view_time_span,
        find_bar_index_by_time,
    )


logger = get_logger(__name__)


def _chart_status_message(message: str, translator=None) -> str:
    text = str(message or "").strip()
    if text.startswith("Loaded cache "):
        return translator("market.loaded_cache") if translator else "K-lines loaded from local cache"
    if "; cache=" in text:
        text = text.split("; cache=", 1)[0].strip() + "."
    if "; quality=" in text:
        text = text.split("; quality=", 1)[0].strip() + "."
    if "; reason=" in text:
        text = text.split("; reason=", 1)[0].strip() + "."
    if "cache fallback failed" in text:
        text = (
            translator("market.cache_fallback_failed")
            if translator
            else "Online load failed; cache fallback also failed."
        )
    return text[:96] + "..." if len(text) > 99 else text


def _render_state(window) -> RenderState:
    getter = getattr(window, "_chart_render_state", None)
    if callable(getter):
        return getter()
    state = getattr(window, "render_state", None)
    if state is None:
        state = RenderState()
        window.render_state = state
    return state


def normalized_symbol(window) -> str | None:
    symbol = window.symbolBox.currentText().strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,30}", symbol):
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("dialog.invalid_symbol_title"),
            window.tr("dialog.invalid_symbol_message"),
        )
        return None
    return symbol


def current_market_key(window) -> tuple[str, str, str, str]:
    return (
        window.symbolBox.currentText().strip().upper(),
        window.intervalBox.currentText().strip(),
        window.startDate.date().toString("yyyy-MM-dd"),
        window.endDate.date().toString("yyyy-MM-dd"),
    )


def is_market_params_dirty(window) -> bool:
    if window.df.empty:
        return False
    return window._loaded_market_key != window._current_market_key()


def accept_loaded_market_key(window, frame: pd.DataFrame, successful: bool = True) -> None:
    if successful and isinstance(frame, pd.DataFrame) and not frame.empty:
        window._loaded_market_key = window._pending_market_key or window._current_market_key()
        window._display_market_key = window._loaded_market_key
        if not getattr(window, "trades", []) and not getattr(window, "events", []):
            window._sample_market_key = window._display_market_key
        hint = getattr(window, "marketDirtyHint", None)
        if hint is not None:
            hint.setVisible(False)
    window._pending_market_key = None
    window.market_dirty = window._is_market_params_dirty()


def load_multi_timeframe_context(window) -> None:
    if not hasattr(window, "multiTimeframePanel") or window.df.empty or window.market_dirty:
        return
    loaded_key = window._loaded_market_key
    if not loaded_key:
        return
    symbol, primary_interval, start_date, end_date = loaded_key
    window._last_multi_timeframe_refresh_key = None
    start_dt = pd.Timestamp(start_date, tz=BJT).to_pydatetime()
    end_dt = (
        pd.Timestamp(end_date, tz=BJT)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).to_pydatetime()
    window.multiTimeframePanel.request_context_load(symbol, primary_interval, start_dt, end_dt)


def on_multi_timeframe_load_failed(window, interval: str, error: str) -> None:
    symbol = (
        window._loaded_market_key[0]
        if window._loaded_market_key
        else window.symbolBox.currentText().strip().upper()
    )
    window._log(
        window.tr("log.higher_timeframe_failed").format(
            symbol=symbol,
            interval=interval,
            error=error,
        )
    )


def on_interval_changed_for_dynamic_switch(window, new_interval: str) -> None:
    lifecycle = getattr(window, "task_lifecycle", None)
    if lifecycle is not None and lifecycle.shutdown_in_progress:
        return
    if window._loading_data:
        window._queued_dynamic_interval = str(new_interval).strip()
        return
    if lifecycle is not None and tuple(lifecycle.active_tasks):
        return
    window._update_header()
    if window.df.empty:
        return
    display_key = getattr(window, "_display_market_key", None) or getattr(window, "_loaded_market_key", None)
    previous_interval = display_key[1] if display_key else None
    next_interval = str(new_interval).strip()
    if previous_interval == next_interval:
        return
    if (
        getattr(window, "trades", [])
        or getattr(window, "events", [])
    ) and window._display_interval() == window._sample_interval():
        window._sample_cursor_bar_index = int(window.cursor)
    window._pending_time_anchor_bjt = capture_time_anchor(window.df, window.cursor)
    window._pending_view_time_span_seconds = capture_view_time_span(window.df, window.manual_xrange)
    window._pending_was_playing = bool(window.playing)
    window._pending_follow_latest = bool(window.follow_latest)
    window._pending_switch_from_interval = previous_interval
    window._pending_switch_to_interval = next_interval
    window._timeframe_switch_pending = True
    window.playing = False
    window.replay_controller.playing = False
    window.replay_controller.accumulated_bars = 0.0
    _render_state(window).mark_multi_timeframe_changed()
    window._last_multi_timeframe_refresh_key = None
    if hasattr(window, "multiTimeframePanel"):
        window.multiTimeframePanel.mark_stale()
    window.load_data(
        dynamic_switch=True,
        preserve_time_anchor=True,
        auto_resume_after_load=window._pending_was_playing,
        reset_session=False,
        use_cache=True,
    )


def on_market_params_changed(window) -> None:
    window.market_dirty = True if window.df.empty else window._is_market_params_dirty()
    if window.market_dirty:
        window.playing = False
        window._accum = 0.0
        window.replay_controller.playing = False
        window.replay_controller.accumulated_bars = 0.0
        _render_state(window).mark_header_changed()
        _render_state(window).mark_multi_timeframe_changed()
        window._last_multi_timeframe_refresh_key = None
        if hasattr(window, "multiTimeframePanel"):
            window.multiTimeframePanel.mark_stale()
    window._update_header()
    if window.market_dirty:
        window._show_market_dirty_feedback()
    else:
        hint = getattr(window, "marketDirtyHint", None)
        if hint is not None:
            hint.setVisible(False)
        window._update_load_play_button()


def clear_timeframe_switch_pending(window) -> None:
    window._timeframe_switch_pending = False
    window._pending_time_anchor_bjt = None
    window._pending_view_time_span_seconds = None
    window._pending_was_playing = False
    window._pending_follow_latest = False
    window._pending_switch_from_interval = None
    window._pending_switch_to_interval = None


def load_data(
    window,
    *,
    restore: bool = False,
    use_cache: bool | None = None,
    dynamic_switch: bool = False,
    preserve_time_anchor: bool = False,
    auto_resume_after_load: bool = False,
    reset_session: bool | None = None,
) -> bool:
    lifecycle = getattr(window, "task_lifecycle", None)
    if lifecycle is not None and (
        lifecycle.shutdown_in_progress or tuple(lifecycle.active_tasks)
    ):
        return False
    del preserve_time_anchor, auto_resume_after_load
    symbol = window._normalized_symbol()
    if symbol is None:
        return False
    interval = window.intervalBox.currentText().strip()
    d0 = window.startDate.date()
    d1 = window.endDate.date()
    if d0 > d1:
        QtWidgets.QMessageBox.warning(
            window,
            window.tr("dialog.invalid_date_range_title"),
            window.tr("dialog.invalid_date_range_message"),
        )
        return False
    start_dt = QtCore.QDateTime(d0, QtCore.QTime(0, 0)).toPython().replace(tzinfo=BJT)
    end_dt = QtCore.QDateTime(d1, QtCore.QTime(23, 59, 59)).toPython().replace(tzinfo=BJT)
    use_cache = bool(restore) if use_cache is None else bool(use_cache)
    reset_session = (not restore and not dynamic_switch) if reset_session is None else bool(reset_session)

    if lifecycle is not None:
        request_stop = getattr(getattr(window, "loader", None), "abort", None)
        if not lifecycle.start(
            "market_data_load",
            request_stop=request_stop if callable(request_stop) else None,
        ):
            return False

    window.playing = False
    window._accum = 0.0
    window.replay_controller.load_state(window.cursor, False, window.follow_latest, 0.0)
    window._set_symbol_value(symbol)
    window._pending_market_key = window._current_market_key()

    if restore and window.restoring_session_id:
        window.session_id = window.restoring_session_id
    elif reset_session:
        window.session_id = window._new_id("sess")
        window.trades.clear()
        window.events.clear()
        window._trade_by_id.clear()
        window._event_by_id.clear()
        window.undo_stack.clear()
        window.redo_stack.clear()
        window.restore_snapshot_pending = False

    if not dynamic_switch and not restore:
        window.persist_session_state()
    window.status.setText(
        window.tr("dynamic_switch_loading")
        if dynamic_switch
        else window.tr("market.loading_format").format(symbol=symbol, interval=interval)
    )
    window._loading_data = True
    window.app_state.data_load.loading = True
    window.app_state.data_load.status_message = f"Loading {symbol} {interval}"
    window._update_load_play_button()
    window._update_header()
    window.requestLoad.emit(
        LoadRequest(
            symbol=symbol,
            interval=interval,
            start_dt_bjt=start_dt,
            end_dt_bjt=end_dt,
            use_cache=use_cache,
        )
    )
    return True


def on_load_progress(window, message: str) -> None:
    window.app_state.data_load.status_message = message
    localized = localize_worker_message(message, window.tr)
    window.status.setText(_chart_status_message(localized, window.tr))
    window._log(localized)


def restore_session_snapshot(window) -> bool:
    """Restore one selected session snapshot, rolling back an explicit switch on failure."""

    try:
        snapshot_state = load_session_snapshot_state(window.storage, window.session_id)
    except Exception as exc:
        abort_performance_session_resume(window)
        operation_error = getattr(window, "_operation_error", None)
        if callable(operation_error):
            operation_error(window.tr("continue_performance_session_failed"), exc)
        else:
            logger.exception("Session snapshot restore failed")
        return False
    window.trades = snapshot_state.trades
    window.events = snapshot_state.events
    window._trade_by_id = snapshot_state.trade_by_id
    window._event_by_id = snapshot_state.event_by_id
    _render_state(window).mark_events_changed()
    if snapshot_state.cursor_bar_index is not None:
        window.cursor = snapshot_state.cursor_bar_index
        window.follow_latest = bool(snapshot_state.follow_latest)
        window.replay_controller.load_state(window.cursor, False, window.follow_latest)
        _render_state(window).mark_cursor_changed()
    window._sync_equity_curve()
    window._refresh_tables(include_heavy=False)
    analysis_refresh = getattr(window, "analysis_refresh_controller", None)
    if analysis_refresh is not None and hasattr(analysis_refresh, "schedule"):
        analysis_refresh.schedule()
    window._render(force=True)
    window._log(
        window.tr("log.session_snapshot_restored").format(
            trades=len(window.trades),
            events=len(window.events),
        )
    )
    if getattr(window, "_session_resume_rollback", None) is not None:
        complete_performance_session_resume(window)
    else:
        window.restoring_session_id = None
    return True


def on_loaded(window, frame: pd.DataFrame, message: str) -> None:
    window._loading_data = False
    window.app_state.data_load.loading = False
    localized_message = localize_worker_message(message, window.tr)
    window._log(localized_message)
    load_failed = message.startswith("加载失败")
    dynamic_switch = bool(getattr(window, "_timeframe_switch_pending", False))
    dynamic_success = dynamic_switch and not load_failed and isinstance(frame, pd.DataFrame) and not frame.empty
    if load_failed:
        logger.error("数据加载失败：%s", message)
    elif "在线刷新失败" in message or "缓存不可用" in message:
        logger.warning("数据加载警告：%s", message)
    if load_failed and getattr(window, "_session_resume_rollback", None) is not None:
        abort_performance_session_resume(window)
        lifecycle = getattr(window, "task_lifecycle", None)
        if lifecycle is not None:
            lifecycle.fail("market_data_load", message)
        window.status.setText(localized_message)
        return
    if dynamic_switch and not dynamic_success:
        previous_interval = getattr(window, "_pending_switch_from_interval", None)
        if previous_interval and hasattr(window.intervalBox, "setCurrentText"):
            blocked = window.intervalBox.blockSignals(True)
            window.intervalBox.setCurrentText(previous_interval)
            window.intervalBox.blockSignals(blocked)
        window._pending_market_key = None
        window.market_dirty = False
        clear_timeframe_switch_pending(window)
        window._update_load_play_button()
        window._render(force=True)
        window.status.setText(window.tr("dynamic_switch_failed"))
        window._log(window.tr("dynamic_switch_failed"))
        lifecycle = getattr(window, "task_lifecycle", None)
        if lifecycle is not None:
            lifecycle.fail("market_data_load", message)
        return
    anchor_time = getattr(window, "_pending_time_anchor_bjt", None)
    visible_span_seconds = getattr(window, "_pending_view_time_span_seconds", None)
    resume_playing = bool(getattr(window, "_pending_was_playing", False))
    resume_follow = bool(getattr(window, "_pending_follow_latest", False))
    switched_to = getattr(window, "_pending_switch_to_interval", None)
    incoming_attrs = dict(getattr(frame, "attrs", {}))
    window.df = frame.reset_index(drop=True) if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    window.df.attrs.update(incoming_attrs)
    window._market_data_generation = int(getattr(window, "_market_data_generation", 0)) + 1
    _render_state(window).mark_market_data_changed()
    window._last_marker_sync_key = None
    window._last_multi_timeframe_refresh_key = None
    window._accept_loaded_market_key(window.df, successful=not load_failed)
    window.app_state.data_load.bar_count = len(window.df)
    window.app_state.data_load.source = str(window.df.attrs.get("data_source", "-"))
    quality_report = window.df.attrs.get("data_quality_report", {})
    window.app_state.data_load.quality_status = (
        str(quality_report.get("data_quality_status", "-"))
        if isinstance(quality_report, dict)
        else "-"
    )
    window.cursor = (
        find_bar_index_by_time(window.df, anchor_time, switched_to or window.intervalBox.currentText().strip())
        if dynamic_switch
        else 0
    )
    window._drawn_n = -1
    window._last_cursor_for_series = -1
    window._accum = 0.0
    if dynamic_switch:
        window.playing = resume_playing
        window.follow_latest = resume_follow
        window.replay_controller.load_state(window.cursor, window.playing, window.follow_latest, 0.0)
    else:
        window.replay_controller.reset()
        window.replay_controller.follow_latest = window.follow_latest
    window._render_dirty = True

    if window.df.empty and load_failed:
        QtWidgets.QMessageBox.critical(
            window,
            window.tr("dialog.market_load_failed_title"),
            localized_message,
        )
    elif not window.df.empty:
        window._persist_loaded_market_data()

    if len(window.df):
        window.axis_price.set_times(window.df["open_time_bjt"].to_numpy())
        window.axis_vol.set_times(window.df["open_time_bjt"].to_numpy())
    else:
        window.axis_price.set_times([])
        window.axis_vol.set_times([])

    if not window.restore_snapshot_pending and not dynamic_switch:
        window.trades.clear()
        window.events.clear()
        window._trade_by_id.clear()
        window._event_by_id.clear()
        _render_state(window).mark_events_changed()
        window._refresh_tables(include_heavy=False)
        clear_analysis_views = getattr(window, "_clear_analysis_views", None)
        if callable(clear_analysis_views):
            clear_analysis_views()

    try:
        window.vb_price.disableAutoRange()
        window.vb_vol.disableAutoRange()
    except Exception:
        pass

    restored_xrange = (
        build_time_centered_xrange(window.df, window.cursor, visible_span_seconds)
        if dynamic_switch
        else None
    )
    default_span = min(window.window_bars, max(40, min(len(window.df), 80))) if len(window.df) else 40
    window.manual_xrange = restored_xrange or (-0.5, max(20.0, float(default_span)))
    window._set_xrange(*window.manual_xrange, force=True)
    window.status.setText(
        window.tr("market.loaded_count").format(
            symbol=window.symbolBox.currentText().strip().upper(),
            interval=window.intervalBox.currentText().strip(),
            count=len(window.df),
        )
    )
    window._update_load_play_button()
    window._render(force=True)

    if window.restore_snapshot_pending and window.session_id:
        window.restore_snapshot_pending = False
        if not restore_session_snapshot(window):
            lifecycle = getattr(window, "task_lifecycle", None)
            if lifecycle is not None:
                lifecycle.fail("market_data_load", "session snapshot restore failed")
            return
    if window.market_dirty:
        window._show_market_dirty_feedback()
        if hasattr(window, "multiTimeframePanel"):
            window.multiTimeframePanel.mark_stale()
    elif not window.df.empty:
        window._load_multi_timeframe_context()
        window._refresh_multi_timeframe_context()
    if dynamic_switch:
        clear_timeframe_switch_pending(window)
        window._update_load_play_button()
        window.status.setText(window.tr("dynamic_switch_success"))
    queued_interval = getattr(window, "_queued_dynamic_interval", None)
    window._queued_dynamic_interval = None
    if queued_interval and not window.df.empty and queued_interval != window._display_interval():
        QtCore.QTimer.singleShot(
            0,
            lambda interval=queued_interval: window.on_interval_changed_for_dynamic_switch(interval),
        )
    lifecycle = getattr(window, "task_lifecycle", None)
    if lifecycle is not None:
        if load_failed:
            lifecycle.fail("market_data_load", message)
        else:
            lifecycle.complete("market_data_load")


def persist_loaded_market_data(window) -> None:
    """Persist the small audit record; the range-aware disk cache owns OHLCV.

    Rewriting every cached candle into SQLite after each load duplicates the
    durable cache and, for long histories, blocks the Qt event loop for many
    seconds.  No runtime path reads ``klines`` from SQLite, while the cache
    manifest already records the exact source and quality result used here.
    """
    report = window.df.attrs.get("data_quality_report")
    if not isinstance(report, dict):
        return
    try:
        window.storage.save_data_quality_report(
            {**report, "report_json": json.dumps(report, ensure_ascii=False)}
        )
    except Exception as exc:
        logger.exception("Kline quality persistence failed.")
        window._log(
            window.tr("log.data_quality_save_failed").format(
                error=f"{type(exc).__name__}: {exc}"
            )
        )


def load_or_toggle_play(window) -> None:
    if window._loading_data:
        return
    if window.df.empty:
        window.status.setText(window.tr("apply_market_before_play"))
    elif window._is_market_params_dirty():
        window.market_dirty = True
        window._show_market_dirty_feedback()
        window.status.setText(window.tr("apply_market_before_play"))
    else:
        window.toggle_play()
        return
    window._update_load_play_button()


__all__ = [
    "accept_loaded_market_key",
    "clear_timeframe_switch_pending",
    "current_market_key",
    "is_market_params_dirty",
    "load_data",
    "load_multi_timeframe_context",
    "load_or_toggle_play",
    "normalized_symbol",
    "on_interval_changed_for_dynamic_switch",
    "on_load_progress",
    "on_loaded",
    "on_market_params_changed",
    "on_multi_timeframe_load_failed",
    "persist_loaded_market_data",
    "restore_session_snapshot",
]
