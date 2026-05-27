from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6 import QtCore

from main_app import MainWindow


def _bars(freq: str = "1min", periods: int = 80) -> pd.DataFrame:
    opens = pd.date_range("2026-05-27 10:00:00", periods=periods, freq=freq, tz="Asia/Shanghai")
    delta = pd.to_timedelta(freq)
    return pd.DataFrame(
        {
            "bar_index": range(periods),
            "open_time_bjt": opens,
            "close_time_bjt": opens + delta,
            "open": range(100, 100 + periods),
            "high": range(101, 101 + periods),
            "low": range(99, 99 + periods),
            "close": range(100, 100 + periods),
            "volume": range(1000, 1000 + periods),
        }
    )


def test_interval_change_with_loaded_data_automatically_requests_dynamic_load():
    calls: list[tuple] = []
    window = SimpleNamespace(
        df=_bars(),
        cursor=37,
        playing=True,
        follow_latest=False,
        manual_xrange=(10.0, 70.0),
        _loading_data=False,
        _display_market_key=("BTCUSDT", "1m", "2026-05-27", "2026-05-27"),
        _loaded_market_key=("BTCUSDT", "1m", "2026-05-27", "2026-05-27"),
        replay_controller=SimpleNamespace(playing=True, accumulated_bars=0.0),
        multiTimeframePanel=SimpleNamespace(mark_stale=lambda: calls.append(("stale",))),
        _update_header=lambda: calls.append(("header",)),
        load_data=lambda **kwargs: calls.append(("load", kwargs)),
    )

    MainWindow.on_interval_changed_for_dynamic_switch(window, "5m")

    assert window._timeframe_switch_pending is True
    assert window._pending_time_anchor_bjt == pd.Timestamp("2026-05-27 10:37:00", tz="Asia/Shanghai")
    assert window._pending_was_playing is True
    assert window.playing is False
    assert ("load", {"dynamic_switch": True, "preserve_time_anchor": True, "auto_resume_after_load": True, "reset_session": False, "use_cache": True}) in calls


class _Text:
    def __init__(self, value: str):
        self.value = value

    def currentText(self) -> str:
        return self.value


class _DateEdit:
    def __init__(self, value: str):
        self.value = value

    def date(self):
        return QtCore.QDate.fromString(self.value, "yyyy-MM-dd")


class _Signal:
    def __init__(self):
        self.requests: list[object] = []

    def emit(self, request):
        self.requests.append(request)


class _Replay:
    def __init__(self):
        self.playing = False
        self.follow_latest = False
        self.accumulated_bars = 0.0
        self.loaded_states: list[tuple] = []

    def load_state(self, *state):
        self.loaded_states.append(state)
        self.playing = bool(state[1])

    def reset(self):
        self.playing = False
        self.accumulated_bars = 0.0


def test_dynamic_load_request_keeps_existing_session_samples_intact():
    signal = _Signal()
    window = SimpleNamespace(
        playing=False,
        _accum=0.0,
        replay_controller=_Replay(),
        cursor=37,
        follow_latest=False,
        symbolBox=_Text("BTCUSDT"),
        intervalBox=_Text("5m"),
        startDate=_DateEdit("2026-05-27"),
        endDate=_DateEdit("2026-05-27"),
        session_id="sess_1m",
        trades=[{"interval": "1m"}],
        events=[{"interval": "1m"}],
        undo_stack=["undo"],
        redo_stack=["redo"],
        restoring_session_id=None,
        restore_snapshot_pending=False,
        _pending_market_key=None,
        _current_market_key=lambda: ("BTCUSDT", "5m", "2026-05-27", "2026-05-27"),
        _normalized_symbol=lambda: "BTCUSDT",
        _set_symbol_value=lambda _symbol: None,
        persist_session_state=lambda: None,
        status=SimpleNamespace(setText=lambda _text: None),
        tr=lambda key: key,
        _loading_data=False,
        app_state=SimpleNamespace(data_load=SimpleNamespace(loading=False, status_message="")),
        _update_load_play_button=lambda: None,
        _update_header=lambda: None,
        requestLoad=signal,
    )

    MainWindow.load_data(window, dynamic_switch=True, preserve_time_anchor=True, reset_session=False, use_cache=True)

    assert window.session_id == "sess_1m"
    assert window.trades == [{"interval": "1m"}]
    assert window.events == [{"interval": "1m"}]
    assert len(signal.requests) == 1
    assert signal.requests[0].interval == "5m"


class _Axis:
    def set_times(self, _values):
        pass


class _View:
    def disableAutoRange(self):
        pass


def _loaded_window(was_playing: bool = True) -> SimpleNamespace:
    old = _bars()
    calls: list[tuple] = []
    replay = _Replay()
    window = SimpleNamespace(
        _loading_data=True,
        app_state=SimpleNamespace(data_load=SimpleNamespace(loading=True, bar_count=0, source="-", quality_status="-")),
        _log=lambda message: calls.append(("log", message)),
        _timeframe_switch_pending=True,
        _pending_time_anchor_bjt=pd.Timestamp("2026-05-27 10:37:00", tz="Asia/Shanghai"),
        _pending_view_time_span_seconds=3600.0,
        _pending_was_playing=was_playing,
        _pending_follow_latest=False,
        _pending_switch_from_interval="1m",
        _pending_switch_to_interval="5m",
        _pending_market_key=("BTCUSDT", "5m", "2026-05-27", "2026-05-27"),
        _display_market_key=("BTCUSDT", "1m", "2026-05-27", "2026-05-27"),
        _loaded_market_key=("BTCUSDT", "1m", "2026-05-27", "2026-05-27"),
        _sample_market_key=("BTCUSDT", "1m", "2026-05-27", "2026-05-27"),
        df=old,
        cursor=37,
        playing=False,
        follow_latest=False,
        replay_controller=replay,
        _drawn_n=-1,
        _last_cursor_for_series=-1,
        _accum=0.0,
        market_dirty=False,
        _is_market_params_dirty=lambda: False,
        _accept_loaded_market_key=lambda frame, successful=True: setattr(window, "_loaded_market_key", ("BTCUSDT", "5m", "2026-05-27", "2026-05-27")),
        _persist_loaded_market_data=lambda: None,
        axis_price=_Axis(),
        axis_vol=_Axis(),
        restore_snapshot_pending=False,
        trades=[{"trade_id": "trade_1", "interval": "1m"}],
        events=[{"event_id": "evt_1", "interval": "1m"}],
        _trade_by_id={"trade_1": {"interval": "1m"}},
        _event_by_id={"evt_1": {"interval": "1m"}},
        _refresh_tables=lambda: calls.append(("refresh_tables",)),
        vb_price=_View(),
        vb_vol=_View(),
        _rebuild_items=lambda: calls.append(("rebuild",)),
        window_bars=140,
        manual_xrange=(10.0, 70.0),
        _set_xrange=lambda x0, x1, force=False: calls.append(("range", x0, x1, force)),
        status=SimpleNamespace(setText=lambda text: calls.append(("status", text))),
        tr=lambda key: key,
        symbolBox=_Text("BTCUSDT"),
        intervalBox=_Text("5m"),
        _update_load_play_button=lambda: calls.append(("button",)),
        _render=lambda force=False: calls.append(("render", force)),
        multiTimeframePanel=SimpleNamespace(mark_stale=lambda: None),
        _load_multi_timeframe_context=lambda: None,
        _refresh_multi_timeframe_context=lambda: None,
        _show_market_dirty_feedback=lambda: None,
        _update_trade_buttons_enabled=lambda: None,
        _calls=calls,
    )
    return window


@pytest.mark.parametrize(("was_playing", "expected_playing"), [(True, True), (False, False)])
def test_dynamic_switch_maps_cursor_and_restores_previous_play_state(was_playing: bool, expected_playing: bool):
    window = _loaded_window(was_playing)

    MainWindow.on_loaded(window, _bars("5min", 20), "Loaded cache.")

    assert window.cursor == 7
    assert window.playing is expected_playing
    assert window.trades == [{"trade_id": "trade_1", "interval": "1m"}]
    assert window.events == [{"event_id": "evt_1", "interval": "1m"}]
    assert window._timeframe_switch_pending is False
    assert window.manual_xrange[1] - window.manual_xrange[0] < 20


def test_dynamic_switch_failure_preserves_old_frame_and_cursor(monkeypatch):
    window = _loaded_window(True)
    original_frame = window.df
    monkeypatch.setattr("main_app.QtWidgets.QMessageBox.critical", lambda *_args, **_kwargs: None)

    MainWindow.on_loaded(window, pd.DataFrame(), "加载失败：offline")

    assert window.df is original_frame
    assert window.cursor == 37
    assert window.playing is False
    assert window.trades == [{"trade_id": "trade_1", "interval": "1m"}]
