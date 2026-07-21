from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from controllers.replay_ui_controller import adjust_speed, current_speed, jump_to_end, step_once, toggle_follow


def _window_with_speed(slider_value: int):
    return SimpleNamespace(speedSlider=SimpleNamespace(value=lambda: slider_value))


@pytest.mark.parametrize(
    ("slider_value", "expected_speed"),
    [
        (0, 0.1),
        (1, 0.2),
        (2, 0.5),
        (3, 1.0),
        (4, 2.0),
        (5, 5.0),
        (6, 10.0),
        (-99, 0.1),
        (99, 10.0),
    ],
)
def test_current_speed_uses_centered_logarithmic_speed_stops(slider_value, expected_speed):
    assert current_speed(_window_with_speed(slider_value)) == expected_speed


def test_arrow_speed_adjustment_moves_one_stop_and_clamps():
    class Slider:
        def __init__(self, value: int):
            self._value = value

        def value(self):
            return self._value

        def minimum(self):
            return 0

        def maximum(self):
            return 6

        def setValue(self, value):
            self._value = value

    slider = Slider(3)
    window = SimpleNamespace(speedSlider=slider)

    adjust_speed(window, -1)
    assert slider.value() == 2
    adjust_speed(window, 1)
    assert slider.value() == 3
    slider.setValue(0)
    adjust_speed(window, -1)
    assert slider.value() == 0
    slider.setValue(6)
    adjust_speed(window, 1)
    assert slider.value() == 6


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
        speedSlider=SimpleNamespace(value=lambda: 3),
        _last_cursor_for_series=-1,
        _update_load_play_button=lambda: None,
        _apply_tp_sl_triggers=lambda _old, _new: None,
        _render=lambda force=False: calls.append(("render", force)),
    )

    step_once(window)

    assert current_speed(window) == 1.0
    assert window.cursor == 4
    assert ("render", True) in calls


def test_replay_ui_controller_scans_tp_sl_between_previous_and_new_cursor():
    scans: list[tuple[int, int]] = []
    replay = SimpleNamespace(
        cursor=0,
        playing=False,
        accumulated_bars=0.0,
        load_state=lambda *_state: None,
        step=lambda _length: 4,
        jump_end=lambda _length: 6,
    )
    window = SimpleNamespace(
        df=[1, 2, 3, 4, 5, 6, 7],
        cursor=3,
        playing=False,
        follow_latest=False,
        _accum=0.0,
        replay_controller=replay,
        _last_cursor_for_series=-1,
        user_view_lock=False,
        _update_load_play_button=lambda: None,
        _apply_tp_sl_triggers=lambda old, new: scans.append((old, new)),
        _render=lambda force=False: None,
    )

    step_once(window)
    jump_to_end(window)

    assert scans == [(3, 4), (4, 6)]


def test_enabling_follow_latest_restores_automatic_y_fitting():
    calls: list[str] = []
    replay = SimpleNamespace(
        load_state=lambda *_state: None,
        toggle_follow=lambda: True,
    )
    window = SimpleNamespace(
        cursor=10,
        playing=False,
        follow_latest=False,
        _accum=0.0,
        replay_controller=replay,
        user_view_lock=True,
        manual_xrange=(0.0, 5.0),
        vb_price=SimpleNamespace(reset_y_auto=lambda: calls.append("reset_y")),
        _current_xrange=lambda: (2.0, 8.0),
        _log=lambda _message: None,
        _render=lambda force=False: calls.append(f"render:{force}"),
    )

    toggle_follow(window)

    assert window.follow_latest is True
    assert window.user_view_lock is False
    assert "reset_y" in calls
    assert "render:True" in calls
