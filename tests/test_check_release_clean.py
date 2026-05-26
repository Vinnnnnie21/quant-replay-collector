from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_release_clean import contamination_reason, inspect_release


def test_clean_release_directory_passes(tmp_path):
    (tmp_path / "quant_collector_app").mkdir()
    (tmp_path / "quant_collector_app" / "main.py").write_text("pass\n", encoding="utf-8")
    assert inspect_release(tmp_path) == []


def test_release_checker_rejects_virtual_environment_database_and_log(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "private.py").write_text("", encoding="utf-8")
    (tmp_path / "quant_collector_app" / "data").mkdir(parents=True)
    (tmp_path / "quant_collector_app" / "data" / "local.db").write_bytes(b"db")
    (tmp_path / "quant_collector_app" / "logs").mkdir(parents=True)
    (tmp_path / "quant_collector_app" / "logs" / "app.log").write_text("log", encoding="utf-8")

    findings = inspect_release(tmp_path)
    reasons = "\n".join(f"{path}: {reason}" for path, reason in findings)
    assert ".venv" in reasons
    assert "local SQLite database" in reasons
    assert "runtime log file" in reasons


@pytest.mark.parametrize(
    "relative_path",
    [
        ".codex_pytest_tmp/run/output.txt",
        "nested/__pycache__/module.py",
        "nested/module.pyc",
        "nested/module.pyo",
        "archives/release.zip",
        "nested/cache/bars.csv",
        "data/cache/bars.csv",
        "data/exports/session.csv",
        "data/research.sqlite",
        "logs/.gitkeep",
    ],
)
def test_contamination_reason_rejects_required_local_artifacts(relative_path):
    assert contamination_reason(Path(relative_path)) is not None


def test_release_checker_finds_new_pollution_rules_in_directory_tree(tmp_path):
    paths = [
        ".codex_pytest_tmp/result.txt",
        "source/cache/bars.csv",
        "source/result.sqlite",
        "source/package.zip",
        "source/compiled.pyo",
        "source/logs/.gitkeep",
        "source/data/exports/session.csv",
    ]
    for relative_path in paths:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("local\n", encoding="utf-8")

    findings = {path for path, _reason in inspect_release(tmp_path)}
    assert set(paths).issubset(findings)
