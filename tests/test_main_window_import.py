from __future__ import annotations

import importlib

import pytest


def test_main_window_module_remains_importable():
    pytest.importorskip("PySide6")
    module = importlib.import_module("main_app")
    assert hasattr(module, "MainWindow")
    assert hasattr(module.MainWindow, "start_export_task")
    assert importlib.import_module("views.theme_dialog").ThemeDialog is not None
