from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from project_paths import APP_DIR, REPO_ROOT

ROOT = REPO_ROOT


def test_lazy_import_helper_imports_requested_module():
    from lazy_imports import deferred_module_names, get_optional_module, lazy_import

    assert lazy_import("json") is json
    assert get_optional_module("json") is json
    assert "api_server" in deferred_module_names()


def test_main_app_import_does_not_load_export_analysis_chain():
    pytest.importorskip("PySide6")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR)
    env["QT_QPA_PLATFORM"] = "offscreen"
    probe = (
        "import json,sys; import main_app; "
        "print(json.dumps({name: name in sys.modules for name in "
        "['exporter','analysis_workspace','backtest_panel','strategy_consistency_panel',"
        "'controllers.research_backfill_controller','workers.research_backfill_worker',"
        "'requests']}))"
    )
    run = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    loaded = json.loads(run.stdout.strip().splitlines()[-1])
    assert loaded == {
        "exporter": False,
        "analysis_workspace": False,
        "backtest_panel": False,
        "strategy_consistency_panel": False,
        "controllers.research_backfill_controller": False,
        "workers.research_backfill_worker": False,
        "requests": False,
    }


def test_storage_import_does_not_eagerly_load_dataframe_or_statistics_stacks():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR)
    probe = (
        "import json,sys; import storage; "
        "print(json.dumps({name: name in sys.modules for name in "
        "['pandas','scipy','scipy.optimize']}))"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(run.stdout.strip().splitlines()[-1]) == {
        "pandas": False,
        "scipy": False,
        "scipy.optimize": False,
    }


def test_analysis_shell_import_does_not_load_behavior_training_dependencies():
    pytest.importorskip("PySide6")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR)
    env["QT_QPA_PLATFORM"] = "offscreen"
    probe = (
        "import json,sys; import analysis_workspace; "
        "print(json.dumps({name: name in sys.modules for name in "
        "['scipy','sklearn','sklearn.linear_model']}))"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(run.stdout.strip().splitlines()[-1]) == {
        "scipy": False,
        "sklearn": False,
        "sklearn.linear_model": False,
    }


def test_opening_analysis_shell_defers_legacy_backtest_panels(tmp_path):
    pytest.importorskip("PySide6")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QRC_RUNTIME_ROOT"] = str(tmp_path / "runtime")
    probe = (
        "import json,os,sys; "
        "from PySide6 import QtWidgets; import main_app; "
        "app=QtWidgets.QApplication([]); "
        "main_app.MainWindow.request_premium_sample=lambda self: None; "
        "window=main_app.MainWindow(); window.open_analysis_workspace(); "
        "app.processEvents(); "
        "before={'backtest_module':'backtest_panel' in sys.modules,"
        "'consistency_module':'strategy_consistency_panel' in sys.modules,"
        "'backtest_panel':window.backtestPanel is not None,"
        "'consistency_panel':window.strategyConsistencyPanel is not None}; "
        "analysis=window._analysis_workspace; "
        "analysis.tabs.setCurrentWidget(analysis.consistencyTab); app.processEvents(); "
        "before['consistency_loaded_on_demand']='strategy_consistency_panel' in sys.modules and window.strategyConsistencyPanel is not None; "
        "print(json.dumps(before),flush=True); "
        "os._exit(0)"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout.strip().splitlines()[-1]) == {
        "backtest_module": False,
        "consistency_module": False,
        "backtest_panel": False,
        "consistency_panel": False,
        "consistency_loaded_on_demand": True,
    }
