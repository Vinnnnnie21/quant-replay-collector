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


def test_pytest_writes_default_cache_and_temp_files_under_one_directory():
    text = Path("pytest.ini").read_text(encoding="utf-8")

    assert "--basetemp=.test-artifacts/pytest-tmp" in text
    assert "cache_dir = .test-artifacts/pytest-cache" in text
