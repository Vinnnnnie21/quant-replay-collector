from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from main_app import MainWindow
from state import AppState


class _Button:
    def __init__(self) -> None:
        self.enabled = True

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class _Status:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class _ExportTaskController:
    def __init__(self) -> None:
        self.is_running = False
        self.calls: list[tuple[str, object]] = []

    def start(self, db_path: str, request) -> bool:
        self.calls.append((db_path, request))
        return True


def test_main_window_start_export_task_delegates_thread_lifecycle_to_controller(tmp_path):
    controller = _ExportTaskController()
    window = SimpleNamespace(
        session_id="sess_1",
        app_state=AppState(),
        export_task_controller=controller,
        current_language="zh_CN",
        storage=SimpleNamespace(db_path="test.db"),
        btnExport=_Button(),
        status=_Status(),
        _export_success_callback=None,
    )

    started = MainWindow.start_export_task(
        window,
        tmp_path / "exports",
        language="en_US",
        selected_label="fwd_ret_5_side_adj",
    )

    assert started is True
    assert window.app_state.export.running is True
    assert window.btnExport.enabled is False
    assert window.status.text == "Exporting session data..."
    assert controller.calls[0][0] == "test.db"
    request = controller.calls[0][1]
    assert request.target == Path(tmp_path / "exports")
    assert request.session_id == "sess_1"
    assert request.language == "en_US"
    assert request.selected_label == "fwd_ret_5_side_adj"


def test_main_window_finish_export_task_only_restores_ui_state():
    app_state = AppState()
    app_state.export.running = True
    window = SimpleNamespace(
        app_state=app_state,
        _export_success_callback=object(),
        btnExport=_Button(),
    )
    window.btnExport.enabled = False

    MainWindow._finish_export_task(window)

    assert window.app_state.export.running is False
    assert window._export_success_callback is None
    assert window.btnExport.enabled is True
