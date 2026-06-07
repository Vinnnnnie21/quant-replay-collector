from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from presenters.status_presenter import (
    refresh_premium_plot,
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
            "reload_klines": "重新加载K线",
            "trade_disabled_due_to_display_interval": "样本周期不一致",
        }.get(key, key),
    )

    update_load_play_button(window)
    update_trade_buttons_enabled(window)

    assert load_button.text == "重新加载K线"
    assert all(button.enabled is False for button in trade_buttons)
    assert all(button.tooltip == "样本周期不一致" for button in trade_buttons)


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
