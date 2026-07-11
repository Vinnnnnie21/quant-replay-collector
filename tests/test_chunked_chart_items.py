from __future__ import annotations

import numpy as np
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from views.candlestick_item import CandlestickItem
from views.volume_item import VolumeItem


def _ohlc(count: int):
    x = np.arange(count, dtype=float)
    opening = 100.0 + x * 0.1
    close = opening + 0.05
    high = close + 0.2
    low = opening - 0.2
    return x, opening, high, low, close


def test_candlestick_item_rebuilds_only_the_last_chunk_for_one_new_bar():
    item = CandlestickItem()
    x, opening, high, low, close = _ohlc(97)
    item.set_data(x, opening, high, low, close)
    first = item.cache_stats()

    x, opening, high, low, close = _ohlc(98)
    item.set_data(x, opening, high, low, close)
    second = item.cache_stats()

    assert first == {"chunks": 4, "rebuilt_last_update": 4}
    assert second == {"chunks": 4, "rebuilt_last_update": 1}


def test_volume_item_rebuilds_only_the_last_chunk_for_one_new_bar():
    item = VolumeItem()
    x = np.arange(97, dtype=float)
    item.set_data(x, 100.0 + x, x % 2 == 0)
    first = item.cache_stats()

    x = np.arange(98, dtype=float)
    item.set_data(x, 100.0 + x, x % 2 == 0)
    second = item.cache_stats()

    assert first == {"chunks": 4, "rebuilt_last_update": 4}
    assert second == {"chunks": 4, "rebuilt_last_update": 1}
