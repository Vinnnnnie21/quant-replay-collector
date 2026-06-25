from __future__ import annotations

from pathlib import Path

import self_check
from storage import StorageManager


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