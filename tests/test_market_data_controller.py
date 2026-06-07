from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from types import SimpleNamespace

import pandas as pd

from controllers.market_data_controller import (
    accept_loaded_market_key,
    current_market_key,
    is_market_params_dirty,
)


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
