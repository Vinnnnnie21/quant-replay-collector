from __future__ import annotations

import os

import pytest


def test_settings_and_analysis_workspace_importable():
    pytest.importorskip("PySide6")

    from analysis_workspace import AnalysisWorkspace
    from main_app import MainWindow
    from settings_dialog import SettingsDialog

    assert AnalysisWorkspace is not None
    assert SettingsDialog is not None
    assert hasattr(MainWindow, "apply_language")
    assert hasattr(MainWindow, "retranslate_ui")


def test_settings_dialog_exposes_and_saves_chart_render_backend(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    import settings_dialog
    from settings_dialog import SettingsDialog

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    host = QtWidgets.QWidget()
    host.current_language = "zh_CN"
    captured = {}
    monkeypatch.setattr(settings_dialog, "load_app_settings", lambda: {"language": "zh_CN", "render_backend": "hardware"})
    monkeypatch.setattr(settings_dialog, "save_app_settings", lambda settings: captured.update(settings))

    dialog = SettingsDialog(host)
    assert dialog.renderBackendBox.currentData() == "hardware"
    dialog.renderBackendBox.setCurrentIndex(dialog.renderBackendBox.findData("software"))
    dialog.accept()

    assert captured["render_backend"] == "software"
    dialog.close()
    host.close()
    app.processEvents()
