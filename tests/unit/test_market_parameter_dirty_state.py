from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow


class _TextControl:
    def __init__(self, value: str):
        self.value = value

    def currentText(self) -> str:
        return self.value


class _DateValue:
    def __init__(self, value: str):
        self.value = value

    def toString(self, _format: str) -> str:
        return self.value


class _DateControl:
    def __init__(self, value: str):
        self.value = value

    def date(self) -> _DateValue:
        return _DateValue(self.value)


def _window_stub() -> SimpleNamespace:
    window = SimpleNamespace(
        symbolBox=_TextControl("BTCUSDT"),
        intervalBox=_TextControl("1m"),
        startDate=_DateControl("2026-01-01"),
        endDate=_DateControl("2026-01-02"),
        df=pd.DataFrame({"close": [1.0]}),
        _loaded_market_key=("BTCUSDT", "1m", "2026-01-01", "2026-01-02"),
    )
    window._current_market_key = lambda: MainWindow._current_market_key(window)
    window._is_market_params_dirty = lambda: MainWindow._is_market_params_dirty(window)
    return window


def test_loaded_key_equal_to_current_parameters_is_not_dirty():
    window = _window_stub()

    assert MainWindow._is_market_params_dirty(window) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("intervalBox", "5m"),
        ("symbolBox", "ETHUSDT"),
        ("startDate", "2025-12-31"),
        ("endDate", "2026-01-03"),
    ],
)
def test_changed_market_parameter_is_dirty(field: str, value: str):
    window = _window_stub()
    if field in {"symbolBox", "intervalBox"}:
        getattr(window, field).value = value
    else:
        getattr(window, field).value = value

    assert MainWindow._is_market_params_dirty(window) is True


def test_accept_loaded_market_key_marks_successful_loaded_frame_clean():
    window = _window_stub()
    window.intervalBox.value = "5m"
    window._pending_market_key = ("BTCUSDT", "5m", "2026-01-01", "2026-01-02")

    MainWindow._accept_loaded_market_key(window, pd.DataFrame({"close": [1.0]}))

    assert window._loaded_market_key == ("BTCUSDT", "5m", "2026-01-01", "2026-01-02")
    assert MainWindow._is_market_params_dirty(window) is False


def test_failed_load_does_not_overwrite_loaded_market_key():
    window = _window_stub()
    window.intervalBox.value = "5m"
    window._pending_market_key = ("BTCUSDT", "5m", "2026-01-01", "2026-01-02")

    MainWindow._accept_loaded_market_key(window, pd.DataFrame({"close": [1.0]}), successful=False)

    assert window._loaded_market_key == ("BTCUSDT", "1m", "2026-01-01", "2026-01-02")
