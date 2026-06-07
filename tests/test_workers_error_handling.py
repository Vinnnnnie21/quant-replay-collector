from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"


def test_workers_import_in_package_mode_without_app_dir_pythonpath():
    pytest.importorskip("PySide6")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    modules = [
        "quant_collector_app.workers.export_worker",
        "quant_collector_app.workers.analysis_refresh_worker",
        "quant_collector_app.workers.loader_worker",
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


def test_export_worker_exposes_lifecycle_signals():
    pytest.importorskip("PySide6")
    from workers.export_worker import ExportWorker

    assert all(hasattr(ExportWorker, name) for name in ("started", "progress", "finished", "failed", "cancelled"))


def test_loader_worker_exposes_lifecycle_signals():
    pytest.importorskip("PySide6")
    from market_data import LoaderWorker

    assert all(hasattr(LoaderWorker, name) for name in ("started", "progress", "finished", "failed", "cancelled"))
