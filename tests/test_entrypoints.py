from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"


def test_package_exposes_version():
    package = importlib.import_module("quant_collector_app")
    from quant_collector_app.app_config import APP_VERSION
    assert package.__version__ == APP_VERSION


def test_root_launcher_is_import_safe():
    module = importlib.import_module("run_app")
    assert callable(module.main)


def test_package_mode_core_modules_are_import_safe():
    assert importlib.import_module("quant_collector_app.storage") is not None
    assert importlib.import_module("quant_collector_app.self_check") is not None


def test_leaf_modules_do_not_require_app_dir_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    modules = [
        "quant_collector_app.app_logger",
        "quant_collector_app.app_settings",
        "quant_collector_app.startup",
        "quant_collector_app.services.market_data_service",
        "quant_collector_app.controllers",
        "quant_collector_app.controllers.backtest_controller",
        "quant_collector_app.presenters.backtest_presenter",
        "quant_collector_app.services.backtest_service",
        "quant_collector_app.render.chart_render_plan",
        "quant_collector_app.multi_timeframe",
    ]
    probe = (
        "import builtins, importlib, pathlib, sys; "
        "original_import = builtins.__import__; "
        "builtins.__import__ = lambda name, *args, **kwargs: "
        "(_ for _ in ()).throw(ModuleNotFoundError(name)) "
        "if name.startswith(('PySide6', 'pyqtgraph')) "
        "else original_import(name, *args, **kwargs); "
        "import quant_collector_app; "
        f"app_dir = {str(APP_DIR)!r}; "
        "sys.path = [p for p in sys.path if p != app_dir]; "
        "assert app_dir not in sys.path; "
        f"[importlib.import_module(name) for name in {modules!r}]"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr


def test_qt_leaf_modules_import_when_pyside6_is_available():
    pytest.importorskip("PySide6")
    pytest.importorskip("pyqtgraph")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    modules = [
        "quant_collector_app.controllers.analysis_controller",
        "quant_collector_app.controllers.export_task_controller",
        "quant_collector_app.controllers.market_data_controller",
        "quant_collector_app.controllers.replay_ui_controller",
        "quant_collector_app.controllers.trade_action_controller",
        "quant_collector_app.controllers.trade_record_controller",
        "quant_collector_app.presenters.status_presenter",
        "quant_collector_app.render.chart_render_adapter",
        "quant_collector_app.views.main_window_connections",
        "quant_collector_app.views.main_window_layout",
        "quant_collector_app.views.main_window_presentation",
    ]
    probe = (
        "import importlib, pathlib, sys; "
        "import quant_collector_app; "
        f"app_dir = {str(APP_DIR)!r}; "
        "sys.path = [p for p in sys.path if p != app_dir]; "
        "assert app_dir not in sys.path; "
        f"[importlib.import_module(name) for name in {modules!r}]"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr
