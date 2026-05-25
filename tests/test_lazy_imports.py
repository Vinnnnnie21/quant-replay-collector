from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"


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
        "['exporter','analysis_workspace','backtest_panel','strategy_consistency_panel']}))"
    )
    run = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    loaded = json.loads(run.stdout.strip().splitlines()[-1])
    assert loaded == {
        "exporter": False,
        "analysis_workspace": False,
        "backtest_panel": False,
        "strategy_consistency_panel": False,
    }
