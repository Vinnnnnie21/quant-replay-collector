from __future__ import annotations

from pathlib import Path

import self_check
from storage import StorageManager


def test_core_self_check_fixture_passes_the_research_quality_gate():
    result = self_check._run_core_check()

    assert result["status"] == "ok"


def test_core_self_check_does_not_open_the_application_database_by_default(monkeypatch):
    integrity_calls: list[object] = []
    monkeypatch.setattr(
        self_check,
        "_run_core_check",
        lambda: {"status": "ok", "warnings": []},
    )
    monkeypatch.setattr(
        self_check,
        "_database_integrity_probe",
        lambda **kwargs: integrity_calls.append(kwargs),
    )

    result = self_check.run_self_check("core")

    assert integrity_calls == []
    assert result["database_integrity"] == {
        "status": "skipped",
        "reason": "database_not_requested",
    }


def test_self_check_reports_database_integrity(monkeypatch, tmp_path):
    storage = StorageManager(tmp_path / "healthy.db")
    monkeypatch.setattr(self_check, "_run_core_check", lambda: {"status": "ok", "warnings": []})

    result = self_check.run_self_check("core", db_path=storage.db_path)

    assert result["status"] == "ok"
    assert result["database_integrity"]["status"] == "ok"
    assert result["database_integrity"]["integrity_check"] == "ok"
    assert result["database_integrity"]["schema_version"] == StorageManager.SCHEMA_VERSION
    assert result["database_integrity"]["migration_status"] == "current"


def test_self_check_missing_database_warns_without_crashing(monkeypatch, tmp_path):
    monkeypatch.setattr(self_check, "_run_core_check", lambda: {"status": "ok", "warnings": []})

    result = self_check.run_self_check("core", db_path=tmp_path / "missing.db")

    assert result["status"] == "ok"
    assert result["database_integrity"]["status"] == "warning"
    assert result["database_integrity"]["database_exists"] is False
    assert "does not exist" in result["database_integrity"]["warning"]


def test_self_check_can_create_database_backup(monkeypatch, tmp_path):
    storage = StorageManager(tmp_path / "healthy.db")
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(self_check, "_run_core_check", lambda: {"status": "ok", "warnings": []})

    result = self_check.run_self_check(
        "core",
        db_path=storage.db_path,
        backup_dir=backup_dir,
        backup_database_requested=True,
    )

    backup = result["database_integrity"]["backup"]
    assert result["status"] == "ok"
    assert backup["status"] == "ok"
    assert Path(backup["backup_path"]).exists()
    assert Path(backup["annotations_jsonl_path"]).exists()
    assert backup["annotations_row_count"] == 0
