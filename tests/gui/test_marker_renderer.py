from __future__ import annotations

import numpy as np
import pandas as pd

from render.marker_renderer import MarkerPayloadCache, build_marker_payloads


def _frame(rows: int = 8) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_index": range(rows),
            "open": np.linspace(100.0, 107.0, rows),
            "high": np.linspace(101.0, 108.0, rows),
            "low": np.linspace(99.0, 106.0, rows),
            "close": np.linspace(100.5, 107.5, rows),
            "volume": np.linspace(1000.0, 1007.0, rows),
        }
    )


def test_marker_payloads_filter_future_and_other_display_interval():
    payload = build_marker_payloads(
        _frame(),
        [
            {"event_type": "OPEN", "side": "LONG", "bar_index": 1, "interval": "5m"},
            {"event_type": "OPEN", "side": "LONG", "bar_index": 6, "interval": "5m"},
            {"event_type": "OPEN", "side": "SHORT", "bar_index": 2, "interval": "1m"},
        ],
        cursor=3,
        display_interval="5m",
        sample_interval="5m",
    )

    assert payload.open_long == ((1, 100.0),)
    assert payload.open_short == ()
    assert payload.marker_key == ("5m", ((1, 100.0),), (), (), ())


def test_marker_payloads_keep_existing_marker_price_semantics():
    payload = build_marker_payloads(
        _frame(),
        [
            {"event_type": "OPEN", "side": "LONG", "bar_index": 1, "interval": "5m"},
            {"event_type": "OPEN", "side": "SHORT", "bar_index": 2, "interval": "5m"},
            {"event_type": "CLOSE", "side": "LONG", "bar_index": 3, "interval": "5m"},
            {"event_type": "CLOSE", "side": "SHORT", "bar_index": 4, "interval": "5m"},
        ],
        cursor=4,
        display_interval="5m",
        sample_interval="5m",
    )

    assert payload.open_long == ((1, 100.0),)
    assert payload.open_short == ((2, 103.0),)
    assert payload.close_long == ((3, 104.0),)
    assert payload.close_short == ((4, 103.0),)


def test_marker_payload_key_is_stable_when_cursor_moves_without_new_visible_events():
    events = [{"event_type": "OPEN", "side": "LONG", "bar_index": 1, "interval": "5m"}]

    first = build_marker_payloads(_frame(), events, cursor=2, display_interval="5m", sample_interval="5m")
    second = build_marker_payloads(_frame(), events, cursor=3, display_interval="5m", sample_interval="5m")

    assert first.marker_key == second.marker_key


def test_marker_payload_cache_reuses_payload_without_rewalking_events_inside_same_boundary():
    class CountingEvents(list):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    events = CountingEvents(
        [
            {"event_type": "OPEN", "side": "LONG", "bar_index": 1, "interval": "5m"},
            {"event_type": "CLOSE", "side": "LONG", "bar_index": 6, "interval": "5m"},
        ]
    )
    cache = MarkerPayloadCache()
    frame = _frame()

    first = cache.payload_for(
        frame,
        events,
        cursor=2,
        display_interval="5m",
        sample_interval="5m",
        events_changed=True,
    )
    second = cache.payload_for(
        frame,
        events,
        cursor=3,
        display_interval="5m",
        sample_interval="5m",
        events_changed=False,
    )

    assert first is second
    assert events.iterations == 1


def test_marker_payload_cache_refreshes_when_cursor_crosses_event_boundary():
    frame = _frame()
    events = [
        {"event_type": "OPEN", "side": "LONG", "bar_index": 1, "interval": "5m"},
        {"event_type": "CLOSE", "side": "LONG", "bar_index": 6, "interval": "5m"},
    ]
    cache = MarkerPayloadCache()

    before_close = cache.payload_for(
        frame,
        events,
        cursor=5,
        display_interval="5m",
        sample_interval="5m",
        events_changed=True,
    )
    at_close = cache.payload_for(
        frame,
        events,
        cursor=6,
        display_interval="5m",
        sample_interval="5m",
    )

    assert before_close.close_long == ()
    assert at_close.close_long == ((6, 107.0),)
    assert at_close is not before_close


def test_marker_payload_cache_rebuilds_same_length_event_replacement_when_marked_changed():
    frame = _frame()
    events = [{"event_type": "OPEN", "side": "LONG", "bar_index": 1, "interval": "5m"}]
    cache = MarkerPayloadCache()

    first = cache.payload_for(
        frame,
        events,
        cursor=4,
        display_interval="5m",
        sample_interval="5m",
        events_changed=True,
    )
    events[0] = {"event_type": "OPEN", "side": "LONG", "bar_index": 3, "interval": "5m"}
    second = cache.payload_for(
        frame,
        events,
        cursor=4,
        display_interval="5m",
        sample_interval="5m",
        events_changed=True,
    )

    assert first.open_long == ((1, 100.0),)
    assert second.open_long == ((3, 102.0),)
