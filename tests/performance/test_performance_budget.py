from __future__ import annotations

from perf.timing import PerfTimer
from perf.throttle import throttle
from views.chart_view import visible_bar_bounds


def test_visible_window_limits_large_render_payload():
    assert visible_bar_bounds(1000, (0.0, 100.0)) == (0, 1000)
    start, end = visible_bar_bounds(50000, (10000.0, 10200.0))
    assert (start, end) == (9900, 10300)
    assert end - start < 1000


def test_throttle_skips_repeated_immediate_calls():
    values = []

    def append_value():
        values.append(1)

    limited = throttle(append_value, 1000)
    limited()
    limited()
    assert values == [1]


def test_perf_timer_reports_elapsed_value():
    reported = {}
    with PerfTimer("work", lambda name, seconds: reported.setdefault(name, seconds)) as timer:
        sum(range(10))
    assert timer.elapsed_seconds >= 0
    assert reported["work"] == timer.elapsed_seconds
