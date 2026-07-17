from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6 import QtCore

from types import SimpleNamespace

import pandas as pd

from controllers.market_data_controller import (
    accept_loaded_market_key,
    current_market_key,
    is_market_params_dirty,
    load_data,
    on_loaded,
    on_interval_changed_for_dynamic_switch,
)
from state import AppState
from task_lifecycle import BackgroundTaskLifecycle, TaskState


class _Text:
    def __init__(self, value: str):
        self.value = value

    def currentText(self) -> str:
        return self.value


class _Date:
    def __init__(self, value: str):
        self.value = value

    def date(self):
        return self

    def toString(self, _format: str) -> str:
        return self.value

    def __gt__(self, other) -> bool:
        return self.value > other.value


def test_market_data_controller_tracks_loaded_and_current_market_keys():
    window = SimpleNamespace(
        symbolBox=_Text("btcusdt"),
        intervalBox=_Text("5m"),
        startDate=_Date("2024-04-01"),
        endDate=_Date("2024-05-01"),
        df=pd.DataFrame({"close": [1.0]}),
        _loaded_market_key=None,
        _display_market_key=None,
        _sample_market_key=None,
        _pending_market_key=None,
        trades=[],
        events=[],
    )

    key = current_market_key(window)
    window._current_market_key = lambda: current_market_key(window)
    window._is_market_params_dirty = lambda: is_market_params_dirty(window)
    accept_loaded_market_key(window, window.df)

    assert key == ("BTCUSDT", "5m", "2024-04-01", "2024-05-01")
    assert window._loaded_market_key == key
    assert window._sample_market_key == key
    assert window.market_dirty is False


def test_market_data_load_registers_shared_background_task() -> None:
    emitted: list[object] = []
    lifecycle = BackgroundTaskLifecycle()
    window = SimpleNamespace(
        playing=False,
        follow_latest=False,
        cursor=0,
        _accum=0.0,
        replay_controller=SimpleNamespace(load_state=lambda *_args: None),
        _normalized_symbol=lambda: "BTCUSDT",
        _set_symbol_value=lambda _symbol: None,
        intervalBox=_Text("1m"),
        startDate=SimpleNamespace(date=lambda: QtCore.QDate(2026, 1, 1)),
        endDate=SimpleNamespace(date=lambda: QtCore.QDate(2026, 1, 2)),
        _current_market_key=lambda: ("BTCUSDT", "1m", "2026-01-01", "2026-01-02"),
        restoring_session_id=None,
        session_id="sess_1",
        trades=[],
        events=[],
        _trade_by_id={},
        _event_by_id={},
        undo_stack=[],
        redo_stack=[],
        restore_snapshot_pending=False,
        status=SimpleNamespace(setText=lambda _text: None),
        tr=lambda key: key,
        _loading_data=False,
        app_state=AppState(),
        _update_load_play_button=lambda: None,
        _update_header=lambda: None,
        requestLoad=SimpleNamespace(emit=emitted.append),
        loader=SimpleNamespace(abort=lambda: None),
        task_lifecycle=lifecycle,
    )

    load_data(window, dynamic_switch=True)

    assert len(emitted) == 1
    assert lifecycle.state("market_data_load") is TaskState.RUNNING


def test_restore_load_does_not_persist_target_before_snapshot_is_loaded() -> None:
    emitted: list[object] = []
    lifecycle = BackgroundTaskLifecycle()
    window = SimpleNamespace(
        playing=False,
        follow_latest=False,
        cursor=0,
        _accum=0.0,
        replay_controller=SimpleNamespace(load_state=lambda *_args: None),
        _normalized_symbol=lambda: "BTCUSDT",
        _set_symbol_value=lambda _symbol: None,
        intervalBox=_Text("1m"),
        startDate=SimpleNamespace(date=lambda: QtCore.QDate(2026, 1, 1)),
        endDate=SimpleNamespace(date=lambda: QtCore.QDate(2026, 1, 2)),
        _current_market_key=lambda: ("BTCUSDT", "1m", "2026-01-01", "2026-01-02"),
        restoring_session_id="sess_target",
        session_id="sess_target",
        trades=[{"trade_id": "old-current-session-trade"}],
        events=[],
        _trade_by_id={},
        _event_by_id={},
        undo_stack=[],
        redo_stack=[],
        restore_snapshot_pending=True,
        persist_session_state=lambda: (_ for _ in ()).throw(
            AssertionError("target must not be saved before its snapshot is restored")
        ),
        status=SimpleNamespace(setText=lambda _text: None),
        tr=lambda key: key,
        _loading_data=False,
        app_state=AppState(),
        _update_load_play_button=lambda: None,
        _update_header=lambda: None,
        requestLoad=SimpleNamespace(emit=emitted.append),
        loader=SimpleNamespace(abort=lambda: None),
        task_lifecycle=lifecycle,
    )

    accepted = load_data(window, restore=True, reset_session=False)

    assert accepted is True
    assert len(emitted) == 1


def test_failed_market_data_load_releases_shared_background_task() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("market_data_load")
    logs: list[str] = []
    window = SimpleNamespace(
        _loading_data=True,
        app_state=AppState(),
        _log=logs.append,
        _timeframe_switch_pending=True,
        _pending_switch_from_interval=None,
        _pending_market_key=("BTCUSDT", "5m", "2026-01-01", "2026-01-02"),
        market_dirty=True,
        _update_load_play_button=lambda: None,
        _render=lambda **_kwargs: None,
        status=SimpleNamespace(setText=lambda _text: None),
        tr=lambda key: key,
        task_lifecycle=lifecycle,
    )

    on_loaded(window, pd.DataFrame(), "加载失败：network error")

    assert lifecycle.state("market_data_load") is TaskState.FAILED
    assert lifecycle.active_tasks == ()


def test_market_data_load_after_shutdown_does_not_mutate_session_or_emit_request() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.begin_shutdown()
    replay_calls: list[tuple] = []
    persisted: list[bool] = []
    emitted: list[object] = []
    window = SimpleNamespace(
        task_lifecycle=lifecycle,
        playing=True,
        follow_latest=True,
        cursor=7,
        _accum=3.0,
        replay_controller=SimpleNamespace(load_state=lambda *args: replay_calls.append(args)),
        _normalized_symbol=lambda: "BTCUSDT",
        _set_symbol_value=lambda _symbol: None,
        intervalBox=_Text("1m"),
        startDate=SimpleNamespace(date=lambda: QtCore.QDate(2026, 1, 1)),
        endDate=SimpleNamespace(date=lambda: QtCore.QDate(2026, 1, 2)),
        _current_market_key=lambda: ("BTCUSDT", "1m", "2026-01-01", "2026-01-02"),
        restoring_session_id=None,
        session_id="sess_original",
        _new_id=lambda _prefix: "sess_replaced",
        trades=[{"trade_id": "t1"}],
        events=[{"event_id": "e1"}],
        _trade_by_id={"t1": {}},
        _event_by_id={"e1": {}},
        undo_stack=["undo"],
        redo_stack=["redo"],
        restore_snapshot_pending=True,
        persist_session_state=lambda: persisted.append(True),
        requestLoad=SimpleNamespace(emit=emitted.append),
    )

    load_data(window, reset_session=True)

    assert window.session_id == "sess_original"
    assert window.trades == [{"trade_id": "t1"}]
    assert window.events == [{"event_id": "e1"}]
    assert window.undo_stack == ["undo"]
    assert window.redo_stack == ["redo"]
    assert window.playing is True
    assert window._accum == 3.0
    assert replay_calls == []
    assert persisted == []
    assert emitted == []
    assert lifecycle.state("market_data_load") is None


def test_market_data_load_rejected_by_running_lifecycle_does_not_mutate_business_state() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("daily_backup")
    replay_calls: list[tuple] = []
    persisted: list[bool] = []
    emitted: list[object] = []
    window = SimpleNamespace(
        task_lifecycle=lifecycle,
        playing=True,
        follow_latest=True,
        cursor=7,
        _accum=3.0,
        replay_controller=SimpleNamespace(load_state=lambda *args: replay_calls.append(args)),
        _normalized_symbol=lambda: "BTCUSDT",
        _set_symbol_value=lambda _symbol: None,
        intervalBox=_Text("1m"),
        startDate=SimpleNamespace(date=lambda: QtCore.QDate(2026, 1, 1)),
        endDate=SimpleNamespace(date=lambda: QtCore.QDate(2026, 1, 2)),
        _current_market_key=lambda: ("BTCUSDT", "1m", "2026-01-01", "2026-01-02"),
        restoring_session_id=None,
        session_id="sess_original",
        _new_id=lambda _prefix: "sess_replaced",
        trades=[{"trade_id": "t1"}],
        events=[{"event_id": "e1"}],
        _trade_by_id={"t1": {}},
        _event_by_id={"e1": {}},
        undo_stack=["undo"],
        redo_stack=["redo"],
        restore_snapshot_pending=True,
        persist_session_state=lambda: persisted.append(True),
        requestLoad=SimpleNamespace(emit=emitted.append),
        loader=SimpleNamespace(abort=lambda: None),
    )

    accepted = load_data(window, reset_session=True)

    assert accepted is False
    assert window.session_id == "sess_original"
    assert window.trades == [{"trade_id": "t1"}]
    assert window.playing is True
    assert window._accum == 3.0
    assert replay_calls == []
    assert persisted == []
    assert emitted == []


def test_dynamic_timeframe_switch_after_shutdown_does_not_change_pending_state() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.begin_shutdown()
    header_updates: list[bool] = []
    window = SimpleNamespace(
        task_lifecycle=lifecycle,
        df=pd.DataFrame({"close": [1.0]}),
        _loading_data=True,
        _queued_dynamic_interval=None,
        _update_header=lambda: header_updates.append(True),
    )

    on_interval_changed_for_dynamic_switch(window, "5m")

    assert header_updates == []
    assert window._queued_dynamic_interval is None
    assert lifecycle.state("market_data_load") is None


def test_dynamic_timeframe_switch_during_background_task_does_not_change_replay_state() -> None:
    lifecycle = BackgroundTaskLifecycle()
    lifecycle.start("analysis_refresh")
    window = SimpleNamespace(
        task_lifecycle=lifecycle,
        df=pd.DataFrame({"open_time_bjt": ["2026-01-01T00:00:00+08:00"], "close": [1.0]}),
        _loading_data=False,
        _queued_dynamic_interval=None,
        playing=True,
        cursor=0,
        trades=[],
        events=[],
        _timeframe_switch_pending=False,
        _update_header=lambda: None,
    )

    on_interval_changed_for_dynamic_switch(window, "5m")

    assert window.playing is True
    assert window._timeframe_switch_pending is False
    assert window._queued_dynamic_interval is None
