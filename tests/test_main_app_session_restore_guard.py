from __future__ import annotations

from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow


def test_execution_setting_signals_do_not_save_during_session_restore():
    calls = []
    window = SimpleNamespace(
        _restoring_session_settings=True,
        persist_session_state=lambda: calls.append("persist"),
        _sync_equity_curve=lambda: calls.append("equity"),
        _refresh_tables=lambda: calls.append("tables"),
        _log=lambda message: calls.append(message),
    )

    MainWindow.on_execution_settings_changed(window)

    assert calls == []
