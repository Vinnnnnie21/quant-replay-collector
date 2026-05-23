from __future__ import annotations

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
