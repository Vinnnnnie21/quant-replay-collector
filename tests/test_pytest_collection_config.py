from __future__ import annotations

from pathlib import Path


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


def test_pytest_keeps_cache_local_and_temp_files_outside_the_repo_by_default():
    text = Path("pytest.ini").read_text(encoding="utf-8")

    assert "--basetemp=" not in text
    assert "cache_dir = .test-artifacts/pytest-cache" in text


def test_ci_uses_an_existing_runner_temp_root_for_pytest():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "$env:RUNNER_TEMP" in workflow
    assert "--basetemp" in workflow
