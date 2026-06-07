from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow
from render_state import RenderState
from replay_controller import ReplayController


class _Elapsed:
    def restart(self) -> int:
        return 1000


class _Item:
    def __init__(self) -> None:
        self.calls: list[tuple[np.ndarray, ...]] = []

    def set_data(self, *args) -> None:
        self.calls.append(args)


class _Scatter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def setData(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _large_frame(rows: int = 8928) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bar_index": range(rows),
            "open": np.linspace(100, 110, rows),
            "high": np.linspace(101, 111, rows),
            "low": np.linspace(99, 109, rows),
            "close": np.linspace(100.5, 110.5, rows),
            "volume": np.linspace(1000, 2000, rows),
        }
    )


def test_playback_tick_does_not_call_rebuild_before_render():
    rebuild_calls = []
    render_calls = []
    window = SimpleNamespace(
        df=_large_frame(),
        cursor=100,
        playing=True,
        follow_latest=False,
        _accum=0.0,
        _last_tick=_Elapsed(),
        replay_controller=ReplayController(),
        current_speed=lambda: 6.0,
        _base_bars_per_sec=1.0,
        _last_cursor_for_series=-1,
        _render_dirty=False,
        _last_render_msec=0,
        _render_interval_ms=0,
        _should_render_now=lambda force=False: True,
        _mark_rendered=lambda: None,
        _log_slow_operation=lambda *_args, **_kwargs: None,
        _rebuild_items=lambda *args, **kwargs: rebuild_calls.append((args, kwargs)),
        _render=lambda force=False: render_calls.append(force),
        _log=lambda _message: None,
    )

    MainWindow.on_timer(window)

    assert rebuild_calls == []
    assert render_calls == [False]
    assert window._render_dirty is True


def test_large_rebuild_uses_visible_window_and_skips_same_bounds():
    candle = _Item()
    volume = _Item()
    window = SimpleNamespace(
        df=_large_frame(),
        cursor=5000,
        candleItem=candle,
        volItem=volume,
        _drawn_n=-1,
        _last_rebuild_key=None,
        _current_xrange=lambda: (4950.0, 5050.0),
        _log_slow_operation=lambda *_args, **_kwargs: None,
    )

    MainWindow._rebuild_items(window)
    MainWindow._rebuild_items(window)

    assert len(candle.calls) == 1
    x_values = candle.calls[0][0]
    assert len(x_values) < 300
    assert x_values.min() >= 4800
    assert x_values.max() <= 5100


def test_free_view_rebuild_cache_ignores_cursor_when_visible_window_unchanged():
    candle = _Item()
    volume = _Item()
    window = SimpleNamespace(
        df=_large_frame(),
        cursor=5000,
        candleItem=candle,
        volItem=volume,
        _drawn_n=-1,
        _last_rebuild_key=None,
        _current_xrange=lambda: (1200.0, 1320.0),
        _log_slow_operation=lambda *_args, **_kwargs: None,
    )

    MainWindow._rebuild_items(window, visible_range=(1200.0, 1320.0))
    window.cursor = 5100
    MainWindow._rebuild_items(window, visible_range=(1200.0, 1320.0))

    assert len(candle.calls) == 1


def test_marker_sync_skips_repeated_scatter_updates_when_payload_is_unchanged():
    class CountingEvents(list):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    df = _large_frame()
    open_long = _Scatter()
    open_short = _Scatter()
    close_long = _Scatter()
    close_short = _Scatter()
    window = SimpleNamespace(
        df=df,
        cursor=101,
        events=CountingEvents([
            {
                "event_id": "evt_1",
                "event_type": "OPEN",
                "side": "LONG",
                "bar_index": 100,
                "interval": "5m",
            }
        ]),
        scatter_open_long=open_long,
        scatter_open_short=open_short,
        scatter_close_long=close_long,
        scatter_close_short=close_short,
        _display_interval=lambda: "5m",
        _sample_interval=lambda: "5m",
        _last_marker_sync_key=None,
    )

    MainWindow._sync_markers(window)
    window.cursor = 102
    MainWindow._sync_markers(window)

    assert len(open_long.calls) == 1
    assert len(open_short.calls) == 1
    assert len(close_long.calls) == 1
    assert len(close_short.calls) == 1
    assert window.events.iterations == 1


def test_render_dirty_flags_do_not_refresh_series_or_context_for_header_only_change():
    rebuild_calls = []
    context_calls = []
    df = _large_frame()
    df["open_time_bjt"] = pd.date_range("2024-04-01", periods=len(df), freq="5min", tz="Asia/Shanghai")
    render_state = RenderState()
    render_state.clear()
    render_state.mark_header_changed()
    window = SimpleNamespace(
        df=df,
        cursor=5000,
        pad_right=12,
        window_bars=120,
        follow_latest=False,
        manual_xrange=(1200.0, 1320.0),
        render_state=render_state,
        _render_dirty=True,
        playing=False,
        _current_xrange=lambda: (1200.0, 1320.0),
        _clamp_xrange=lambda x0, x1: (x0, x1),
        _set_xrange=lambda *_args, **_kwargs: None,
        _rebuild_items=lambda *args, **kwargs: rebuild_calls.append((args, kwargs)),
        _autoscale_y=lambda *_args: None,
        _sync_markers=lambda: None,
        _update_current_price_line=lambda *_args: None,
        _refresh_multi_timeframe_context=lambda: context_calls.append(True),
        current_speed=lambda: 1.0,
        session_id="sess_1",
        _is_market_params_dirty=lambda: False,
        _update_header=lambda: None,
        status=SimpleNamespace(setText=lambda _text: None),
        symbolBox=SimpleNamespace(currentText=lambda: "BTCUSDT"),
        intervalBox=SimpleNamespace(currentText=lambda: "5m"),
        events=[],
        _log_slow_operation=lambda *_args, **_kwargs: None,
    )

    MainWindow._render(window, force=False)

    assert rebuild_calls == []
    assert context_calls == []


def test_follow_latest_render_rebuilds_target_window_before_moving_view():
    rebuild_calls = []
    set_xrange_calls = []
    df = _large_frame()
    df["open_time_bjt"] = pd.date_range("2024-04-01", periods=len(df), freq="5min", tz="Asia/Shanghai")
    window = SimpleNamespace(
        df=df,
        cursor=5000,
        pad_right=12,
        window_bars=120,
        follow_latest=True,
        manual_xrange=None,
        _render_dirty=True,
        playing=True,
        _current_xrange=lambda: (4800.0, 4920.0),
        _clamp_xrange=lambda x0, x1: (x0, x1),
        _set_xrange=lambda x0, x1, force=False: set_xrange_calls.append((x0, x1, force)),
        _rebuild_items=lambda *args, **kwargs: rebuild_calls.append((args, kwargs)),
        _autoscale_y=lambda *_args: None,
        _sync_markers=lambda: None,
        _update_current_price_line=lambda *_args: None,
        _refresh_multi_timeframe_context=lambda: None,
        _fmt_num=lambda value: str(value),
        _short_id=lambda value: str(value),
        current_speed=lambda: 6.0,
        session_id="sess_1",
        _is_market_params_dirty=lambda: False,
        _update_header=lambda: None,
        status=SimpleNamespace(setText=lambda _text: None),
        symbolBox=SimpleNamespace(currentText=lambda: "BTCUSDT"),
        intervalBox=SimpleNamespace(currentText=lambda: "5m"),
        events=[],
        _log_slow_operation=lambda *_args, **_kwargs: None,
    )

    MainWindow._render(window, force=True)

    assert rebuild_calls
    assert rebuild_calls[0][1]["visible_range"] == (4892.0, 5012.0)
    assert set_xrange_calls == [(4892.0, 5012.0, True)]
