from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from quant_collector_app.database_backup import (
    backup_database,
    export_annotations_jsonl,
    list_backups,
    run_database_integrity_check,
    verify_backup,
)
from research.entry_annotations import DecisionTiming, EntryAnnotation, HumanDecision
from storage import StorageManager


def _entry_annotation() -> dict:
    return EntryAnnotation(
        annotation_id="ann_backup_1",
        session_id="session_backup",
        symbol="BTCUSDT",
        interval="1m",
        bar_index=12,
        bar_time="2026-01-01T00:12:00Z",
        human_decision=HumanDecision.ENTRY,
        confidence=5,
        reason_tags=["long_lower_shadow"],
        note="backup test",
        decision_timing=DecisionTiming.CURRENT_BAR_CLOSE,
        created_at="2026-01-01T00:13:00Z",
        updated_at="2026-01-01T00:13:00Z",
        app_version="test",
    ).to_dict()


def test_backup_database_creates_named_backup_and_verify_passes(tmp_path):
    storage = StorageManager(tmp_path / "source.db")
    storage.upsert_session({"session_id": "session_backup", "symbol": "BTCUSDT", "interval": "1m"})

    result = backup_database(storage.db_path, tmp_path / "backups")

    backup_path = result["backup_path"]
    assert backup_path.exists()
    assert re.match(r"quant_replay_\d{8}_\d{6}\.db", backup_path.name)
    assert list_backups(tmp_path / "backups") == [backup_path]
    verified = verify_backup(backup_path)
    assert verified["status"] == "ok"
    assert verified["integrity_check"] == "ok"
    assert verified["schema_version"] == StorageManager.SCHEMA_VERSION


def test_verify_backup_reports_corrupt_file_clearly(tmp_path):
    corrupt = tmp_path / "quant_replay_20260101_000000.db"
    corrupt.write_bytes(b"not a sqlite database")

    with pytest.raises(ValueError, match="SQLite backup verification failed"):
        verify_backup(corrupt)


def test_integrity_check_reports_missing_required_tables(tmp_path):
    incomplete = tmp_path / "incomplete.db"
    with sqlite3.connect(incomplete) as conn:
        conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE trades (trade_id TEXT PRIMARY KEY)")
        conn.execute(f"PRAGMA user_version={StorageManager.SCHEMA_VERSION}")

    report = run_database_integrity_check(incomplete, expected_schema_version=StorageManager.SCHEMA_VERSION)

    assert report["status"] == "warning"
    assert report["migration_status"] == "incomplete_schema"
    assert "entry_annotations" in report["missing_required_tables"]
    assert "entry_annotation_history" in report["missing_required_tables"]


def test_annotations_jsonl_export_preserves_rows(tmp_path):
    storage = StorageManager(tmp_path / "annotations.db")
    storage.save_entry_annotation(_entry_annotation())
    updated = _entry_annotation()
    updated["note"] = "updated backup test"
    updated["updated_at"] = "2026-01-01T00:14:00Z"
    storage.save_entry_annotation(updated)

    result = export_annotations_jsonl(storage.db_path, tmp_path / "backups")

    assert result["row_count"] == 2
    rows = [json.loads(line) for line in result["jsonl_path"].read_text(encoding="utf-8").splitlines()]
    current = next(row for row in rows if row["_table"] == "entry_annotations")
    history = next(row for row in rows if row["_table"] == "entry_annotation_history")
    assert current["annotation_id"] == "ann_backup_1"
    assert current["human_decision"] == "ENTRY"
    assert current["reason_tags"] == ["long_lower_shadow"]
    assert current["note"] == "updated backup test"
    assert history["operation"] == "UPDATE"
    assert history["snapshot"]["note"] == "backup test"


def test_gitignore_ignores_default_backups_directory():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    ignored = {line.strip() for line in gitignore.splitlines()}
    assert "backups/" in ignored
    assert "quant_collector_app/backups/" in ignored