from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import time

import pytest

pytest.importorskip("PySide6")

from ui_watchdog import UiFreezeWatchdog


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "quant_collector_app"


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)

    def error(self, message, *args):
        self.errors.append(message % args if args else message)


def test_watchdog_imports_in_package_mode_without_app_dir_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    probe = (
        "import importlib, pathlib, sys; "
        "import quant_collector_app; "
        f"app_dir = {str(APP_DIR)!r}; "
        "sys.path = [p for p in sys.path if p != app_dir]; "
        "assert app_dir not in sys.path; "
        "importlib.import_module('quant_collector_app.ui_watchdog')"
    )

    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert run.returncode == 0, run.stderr

    def exception(self, message, *args):
        self.errors.append(message % args if args else message)


def test_watchdog_normal_heartbeat_does_not_write_freeze_warning(tmp_path):
    logger = _Logger()
    watchdog = UiFreezeWatchdog(
        log_dir=tmp_path,
        logger=logger,
        warning_after_seconds=2.0,
        dump_after_seconds=5.0,
        start=False,
    )
    watchdog.record_heartbeat(now=100.0)

    watchdog.check(now=101.0)

    assert logger.warnings == []
    assert list(Path(tmp_path).glob("freeze_dump_*.log")) == []


def test_watchdog_delayed_heartbeat_writes_warning_and_dump(tmp_path):
    logger = _Logger()
    watchdog = UiFreezeWatchdog(
        log_dir=tmp_path,
        logger=logger,
        warning_after_seconds=2.0,
        dump_after_seconds=5.0,
        start=False,
    )
    watchdog.record_heartbeat(now=100.0)

    watchdog.check(now=103.0)
    watchdog.check(now=106.0)

    assert any("UI heartbeat delayed" in message for message in logger.warnings)
    dumps = list(Path(tmp_path).glob("freeze_dump_*.log"))
    assert len(dumps) == 1
    assert "thread" in dumps[0].read_text(encoding="utf-8", errors="ignore").lower()


def test_watchdog_background_thread_detects_stale_heartbeat(tmp_path):
    logger = _Logger()
    watchdog = UiFreezeWatchdog(
        log_dir=tmp_path,
        logger=logger,
        warning_after_seconds=0.01,
        dump_after_seconds=0.02,
        interval_ms=1000,
        background_interval_seconds=0.005,
        start=False,
        start_background=True,
    )
    try:
        time.sleep(0.08)
    finally:
        watchdog.shutdown()

    assert any("UI heartbeat delayed" in message for message in logger.warnings)
    assert list(Path(tmp_path).glob("freeze_dump_*.log"))
