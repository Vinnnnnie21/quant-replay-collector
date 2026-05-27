from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow


class _Button:
    def __init__(self):
        self.enabled = None
        self.tooltip = ""

    def setEnabled(self, enabled: bool):
        self.enabled = enabled

    def setToolTip(self, tooltip: str):
        self.tooltip = tooltip


class _Scatter:
    def __init__(self):
        self.pos = None

    def setData(self, pos):
        self.pos = pos


def _sample_window(display_interval: str, with_samples: bool = True) -> SimpleNamespace:
    records = [{"interval": "1m"}] if with_samples else []
    window = SimpleNamespace(
        _display_market_key=("BTCUSDT", display_interval, "2026-05-27", "2026-05-27"),
        _sample_market_key=("BTCUSDT", "1m", "2026-05-27", "2026-05-27"),
        trades=list(records),
        events=list(records),
        intervalBox=SimpleNamespace(currentText=lambda: display_interval),
        btnOpenLong=_Button(),
        btnOpenShort=_Button(),
        btnCloseLong=_Button(),
        btnCloseShort=_Button(),
        tr=lambda key: "当前显示周期与交易样本周期不一致。为避免污染样本，请回到样本周期或新建当前周期会话。",
    )
    window._display_interval = lambda: MainWindow._display_interval(window)
    window._sample_interval = lambda: MainWindow._sample_interval(window)
    window._is_display_interval_same_as_sample_interval = lambda: MainWindow._is_display_interval_same_as_sample_interval(window)
    window._is_trade_recording_allowed = lambda: MainWindow._is_trade_recording_allowed(window)
    return window


def test_existing_one_minute_samples_disable_trade_buttons_on_five_minute_display():
    window = _sample_window("5m")

    MainWindow._update_trade_buttons_enabled(window)

    assert window.btnOpenLong.enabled is False
    assert window.btnCloseShort.enabled is False
    assert "显示周期" in window.btnOpenLong.tooltip


def test_same_display_and_sample_interval_keeps_trade_buttons_enabled():
    window = _sample_window("1m")

    MainWindow._update_trade_buttons_enabled(window)

    assert window.btnOpenLong.enabled is True
    assert window.btnCloseLong.enabled is True


def test_empty_new_session_is_not_blocked_when_display_interval_changes():
    window = _sample_window("5m", with_samples=False)

    MainWindow._update_trade_buttons_enabled(window)

    assert window.btnOpenLong.enabled is True


def test_open_and_close_requests_are_guarded_when_display_differs_from_sample_interval():
    calls: list[str] = []
    window = SimpleNamespace(
        df=pd.DataFrame({"bar_index": [0]}),
        _is_trade_recording_allowed=lambda: False,
        _warn_trade_interval_mismatch=lambda: calls.append("warning"),
    )

    MainWindow.request_open_trade(window, "LONG")
    MainWindow.request_close_trade(window, "LONG")

    assert calls == ["warning", "warning"]


def test_event_markers_from_one_minute_samples_are_not_drawn_on_five_minute_chart():
    scatter = [_Scatter() for _ in range(4)]
    window = SimpleNamespace(
        cursor=3,
        df=pd.DataFrame({"high": [11, 12, 13, 14], "low": [9, 10, 11, 12]}),
        events=[{"bar_index": 2, "interval": "1m", "event_type": "OPEN", "side": "LONG"}],
        _display_market_key=("BTCUSDT", "5m", "2026-05-27", "2026-05-27"),
        intervalBox=SimpleNamespace(currentText=lambda: "5m"),
        scatter_open_long=scatter[0],
        scatter_open_short=scatter[1],
        scatter_close_long=scatter[2],
        scatter_close_short=scatter[3],
    )
    window._display_interval = lambda: MainWindow._display_interval(window)
    window._sample_interval = lambda: MainWindow._sample_interval(window)

    MainWindow._sync_markers(window)

    assert isinstance(window.scatter_open_long.pos, np.ndarray)
    assert window.scatter_open_long.pos.size == 0


def test_session_persistence_keeps_sample_interval_cursor_while_display_is_different():
    written: list[dict] = []
    window = _sample_window("5m")
    window.session_id = "sess_1m"
    window.cursor = 7
    window.follow_latest = False
    window._sample_cursor_bar_index = 37
    window.storage = SimpleNamespace(
        get_latest_session=lambda: {"session_id": "sess_1m", "last_opened_at": "old"},
        upsert_session=lambda row: written.append(row),
    )
    window.current_speed = lambda: 1.0
    window.initialEquitySpin = SimpleNamespace(value=lambda: 10000.0)
    window.tradeNotionalSpin = SimpleNamespace(value=lambda: 1000.0)
    window.feeBpsSpin = SimpleNamespace(value=lambda: 4.0)
    window.slippageBpsSpin = SimpleNamespace(value=lambda: 1.0)
    window._fill_mode_value = lambda: "close"

    MainWindow.persist_session_state(window)

    assert written[0]["interval"] == "1m"
    assert written[0]["cursor_bar_index"] == 37
