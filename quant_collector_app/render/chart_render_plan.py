from __future__ import annotations

from dataclasses import dataclass
from typing import Any


XRange = tuple[float, float]


@dataclass(frozen=True)
class ChartRenderPlan:
    """Pure render decisions that MainWindow applies on the Qt main thread."""

    is_empty: bool
    visible_range: XRange | None
    manual_xrange: XRange | None
    rebuild_series: bool
    set_xrange: bool
    force_xrange: bool
    refresh_autoscale: bool
    refresh_markers: bool
    refresh_price_line: bool
    refresh_multi_timeframe: bool
    refresh_status: bool
    refresh_header: bool


def clamp_visible_range(
    x0: float,
    x1: float,
    *,
    row_count: int,
    cursor: int,
    pad_right: int,
) -> XRange:
    if row_count <= 0:
        return float(x0), float(x1)
    left = float(x0)
    right = float(x1)
    span = max(3.0, right - left)
    xmin = 0.0
    xmax = max(float(cursor) + float(pad_right), span)
    if left < xmin:
        left = xmin
        right = left + span
    if right > xmax:
        right = xmax
        left = right - span
    if left < xmin:
        left = xmin
    return left, right


def _ranges_differ(first: XRange | None, second: XRange) -> bool:
    if first is None:
        return True
    return abs(first[0] - second[0]) > 1e-6 or abs(first[1] - second[1]) > 1e-6


def build_chart_render_plan(
    *,
    state: Any,
    force: bool,
    render_dirty: bool,
    row_count: int,
    cursor: int,
    pad_right: int,
    window_bars: int,
    follow_latest: bool,
    current_xrange: XRange | None,
    manual_xrange: XRange | None,
) -> ChartRenderPlan | None:
    """Resolve render work without touching Qt widgets or mutating render state."""

    if not force and not render_dirty and not state.any_dirty():
        return None

    force_clean = bool(force and not state.any_dirty())
    if row_count <= 0:
        return ChartRenderPlan(
            is_empty=True,
            visible_range=None,
            manual_xrange=manual_xrange,
            rebuild_series=False,
            set_xrange=False,
            force_xrange=False,
            refresh_autoscale=False,
            refresh_markers=False,
            refresh_price_line=False,
            refresh_multi_timeframe=False,
            refresh_status=False,
            refresh_header=bool(force or force_clean or state.should_refresh_header()),
        )

    rebuild_series = bool(force_clean or state.should_refresh_series())
    refresh_autoscale = bool(force_clean or state.should_refresh_autoscale())
    refresh_markers = bool(force_clean or state.should_refresh_markers())
    refresh_price_line = bool(force_clean or state.should_refresh_price_line())
    refresh_multi_timeframe = bool(force_clean or state.should_refresh_multi_timeframe())

    if follow_latest:
        if current_xrange is not None:
            span = max(5.0, current_xrange[1] - current_xrange[0])
        elif manual_xrange is not None:
            span = max(5.0, manual_xrange[1] - manual_xrange[0])
        else:
            span = float(min(window_bars, max(40, row_count)))
        right = float(cursor + pad_right)
        visible_range = clamp_visible_range(
            right - span,
            right,
            row_count=row_count,
            cursor=cursor,
            pad_right=pad_right,
        )
        set_xrange = bool(
            force
            or force_clean
            or state.market_data_changed
            or state.cursor_changed
            or state.visible_range_changed
        )
        resolved_manual_xrange = manual_xrange
    else:
        resolved_manual_xrange = manual_xrange
        if resolved_manual_xrange is None:
            if current_xrange is not None:
                resolved_manual_xrange = current_xrange
            else:
                span = float(min(window_bars, max(40, row_count)))
                right = float(min(cursor + pad_right, row_count - 1 + pad_right))
                resolved_manual_xrange = max(0.0, right - span), right
        visible_range = clamp_visible_range(
            *resolved_manual_xrange,
            row_count=row_count,
            cursor=cursor,
            pad_right=pad_right,
        )
        resolved_manual_xrange = visible_range
        set_xrange = bool(force and _ranges_differ(current_xrange, visible_range))

    return ChartRenderPlan(
        is_empty=False,
        visible_range=visible_range,
        manual_xrange=resolved_manual_xrange,
        rebuild_series=rebuild_series,
        set_xrange=set_xrange,
        force_xrange=bool(force),
        refresh_autoscale=refresh_autoscale,
        refresh_markers=refresh_markers,
        refresh_price_line=refresh_price_line,
        refresh_multi_timeframe=refresh_multi_timeframe,
        refresh_status=True,
        refresh_header=True,
    )


__all__ = [
    "ChartRenderPlan",
    "XRange",
    "build_chart_render_plan",
    "clamp_visible_range",
]
