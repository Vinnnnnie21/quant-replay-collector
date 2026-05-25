from __future__ import annotations

from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pandas")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow, QtWidgets


class _Storage:
    def __init__(self):
        self.clear_calls = 0

    def clear_manual_research_records(self):
        self.clear_calls += 1
        return {}


def _window_stub():
    return SimpleNamespace(
        _loading_data=False,
        app_state=SimpleNamespace(export=SimpleNamespace(running=False)),
        storage=_Storage(),
        tr=lambda key: {
            "clear_trade_records_title": "清空全部交易样本",
            "clear_trade_records_warning": "warning",
            "clear_trade_records_phrase_prompt": "prompt",
            "clear_trade_records_phrase": "清空交易数据",
            "clear_trade_records_phrase_mismatch": "mismatch",
        }.get(key, key),
    )


def test_clear_trade_records_cancelled_at_warning_does_not_delete(monkeypatch):
    window = _window_stub()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Cancel,
    )

    MainWindow.confirm_clear_trade_records(window)

    assert window.storage.clear_calls == 0


def test_clear_trade_records_requires_confirmation_phrase(monkeypatch):
    window = _window_stub()
    responses = iter([QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.Ok])
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: next(responses),
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("wrong", True),
    )

    MainWindow.confirm_clear_trade_records(window)

    assert window.storage.clear_calls == 0
