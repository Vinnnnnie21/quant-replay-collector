from __future__ import annotations

from pathlib import Path

from tests.conftest import _artifact_run_root


def test_pytest_collection_excludes_runtime_and_release_directories():
    config = Path("pytest.ini")
    assert config.exists()
    text = config.read_text(encoding="utf-8")

    for value in (
        "dist",
        "build",
        ".pytest_cache",
        "__pycache__",
        "performance_reports",
        "pytest_manual_full_*",
        "Backup",
        ".codex-backups",
        ".pytest_tmp*",
        ".test-artifacts",
        "quant_collector_app/data",
        "quant_collector_app/logs",
    ):
        assert value in text


def test_pytest_uses_repeat_safe_process_scoped_temp_directories():
    text = Path("pytest.ini").read_text(encoding="utf-8")

    assert "--basetemp=" not in text
    assert "-p no:cacheprovider" in text
    run_root = _artifact_run_root(pid=123, token="abc")
    assert run_root == Path(".test-artifacts/pytest-tmp-run-123-abc")


def test_ci_uses_an_existing_runner_temp_root_for_pytest():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "$env:RUNNER_TEMP" in workflow
    assert "--basetemp" in workflow
