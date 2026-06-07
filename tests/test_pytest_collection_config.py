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
        "quant_collector_app/data",
        "quant_collector_app/logs",
    ):
        assert value in text
