from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from presenters.status_presenter import (
    refresh_premium_plot,
    update_header,
    update_load_play_button,
    update_trade_buttons_enabled,
)


class _Button:
    def __init__(self) -> None:
        self.text = ""
        self.enabled = None
        self.tooltip = ""

    def setText(self, text: str) -> None:
        self.text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = tooltip

    def setChecked(self, checked: bool) -> None:
        self.checked = checked


class _Curve:
    def __init__(self) -> None:
        self.values = None

    def setData(self, x, y) -> None:
        self.values = (list(x), list(y))


def test_status_presenter_prioritizes_dirty_market_and_trade_guard():
    load_button = _Button()
    trade_buttons = [_Button() for _ in range(4)]
    window = SimpleNamespace(
        _loading_data=False,
        df=pd.DataFrame({"close": [1.0]}),
        market_dirty=True,
        playing=True,
        btnLoadPlay=load_button,
        btnOpenLong=trade_buttons[0],
        btnOpenShort=trade_buttons[1],
        btnCloseLong=trade_buttons[2],
        btnCloseShort=trade_buttons[3],
        _is_market_params_dirty=lambda: True,
        _is_trade_recording_allowed=lambda: False,
        _trade_transaction_active=False,
        tr=lambda key: {
            "play": "播放",
            "trade_disabled_due_to_display_interval": "样本周期不一致",
        }.get(key, key),
    )

    update_load_play_button(window)
    update_trade_buttons_enabled(window)

    assert load_button.text == "播放 (Space)"
    assert load_button.enabled is False
    assert all(button.enabled is False for button in trade_buttons)
    assert all(button.tooltip == "样本周期不一致" for button in trade_buttons)


def test_load_play_button_only_controls_replay_states():
    button = _Button()
    window = SimpleNamespace(
        _loading_data=False,
        df=pd.DataFrame(),
        playing=False,
        btnLoadPlay=button,
        _is_market_params_dirty=lambda: False,
        tr=lambda key: {"loading": "加载中...", "play": "播放", "pause": "暂停"}.get(key, key),
    )

    update_load_play_button(window)
    assert button.text == "播放 (Space)"
    assert button.enabled is False

    window.df = pd.DataFrame({"close": [1.0]})
    window._is_market_params_dirty = lambda: True
    update_load_play_button(window)
    assert button.text == "播放 (Space)"
    assert button.enabled is False

    window.market_dirty = False
    window._is_market_params_dirty = lambda: False
    update_load_play_button(window)
    assert button.text == "播放 (Space)"
    assert button.enabled is True

    window.playing = True
    update_load_play_button(window)
    assert button.text == "暂停 (Space)"
    assert button.enabled is True

    window._loading_data = True
    update_load_play_button(window)
    assert button.text == "加载中..."
    assert button.enabled is False


def test_status_presenter_refreshes_recent_premium_rows_only():
    rows = [
        {
            "sample_status": "OK",
            "buy_premium_pct": 1.0,
            "sell_premium_pct": 2.0,
            "avg_premium_pct": 1.5,
        }
    ]
    calls: list[int] = []
    window = SimpleNamespace(
        storage=SimpleNamespace(
            fetch_recent_premium_samples=lambda limit=240: calls.append(limit) or rows,
        ),
        premiumBuyCurve=_Curve(),
        premiumSellCurve=_Curve(),
        premiumAvgCurve=_Curve(),
        _log_slow_operation=lambda *_args: None,
    )

    refresh_premium_plot(window)

    assert calls == [240]
    assert window.premiumAvgCurve.values[1] == [1.5]


def test_status_presenter_updates_combined_header_text():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    del _app
    buttons = {key: _Button() for key in ("1m", "5m")}
    window = SimpleNamespace(
        df=pd.DataFrame(
            [
                {
                    "open_time_bjt": pd.Timestamp("2024-04-01 00:00:00+08:00"),
                    "open": 70446.20,
                    "high": 70584.20,
                    "low": 70387.80,
                    "close": 70534.80,
                    "volume": 12.0,
                    "bar_index": 0,
                }
            ]
        ),
        cursor=0,
        symbolBox=SimpleNamespace(currentText=lambda: "BTCUSDT"),
        intervalBox=SimpleNamespace(currentText=lambda: "5m"),
        _display_interval=lambda: "5m",
        _sample_interval=lambda: "5m",
        headerMainLabel=QtWidgets.QLabel(),
        headerSymbolValue=QtWidgets.QLabel(),
        headerIntervalValue=QtWidgets.QLabel(),
        headerSampleIntervalValue=QtWidgets.QLabel(),
        headerOhlcValue=QtWidgets.QLabel(),
        headerTimeValue=QtWidgets.QLabel(),
        headerDeltaValue=QtWidgets.QLabel(),
        headerPlayBadge=QtWidgets.QLabel(),
        headerViewBadge=QtWidgets.QLabel(),
        headerSessionBadge=QtWidgets.QLabel(),
        chartIntervalButtons=buttons,
        trades=[],
        playing=False,
        follow_latest=False,
        session_id="sess_1234567890",
        tr=lambda key: {"paused": "暂停", "free_view": "自由浏览", "session": "session"}.get(key, key),
        _set_widget_role=lambda widget, role: widget.setProperty("role", role),
        _update_load_play_button=lambda: None,
        _update_trade_buttons_enabled=lambda: None,
    )

    update_header(window)

    text = window.headerMainLabel.text()
    assert "BTCUSDT" in text
    assert "5m" in text
    assert "sample 5m" in text
    assert "2024-04-01 00:00" in text
    assert "O 70446.20" in text
    assert "C 70534.80" in text
    assert "+0.13%" in text
    assert buttons["5m"].enabled is None
