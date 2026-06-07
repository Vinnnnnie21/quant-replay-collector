from __future__ import annotations

from types import SimpleNamespace

import pytest


QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from controllers.trade_record_controller import confirm_clear_trade_records


def test_trade_record_clear_controller_rejects_busy_window(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda _parent, _title, message, *_args: warnings.append(message),
    )
    window = SimpleNamespace(
        _loading_data=True,
        app_state=SimpleNamespace(export=SimpleNamespace(running=False)),
        tr=lambda key: key,
    )

    confirm_clear_trade_records(window)

    assert warnings == ["clear_trade_records_busy"]
