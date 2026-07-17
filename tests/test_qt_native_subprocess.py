from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.performance
def test_qt_graphics_and_worker_lifecycle_stress_subprocess_exits_cleanly(tmp_path):
    """Capture native failures without taking down the release-gate process."""

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["QRC_QT_STRESS_TRACE"] = "1"
    stdout_path = tmp_path / "child-stdout.txt"
    stderr_path = tmp_path / "child-stderr.txt"
    run = None
    timeout_error = None
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_file:
        try:
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-m",
                    "qt_native_inner",
                    "tests/test_qt_layout_stress.py",
                    "-q",
                    "-s",
                    "--basetemp",
                    str(tmp_path / "child-pytest"),
                ],
                cwd=root,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            timeout_error = exc

    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    trace_lines = [line for line in stderr.splitlines() if "qt_stress" in line]
    trace_tail = "\n".join(trace_lines[-20:])
    fatal_index = stderr.rfind("Windows fatal exception")
    fatal_tail = (
        "\n".join(stderr[fatal_index:].splitlines()[:35])
        if fatal_index >= 0
        else ""
    )
    stdout_tail = "\n".join(stdout.splitlines()[-20:])
    stderr_tail = "\n".join(stderr.splitlines()[-20:])
    diagnostic = (
        f"last lifecycle trace lines:\n{trace_tail}\n"
        f"fatal stack:\n{fatal_tail}\n"
        f"last stdout lines:\n{stdout_tail}\nlast stderr lines:\n{stderr_tail}"
    )
    assert timeout_error is None, f"{timeout_error}\n{diagnostic}"
    assert run is not None
    assert run.returncode == 0, diagnostic
    assert "Windows fatal exception" not in stderr, diagnostic
    assert "access violation" not in stderr.lower(), diagnostic
    assert "QThread: Destroyed while thread" not in stderr, diagnostic
