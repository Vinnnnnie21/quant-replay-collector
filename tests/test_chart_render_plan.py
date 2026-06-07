from __future__ import annotations

from render.chart_render_plan import build_chart_render_plan
from render_state import RenderState


def test_follow_latest_plan_targets_cursor_time_window_and_refreshes_cursor_dependents():
    state = RenderState()
    state.clear()
    state.mark_cursor_changed()

    plan = build_chart_render_plan(
        state=state,
        force=False,
        render_dirty=True,
        row_count=8928,
        cursor=5000,
        pad_right=12,
        window_bars=120,
        follow_latest=True,
        current_xrange=(4800.0, 4920.0),
        manual_xrange=None,
    )

    assert plan is not None
    assert plan.visible_range == (4892.0, 5012.0)
    assert plan.rebuild_series is True
    assert plan.set_xrange is True
    assert plan.refresh_markers is True
    assert plan.refresh_multi_timeframe is True


def test_free_view_header_only_plan_keeps_visible_window_without_rebuilding_series():
    state = RenderState()
    state.clear()
    state.mark_header_changed()

    plan = build_chart_render_plan(
        state=state,
        force=False,
        render_dirty=True,
        row_count=8928,
        cursor=5000,
        pad_right=12,
        window_bars=120,
        follow_latest=False,
        current_xrange=(1200.0, 1320.0),
        manual_xrange=(1200.0, 1320.0),
    )

    assert plan is not None
    assert plan.visible_range == (1200.0, 1320.0)
    assert plan.rebuild_series is False
    assert plan.set_xrange is False
    assert plan.refresh_multi_timeframe is False
    assert plan.refresh_header is True


def test_clean_plan_skips_render_when_not_forced():
    state = RenderState()
    state.clear()

    assert build_chart_render_plan(
        state=state,
        force=False,
        render_dirty=False,
        row_count=8928,
        cursor=5000,
        pad_right=12,
        window_bars=120,
        follow_latest=False,
        current_xrange=(1200.0, 1320.0),
        manual_xrange=(1200.0, 1320.0),
    ) is None


def test_forced_clean_plan_refreshes_cursor_dependent_components():
    state = RenderState()
    state.clear()

    plan = build_chart_render_plan(
        state=state,
        force=True,
        render_dirty=False,
        row_count=8928,
        cursor=5000,
        pad_right=12,
        window_bars=120,
        follow_latest=False,
        current_xrange=(1200.0, 1320.0),
        manual_xrange=(1200.0, 1320.0),
    )

    assert plan is not None
    assert plan.rebuild_series is True
    assert plan.refresh_autoscale is True
    assert plan.refresh_markers is True
    assert plan.refresh_multi_timeframe is True
