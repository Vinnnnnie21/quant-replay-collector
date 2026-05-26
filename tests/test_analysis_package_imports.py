from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"


@pytest.mark.parametrize(
    "module_name",
    [
        "quant_collector_app.time_series_analysis.report",
        "quant_collector_app.strategy_consistency.consistency",
        "quant_collector_app.analysis.feature_engineering",
        "quant_collector_app.analysis.llm_context",
    ],
)
def test_pure_analysis_modules_import_without_app_dir_pythonpath(module_name):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    probe = (
        "import importlib, sys; "
        f"assert {str(APP_DIR)!r} not in sys.path; "
        f"importlib.import_module({module_name!r})"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr
