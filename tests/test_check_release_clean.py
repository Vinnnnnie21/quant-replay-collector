from __future__ import annotations

from scripts.check_release_clean import inspect_release


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
