from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from app_i18n import tr
from main_app import MainWindow


def test_reset_view_only_resets_zoom_without_clearing_market_or_trade_data():
    calls: list[tuple] = []
    frame = pd.DataFrame({"close": range(20)})
    trades = [{"trade_id": "t1"}]
    events = [{"event_id": "e1"}]
    window = SimpleNamespace(
        df=frame,
        trades=trades,
        events=events,
        window_bars=140,
        cursor=10,
        pad_right=8,
        manual_xrange=(2.0, 5.0),
        user_view_lock=True,
        _set_xrange=lambda x0, x1, force=False: calls.append(("range", x0, x1, force)),
        _render=lambda force=False: calls.append(("render", force)),
        _log=lambda message: calls.append(("log", message)),
        tr=lambda key: {"reset_zoom_done": "已重置缩放范围。"}.get(key, key),
    )

    MainWindow.reset_view(window)

    assert window.df is frame
    assert window.trades is trades
    assert window.events is events
    assert window.user_view_lock is False
    assert window.manual_xrange != (2.0, 5.0)
    assert ("log", "已重置缩放范围。") in calls


def test_reset_view_language_makes_non_destructive_semantics_explicit():
    assert tr("reset_view", "zh_CN") == "重置缩放"
    assert tr("reset_view", "en_US") == "Reset Zoom"
    assert "不清空K线" in tr("reset_view_hint", "zh_CN")
    assert "does not clear Kline" in tr("reset_view_hint", "en_US")
