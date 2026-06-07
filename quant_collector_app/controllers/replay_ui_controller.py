"""Main-window replay controls layered over the Qt-free ReplayController."""

from __future__ import annotations

import time

from PySide6 import QtCore

try:
    from app_logger import get_logger
    from render_state import RenderState
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger
    from ..render_state import RenderState


logger = get_logger(__name__)


def _render_state(window) -> RenderState:
    getter = getattr(window, "_chart_render_state", None)
    if callable(getter):
        return getter()
    state = getattr(window, "render_state", None)
    if state is None:
        state = RenderState()
        window.render_state = state
    return state


def _log_slow(window, name: str, started: float) -> None:
    callback = getattr(window, "_log_slow_operation", None)
    if callable(callback):
        callback(name, started)


def on_speed_changed(window, _value: int) -> None:
    window.speedLabel.setText(f"速度: {window.current_speed():.1f}x")


def current_speed(window) -> float:
    return max(0.1, float(window.speedSlider.value()) / 10.0)


def on_timer(window) -> None:
    started = time.perf_counter()
    if len(window.df) == 0:
        return
    elapsed = window._last_tick.restart() / 1000.0
    try:
        was_playing = bool(window.playing)
        window.replay_controller.load_state(
            window.cursor,
            window.playing,
            window.follow_latest,
            window._accum,
        )
        changed = window.replay_controller.tick(
            elapsed,
            len(window.df),
            window.current_speed(),
            window._base_bars_per_sec,
        )
        window.cursor = window.replay_controller.cursor
        window.playing = window.replay_controller.playing
        window._accum = window.replay_controller.accumulated_bars
        if was_playing and not window.playing:
            window.analysis_refresh_controller.resume_if_idle()
        if changed or window.cursor != window._last_cursor_for_series:
            window._last_cursor_for_series = int(window.cursor)
            _render_state(window).mark_cursor_changed()
            window._render_dirty = True
        if window._should_render_now(force=False):
            window._render(force=False)
            window._mark_rendered()
    except Exception as exc:
        logger.exception("播放定时器异常")
        window._log(f"timer异常：{type(exc).__name__}: {exc}")
        window.playing = False
    finally:
        _log_slow(window, "on_timer", started)


def toggle_play(window) -> None:
    if len(window.df) == 0:
        return
    if window._is_market_params_dirty():
        window.on_market_params_changed()
        return
    window.replay_controller.load_state(
        window.cursor,
        window.playing,
        window.follow_latest,
        window._accum,
    )
    window.playing = window.replay_controller.toggle_play(len(window.df))
    window._log("播放" if window.playing else "暂停")
    window._last_tick.restart()
    window._update_load_play_button()
    _render_state(window).mark_header_changed()
    window._render_dirty = True
    window._render(force=False)
    if not window.playing:
        window.analysis_refresh_controller.resume_if_idle()


def step_once(window) -> None:
    if len(window.df) == 0:
        return
    window.replay_controller.load_state(
        window.cursor,
        window.playing,
        window.follow_latest,
        window._accum,
    )
    window.cursor = window.replay_controller.step(len(window.df))
    window.playing = window.replay_controller.playing
    window._accum = window.replay_controller.accumulated_bars
    window._last_cursor_for_series = int(window.cursor)
    window._update_load_play_button()
    _render_state(window).mark_cursor_changed()
    window._render(force=True)


def jump_to_end(window) -> None:
    if len(window.df) == 0:
        return
    window.replay_controller.load_state(
        window.cursor,
        window.playing,
        window.follow_latest,
        window._accum,
    )
    window.cursor = window.replay_controller.jump_end(len(window.df))
    window._last_cursor_for_series = int(window.cursor)
    window.user_view_lock = False
    window.playing = window.replay_controller.playing
    window._update_load_play_button()
    _render_state(window).mark_cursor_changed()
    _render_state(window).mark_visible_range_changed()
    window._render(force=True)


def toggle_follow(window) -> None:
    window.replay_controller.load_state(
        window.cursor,
        window.playing,
        window.follow_latest,
        window._accum,
    )
    window.follow_latest = window.replay_controller.toggle_follow()
    window._log(f"跟随最新：{'开启' if window.follow_latest else '关闭'}")
    if window.follow_latest:
        window.user_view_lock = False
        current = window._current_xrange()
        if current is not None:
            window.manual_xrange = current
    _render_state(window).mark_visible_range_changed()
    _render_state(window).mark_header_changed()
    window._render(force=True)


def on_user_interaction(window) -> None:
    window.user_view_lock = True
    window.last_user_interaction = QtCore.QDateTime.currentMSecsSinceEpoch() / 1000.0
    if window.follow_latest:
        window.follow_latest = False
        window._log("检测到手动缩放/拖动，已自动退出跟随最新。")


def reset_view(window) -> None:
    if len(window.df) == 0:
        return
    span = min(window.window_bars, max(40, min(len(window.df), 120)))
    x1 = float(min(window.cursor + window.pad_right, len(window.df) - 1 + window.pad_right))
    x0 = max(0.0, x1 - span)
    window.manual_xrange = (x0, x1)
    window.user_view_lock = False
    window._set_xrange(x0, x1, force=True)
    _render_state(window).mark_visible_range_changed()
    window._render(force=True)
    window._log(window.tr("reset_zoom_done"))


__all__ = [
    "current_speed",
    "jump_to_end",
    "on_speed_changed",
    "on_timer",
    "on_user_interaction",
    "reset_view",
    "step_once",
    "toggle_follow",
    "toggle_play",
]
