from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from types import SimpleNamespace

import pandas as pd

from controllers.trade_action_controller import (
    current_bar,
    display_interval,
    is_display_interval_same_as_sample_interval,
)


def test_trade_action_controller_keeps_display_and_sample_interval_separate():
    window = SimpleNamespace(
        df=pd.DataFrame({"bar_index": [0, 1], "close": [1.0, 2.0]}),
        cursor=1,
        _display_market_key=("BTCUSDT", "5m", "2024-04-01", "2024-05-01"),
        _sample_market_key=("BTCUSDT", "1m", "2024-04-01", "2024-05-01"),
        trades=[{"interval": "1m"}],
        events=[],
        intervalBox=SimpleNamespace(currentText=lambda: "5m"),
    )
    window._display_interval = lambda: display_interval(window)
    window._sample_interval = lambda: "1m"

    assert int(current_bar(window)["bar_index"]) == 1
    assert display_interval(window) == "5m"
    assert is_display_interval_same_as_sample_interval(window) is False
