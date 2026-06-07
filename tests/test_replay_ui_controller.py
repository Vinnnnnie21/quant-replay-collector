from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from controllers.replay_ui_controller import current_speed, step_once


def test_replay_ui_controller_steps_and_preserves_speed_semantics():
    calls: list[tuple] = []
    replay = SimpleNamespace(
        cursor=0,
        playing=False,
        accumulated_bars=0.0,
        load_state=lambda *state: calls.append(("load", state)),
        step=lambda _length: 4,
    )
    window = SimpleNamespace(
        df=[1, 2, 3, 4, 5],
        cursor=3,
        playing=False,
        follow_latest=False,
        _accum=0.0,
        replay_controller=replay,
        speedSlider=SimpleNamespace(value=lambda: 63),
        _last_cursor_for_series=-1,
        _update_load_play_button=lambda: None,
        _render=lambda force=False: calls.append(("render", force)),
    )

    step_once(window)

    assert current_speed(window) == 6.3
    assert window.cursor == 4
    assert ("render", True) in calls
