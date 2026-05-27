from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow


class _Button:
    def __init__(self):
        self.text = ""
        self.enabled = None

    def setText(self, text: str):
        self.text = text

    def setEnabled(self, enabled: bool):
        self.enabled = enabled


class _Status:
    def __init__(self):
        self.text = ""

    def setText(self, text: str):
        self.text = text


def _state(dirty: bool, playing: bool = False) -> SimpleNamespace:
    calls: list[tuple] = []
    window = SimpleNamespace(
        _loading_data=False,
        df=pd.DataFrame({"close": [1.0]}),
        market_dirty=dirty,
        playing=playing,
        replay_controller=SimpleNamespace(playing=playing),
        btnLoadPlay=_Button(),
        status=_Status(),
        load_data=lambda *args, **kwargs: calls.append(("load", args, kwargs)),
        toggle_play=lambda: calls.append(("play",)),
        _is_market_params_dirty=lambda: dirty,
        _update_header=lambda: calls.append(("header",)),
        tr=lambda key: {
            "loading": "加载中...",
            "load_klines": "加载K线",
            "reload_klines": "重新加载K线",
            "pause": "暂停",
            "play": "播放",
            "market_params_changed": "行情参数已变更，点击重新加载K线。",
        }.get(key, key),
        _calls=calls,
    )
    window._update_load_play_button = lambda: MainWindow._update_load_play_button(window)
    window._show_market_dirty_feedback = lambda: MainWindow._show_market_dirty_feedback(window)
    return window


def test_loaded_clean_data_toggles_play():
    window = _state(False)

    MainWindow.load_or_toggle_play(window)

    assert window._calls == [("play",)]


def test_loaded_dirty_data_reloads_instead_of_playing_old_frame():
    window = _state(True)

    MainWindow.load_or_toggle_play(window)

    assert window._calls == [("load", (), {"restore": False, "use_cache": True})]


def test_market_parameter_change_stops_playback_and_requests_reload_feedback():
    window = _state(True, playing=True)

    MainWindow.on_market_params_changed(window)

    assert window.playing is False
    assert window.replay_controller.playing is False
    assert window.market_dirty is True
    assert window.status.text == "行情参数已变更，点击重新加载K线。"
    assert window.btnLoadPlay.text == "重新加载K线"


def test_dirty_button_state_takes_priority_over_playing():
    window = _state(True, playing=True)

    MainWindow._update_load_play_button(window)

    assert window.btnLoadPlay.text == "重新加载K线"


def test_direct_play_action_cannot_resume_dirty_market_data():
    calls: list[str] = []
    window = SimpleNamespace(
        df=pd.DataFrame({"close": [1.0]}),
        cursor=0,
        playing=False,
        follow_latest=False,
        _accum=0.0,
        _last_tick=SimpleNamespace(restart=lambda: None),
        _render_dirty=False,
        replay_controller=SimpleNamespace(
            load_state=lambda *_args: calls.append("load_state"),
            toggle_play=lambda _length: calls.append("toggle_play") or True,
        ),
        _is_market_params_dirty=lambda: True,
        on_market_params_changed=lambda: calls.append("dirty_feedback"),
        _log=lambda _message: None,
        _update_load_play_button=lambda: None,
        _render=lambda force=False: None,
    )

    MainWindow.toggle_play(window)

    assert calls == ["dirty_feedback"]
