from __future__ import annotations

from render.visible_window import build_rebuild_plan, visible_bar_bounds


def test_visible_bar_bounds_keeps_small_series_whole():
    assert visible_bar_bounds(1000, (10.0, 20.0)) == (0, 1000)


def test_visible_bar_bounds_slices_large_series_with_margin():
    assert visible_bar_bounds(50_000, (10_000.0, 10_200.0)) == (9900, 10300)


def test_rebuild_key_ignores_cursor_when_visible_window_is_old_free_view():
    first = build_rebuild_plan(available_bars=5001, visible_range=(1200.0, 1320.0))
    second = build_rebuild_plan(available_bars=5101, visible_range=(1200.0, 1320.0))

    assert first.start == 1100
    assert first.end == 1420
    assert first.rebuild_key == second.rebuild_key == (None, 1100, 1420)


def test_rebuild_key_includes_available_bars_when_window_contains_latest():
    first = build_rebuild_plan(available_bars=5001, visible_range=(4892.0, 5012.0))
    second = build_rebuild_plan(available_bars=5002, visible_range=(4892.0, 5012.0))

    assert first.rebuild_key == (5001, 4792, 5001)
    assert second.rebuild_key == (5002, 4792, 5002)
