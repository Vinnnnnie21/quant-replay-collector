"""Qt-main-thread chart rendering adapter used by MainWindow wrappers."""

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
from PySide6 import QtCore

try:
    from app_config import BJT
    from market_data import clamp
    from presenters.formatters import fmt_num, short_id
    from render.chart_render_plan import build_chart_render_plan, clamp_visible_range
    from render.marker_renderer import MarkerPayloadCache
    from render.visible_window import build_rebuild_plan
    from render_state import RenderState
except ImportError:  # pragma: no cover - package import path
    from ..app_config import BJT
    from ..market_data import clamp
    from ..presenters.formatters import fmt_num, short_id
    from .chart_render_plan import build_chart_render_plan, clamp_visible_range
    from .marker_renderer import MarkerPayloadCache
    from .visible_window import build_rebuild_plan
    from ..render_state import RenderState


def _log_slow(window, name: str, started: float) -> None:
    callback = getattr(window, "_log_slow_operation", None)
    if callable(callback):
        callback(name, started)


def _render_state(window) -> RenderState:
    getter = getattr(window, "_chart_render_state", None)
    if callable(getter):
        return getter()
    state = getattr(window, "render_state", None)
    if state is None:
        state = RenderState()
        window.render_state = state
    return state


def should_render_now(window, force: bool = False) -> bool:
    if force or not window.playing:
        return True
    now = QtCore.QDateTime.currentMSecsSinceEpoch()
    return now - int(getattr(window, "_last_render_msec", 0)) >= int(
        getattr(window, "_render_interval_ms", 50)
    )


def mark_rendered(window) -> None:
    window._last_render_msec = QtCore.QDateTime.currentMSecsSinceEpoch()


def on_price_view_range_changed(window, view_range) -> None:
    if window._programmatic_view_update:
        return
    try:
        x0, x1 = view_range[0]
    except Exception:
        return
    if not (math.isfinite(x0) and math.isfinite(x1) and x1 > x0):
        return
    window.manual_xrange = (float(x0), float(x1))
    _render_state(window).mark_visible_range_changed()
    window._render_dirty = True


def refresh_multi_timeframe_context(window) -> None:
    started = time.perf_counter()
    if not hasattr(window, "multiTimeframePanel") or window.df.empty:
        return
    try:
        index = int(clamp(window.cursor, 0, len(window.df) - 1))
        primary_row = window.df.iloc[index]
        if hasattr(window.multiTimeframePanel, "_context_summary_key"):
            context_key = window.multiTimeframePanel._context_summary_key(primary_row)
        else:
            context_key = (index,)
        if context_key == getattr(window, "_last_multi_timeframe_refresh_key", None):
            return
        window.multiTimeframePanel.refresh_for_primary_row(primary_row)
        window._last_multi_timeframe_refresh_key = context_key
    finally:
        _log_slow(window, "_refresh_multi_timeframe_context", started)


def rebuild_items(window, n=None, visible_range=None) -> None:
    started = time.perf_counter()
    if window.df.empty:
        window.candleItem.set_data(np.array([]), np.array([]), np.array([]), np.array([]), np.array([]))
        window.volItem.set_data(np.array([]), np.array([]), np.array([]))
        window._drawn_n = 0
        window._last_rebuild_key = None
        return
    try:
        n = int(clamp((window.cursor + 1) if n is None else n, 0, len(window.df)))
        xrange = visible_range if visible_range is not None else window._current_xrange()
        plan = build_rebuild_plan(n, xrange)
        start, end = plan.start, plan.end
        rebuild_key = plan.rebuild_key
        if getattr(window, "_last_rebuild_key", None) == rebuild_key:
            return
        frame = window.df.iloc[start:end]
        x = np.arange(start, end, dtype=float)
        opening = frame["open"].to_numpy(dtype=float)
        high = frame["high"].to_numpy(dtype=float)
        low = frame["low"].to_numpy(dtype=float)
        close = frame["close"].to_numpy(dtype=float)
        volume = frame["volume"].to_numpy(dtype=float)
        up = close >= opening
        window.candleItem.set_data(x, opening, high, low, close)
        window.volItem.set_data(x, volume, up)
        window._drawn_n = n
        window._last_rebuild_key = rebuild_key
    finally:
        _log_slow(window, "_rebuild_items", started)


def current_xrange(window):
    try:
        (x0, x1), _ = window.vb_price.viewRange()
        if math.isfinite(x0) and math.isfinite(x1) and x1 > x0:
            return float(x0), float(x1)
    except Exception:
        pass
    return None


def set_xrange(window, x0: float, x1: float, force: bool = False) -> None:
    x0, x1 = window._clamp_xrange(x0, x1)
    current = window._current_xrange()
    if (
        not force
        and current is not None
        and abs(current[0] - x0) < 1e-6
        and abs(current[1] - x1) < 1e-6
    ):
        return
    window._programmatic_view_update = True
    try:
        window.pricePlot.setXRange(x0, x1, padding=0.0)
    finally:
        window._programmatic_view_update = False
    window.manual_xrange = (x0, x1)


def clamp_xrange(window, x0: float, x1: float):
    return clamp_visible_range(
        x0,
        x1,
        row_count=len(window.df),
        cursor=window.cursor,
        pad_right=window.pad_right,
    )


def soft_follow_should_apply(window) -> bool:
    if not window.follow_latest or window.df.empty:
        return False
    now = QtCore.QDateTime.currentMSecsSinceEpoch() / 1000.0
    if window.user_view_lock and (now - window.last_user_interaction) < 1.2:
        (_x0, x1), _ = window.vb_price.viewRange()
        return x1 >= (window.cursor - 6)
    return True


def autoscale_y(window, x0, x1) -> None:
    if window.df.empty or window.cursor < 0:
        return
    available_n = window.cursor + 1
    i0 = int(clamp(math.floor(x0), 0, available_n - 1))
    i1 = int(clamp(math.ceil(x1), 0, available_n - 1))
    if i1 <= i0:
        i1 = min(available_n - 1, i0 + 1)
    visible = window.df.iloc[i0:i1 + 1]
    if visible.empty:
        return
    lmin = float(visible["low"].min())
    hmax = float(visible["high"].max())
    if abs(hmax - lmin) < 1e-9:
        hmax += 1.0
        lmin -= 1.0
    window.pricePlot.setYRange(lmin, hmax, padding=0.0)
    vmax = float(visible["volume"].max()) if len(visible) else 1.0
    window.volPlot.setYRange(0.0, max(vmax, 1.0), padding=0.0)


def sync_markers(window, force_reindex: bool | None = None) -> None:
    cache = getattr(window, "_marker_payload_cache", None)
    if cache is None:
        cache = MarkerPayloadCache()
        window._marker_payload_cache = cache
    if force_reindex is None:
        state = getattr(window, "render_state", None)
        force_reindex = bool(
            state is not None
            and (state.events_changed or state.market_data_changed)
        )
    payload = cache.payload_for(
        window.df,
        window.events,
        cursor=window.cursor,
        display_interval=window._display_interval(),
        sample_interval=window._sample_interval(),
        events_changed=force_reindex,
    )
    if payload.marker_key == getattr(window, "_last_marker_sync_key", None):
        return
    window.scatter_open_long.setData(
        pos=np.array(payload.open_long) if payload.open_long else np.empty((0, 2), dtype=float)
    )
    window.scatter_open_short.setData(
        pos=np.array(payload.open_short) if payload.open_short else np.empty((0, 2), dtype=float)
    )
    window.scatter_close_long.setData(
        pos=np.array(payload.close_long) if payload.close_long else np.empty((0, 2), dtype=float)
    )
    window.scatter_close_short.setData(
        pos=np.array(payload.close_short) if payload.close_short else np.empty((0, 2), dtype=float)
    )
    window._last_marker_sync_key = payload.marker_key


def render_chart(window, force: bool = False) -> None:
    started = time.perf_counter()
    state = _render_state(window)
    plan = build_chart_render_plan(
        state=state,
        force=force,
        render_dirty=window._render_dirty,
        row_count=len(window.df),
        cursor=window.cursor,
        pad_right=window.pad_right,
        window_bars=window.window_bars,
        follow_latest=window.follow_latest,
        current_xrange=window._current_xrange(),
        manual_xrange=window.manual_xrange,
    )
    if plan is None:
        return
    if plan.is_empty:
        if plan.refresh_header:
            window._update_header()
        window._render_dirty = False
        state.clear()
        return
    if plan.manual_xrange is not None:
        window.manual_xrange = plan.manual_xrange
    vx0, vx1 = plan.visible_range
    if plan.rebuild_series:
        window._rebuild_items(visible_range=(vx0, vx1))
    if plan.set_xrange:
        window._set_xrange(vx0, vx1, force=plan.force_xrange)
    if plan.refresh_autoscale:
        window._autoscale_y(vx0, vx1)
    if plan.refresh_markers:
        window._sync_markers()
    if plan.refresh_price_line:
        window._update_current_price_line(vx0, vx1)
    if plan.refresh_multi_timeframe:
        window._refresh_multi_timeframe_context()
    index = int(clamp(window.cursor, 0, len(window.df) - 1))
    bar_time = pd.to_datetime(window.df.iloc[index]["open_time_bjt"]).tz_convert(BJT).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    bar = window.df.iloc[index]
    report = window.df.attrs.get("data_quality_report", {})
    data_source = window.df.attrs.get("data_source", "-")
    quality = report.get("data_quality_status", "-") if isinstance(report, dict) else "-"
    window.status.setText(
        f"{window.symbolBox.currentText().strip().upper()} {window.intervalBox.currentText().strip()} | "
        f"{'播放' if window.playing else '暂停'} | 速度 x{window.current_speed():.1f} | "
        f"cursor={window.cursor}/{max(0, len(window.df) - 1)} | {bar_time} BJT | "
        f"O={fmt_num(bar.get('open'))} H={fmt_num(bar.get('high'))} "
        f"L={fmt_num(bar.get('low'))} C={fmt_num(bar.get('close'))} | "
        f"源={data_source} 质量={quality} 样本={len(window.events)} "
        f"会话={short_id(window.session_id) if window.session_id else '-'} | "
        f"{'跟随最新' if window.follow_latest else '自由浏览'}"
    )
    if window._is_market_params_dirty():
        window.status.setText(window.tr("market_params_changed"))
    window._update_header()
    window._render_dirty = False
    state.clear()
    _log_slow(window, "_render", started)


__all__ = [
    "autoscale_y",
    "clamp_xrange",
    "current_xrange",
    "mark_rendered",
    "on_price_view_range_changed",
    "rebuild_items",
    "refresh_multi_timeframe_context",
    "render_chart",
    "set_xrange",
    "should_render_now",
    "soft_follow_should_apply",
    "sync_markers",
]
