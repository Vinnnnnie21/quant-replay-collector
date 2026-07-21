from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
from PySide6 import QtCore

from render.chart_render_adapter import (
    autoscale_y,
    clamp_xrange,
    current_xrange,
    on_chart_drag_finished,
    on_chart_drag_started,
    on_price_view_range_changed,
    render_active_drag_frame,
    should_render_now,
)
from render_state import RenderState


def test_chart_render_adapter_reads_and_clamps_visible_range():
    window = SimpleNamespace(
        vb_price=SimpleNamespace(viewRange=lambda: ((2.5, 8.5), (0.0, 1.0))),
        df=pd.DataFrame({"close": range(10)}),
        cursor=7,
        pad_right=2,
        playing=False,
        _last_render_msec=0,
        _render_interval_ms=50,
    )

    assert current_xrange(window) == (2.5, 8.5)
    assert clamp_xrange(window, -10.0, 100.0) == (0.0, 110.0)
    assert should_render_now(window) is True


def test_recent_chart_interaction_uses_120hz_render_budget():
    now = QtCore.QDateTime.currentMSecsSinceEpoch()
    state = RenderState()
    state.clear()
    state.mark_visible_range_changed()
    window = SimpleNamespace(
        playing=False,
        _render_dirty=True,
        render_state=state,
        last_user_interaction=now / 1000.0,
        _last_render_msec=now - 5,
        _interaction_render_interval_ms=8,
        _render_interval_ms=50,
    )

    assert should_render_now(window) is False

    window._last_render_msec = now - 8

    assert should_render_now(window) is True


def test_follow_autoscale_fits_visible_wicks_with_three_percent_padding():
    price_ranges = []
    volume_ranges = []
    window = SimpleNamespace(
        df=pd.DataFrame(
            {
                "low": [95.0, 90.0, 94.0],
                "high": [105.0, 110.0, 108.0],
                "volume": [10.0, 20.0, 15.0],
            }
        ),
        cursor=2,
        vb_price=SimpleNamespace(yManual=False),
        pricePlot=SimpleNamespace(setYRange=lambda low, high, padding=0.0: price_ranges.append((low, high, padding))),
        volPlot=SimpleNamespace(setYRange=lambda low, high, padding=0.0: volume_ranges.append((low, high, padding))),
    )

    autoscale_y(window, 0.0, 2.0)

    assert price_ranges == [(89.4, 110.6, 0.0)]
    assert volume_ranges == [(0.0, 20.0, 0.0)]


def test_active_drag_updates_manual_range_without_scheduling_chart_rebuild():
    state = RenderState()
    state.clear()
    window = SimpleNamespace(
        _programmatic_view_update=False,
        _chart_drag_active=True,
        manual_xrange=None,
        render_state=state,
        _render_dirty=False,
    )

    on_price_view_range_changed(window, ((10.0, 110.0), (90.0, 120.0)))

    assert window.manual_xrange == (10.0, 110.0)
    assert window._render_dirty is False
    assert state.any_dirty() is False


def test_drag_lifecycle_defers_work_until_release():
    state = RenderState()
    state.clear()
    renders = []
    window = SimpleNamespace(
        _chart_drag_active=False,
        render_state=state,
        _render_dirty=False,
        _render=lambda force=False: renders.append(force),
    )

    on_chart_drag_started(window)
    assert window._chart_drag_active is True
    assert state.any_dirty() is False

    on_chart_drag_finished(window)
    assert window._chart_drag_active is False
    assert window._render_dirty is True
    assert state.visible_range_changed is True
    assert renders == [False]


def test_playback_render_is_suspended_while_chart_drag_is_active():
    state = RenderState()
    state.clear()
    state.mark_cursor_changed()
    window = SimpleNamespace(
        playing=True,
        _chart_drag_active=True,
        _render_dirty=True,
        render_state=state,
        _last_render_msec=0,
        _render_interval_ms=0,
    )

    assert should_render_now(window) is False


def test_active_drag_frame_appends_cursor_data_without_moving_viewport():
    rebuilds = []
    price_updates = []
    window = SimpleNamespace(
        df=pd.DataFrame({"close": [100.0, 101.0]}),
        cursor=1,
        _current_xrange=lambda: (0.25, 20.25),
        _rebuild_items=lambda **kwargs: rebuilds.append(kwargs),
        _update_current_price_line=lambda x0, x1: price_updates.append((x0, x1)),
    )

    render_active_drag_frame(window)

    assert rebuilds == [{"visible_range": (0.25, 20.25)}]
    assert price_updates == [(0.25, 20.25)]
