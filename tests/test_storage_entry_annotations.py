from __future__ import annotations

import csv
import json
import sqlite3

from exporter import Exporter
from research.entry_annotations import DecisionTiming, EntryAnnotation, HumanDecision
from storage import StorageManager


def _entry_annotation(
    annotation_id: str = "ann_1",
    *,
    decision: HumanDecision = HumanDecision.ENTRY,
    note: str = "first review",
    confidence: int = 5,
    observation_id: str = "obs_42",
    decision_bar_index: int = 42,
) -> dict:
    return EntryAnnotation(
        annotation_id=annotation_id,
        observation_id=observation_id,
        session_id="session_1",
        symbol="BTCUSDT",
        interval="5m",
        bar_index=decision_bar_index,
        bar_time="2026-01-01T00:00:00Z",
        human_decision=decision,
        confidence=confidence,
        reason_tags=["lower_shadow", "volume_spike"],
        note=note,
        decision_timing=DecisionTiming.CURRENT_BAR_CLOSE,
        created_at="2026-01-01T00:01:00Z",
        updated_at="2026-01-01T00:01:00Z",
        app_version="test",
    ).to_dict()


def test_new_database_creates_entry_annotations_table(tmp_path):
    storage = StorageManager(tmp_path / "entry_annotations.db")

    with storage.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(entry_annotations)").fetchall()
        }
        history_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(entry_annotation_history)").fetchall()
        }

    assert "entry_annotations" in tables
    assert {
        "annotation_id",
        "observation_id",
        "session_id",
        "symbol",
        "interval",
        "bar_index",
        "bar_time",
        "setup_bar_index",
        "decision_bar_index",
        "setup_bar_time",
        "decision_bar_time",
        "human_decision",
        "confidence",
        "reason_tags_json",
        "note",
        "decision_timing",
        "annotation_version",
        "created_at",
        "updated_at",
        "is_active",
        "superseded_by",
        "app_version",
    } <= columns
    assert "entry_annotations" in StorageManager.ALLOWED_TABLES
    assert {"observation_id", "previous_payload_json", "new_payload_json", "change_reason"} <= history_columns


def test_entry_annotation_can_be_saved_read_updated_and_deleted(tmp_path):
    storage = StorageManager(tmp_path / "entry_annotations_crud.db")

    storage.save_entry_annotation(_entry_annotation())
    stored = storage.list_entry_annotations(session_id="session_1")

    assert len(stored) == 1
    assert stored[0]["annotation_id"] == "ann_1"
    assert stored[0]["human_decision"] == "ENTRY"
    assert stored[0]["confidence"] == 5
    assert stored[0]["reason_tags"] == ["lower_shadow", "volume_spike"]
    assert stored[0]["setup_bar_index"] == 42
    assert stored[0]["decision_bar_index"] == 42
    assert stored[0]["bar_index"] == 42
    assert stored[0]["is_active"] == 1

    storage.save_entry_annotation(_entry_annotation(note="updated review", confidence=4))
    updated = storage.list_entry_annotations(annotation_id="ann_1")

    assert len(updated) == 1
    assert updated[0]["note"] == "updated review"
    assert updated[0]["confidence"] == 4
    assert storage.list_entry_annotation_history(annotation_id="ann_1")[0]["note"] == "first review"

    storage.delete_entry_annotation("ann_1")

    assert storage.list_entry_annotations(session_id="session_1") == []
    inactive = storage.list_entry_annotations(session_id="session_1", include_inactive=True)
    assert inactive[0]["is_active"] == 0

def test_same_observation_decision_change_updates_active_row_and_records_history(tmp_path):
    storage = StorageManager(tmp_path / "entry_annotation_update_decision.db")

    storage.save_entry_annotation(_entry_annotation("ann_entry", decision=HumanDecision.ENTRY, note="entry version"))
    storage.save_entry_annotation(
        _entry_annotation("ann_reject", decision=HumanDecision.REJECT, confidence=2, note="reject version")
    )

    active = storage.list_entry_annotations(session_id="session_1")
    history = storage.list_entry_annotation_history(annotation_id="ann_entry")

    assert len(active) == 1
    assert active[0]["annotation_id"] == "ann_entry"
    assert active[0]["human_decision"] == "REJECT"
    assert active[0]["confidence"] == 2
    assert active[0]["annotation_version"] == "entry_annotations_v2"
    assert len(history) == 1
    assert history[0]["human_decision"] == "ENTRY"
    assert history[0]["operation"] == "UPDATE"
    assert history[0]["new_payload"]["human_decision"] == "REJECT"


def test_v5_database_migrates_entry_annotations_table_idempotently(tmp_path):
    path = tmp_path / "legacy_v5.db"
    storage = StorageManager(path)
    storage.upsert_session({"session_id": "legacy_session", "symbol": "ETHUSDT", "interval": "1m"})
    with storage.connect() as conn:
        conn.execute("DROP TABLE entry_annotations")
        conn.execute("PRAGMA user_version=5")

    migrated = StorageManager(path)
    migrated_again = StorageManager(path)

    with migrated_again.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    assert "entry_annotations" in tables
    assert migrated.schema_version() == StorageManager.SCHEMA_VERSION
    assert migrated_again.fetch_table("sessions", "session_id=?", ("legacy_session",))[0]["symbol"] == "ETHUSDT"


def test_minimal_legacy_database_is_upgraded_without_losing_session(tmp_path):
    path = tmp_path / "legacy_minimal.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (session_id TEXT PRIMARY KEY);
            INSERT INTO sessions (session_id) VALUES ('old_session');
            """
        )

    storage = StorageManager(path)

    assert storage.schema_version() == StorageManager.SCHEMA_VERSION
    assert storage.fetch_table("sessions", "session_id=?", ("old_session",))[0]["session_id"] == "old_session"
    assert storage.fetch_table("entry_annotations") == []


def test_legacy_entry_annotations_table_is_upgraded_without_losing_rows(tmp_path):
    path = tmp_path / "legacy_entry_annotations_v6.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE entry_annotations (
                annotation_id TEXT PRIMARY KEY,
                session_id TEXT,
                symbol TEXT,
                interval TEXT,
                bar_index INTEGER,
                bar_time TEXT,
                human_decision TEXT,
                confidence INTEGER,
                reason_tags_json TEXT,
                note TEXT,
                decision_timing TEXT,
                created_at TEXT,
                app_version TEXT
            );
            INSERT INTO entry_annotations (
                annotation_id, session_id, symbol, interval, bar_index, bar_time,
                human_decision, confidence, reason_tags_json, note, decision_timing,
                created_at, app_version
            ) VALUES (
                'legacy_ann', 'legacy_session', 'BTCUSDT', '5m', 9,
                '2026-01-01T00:45:00Z', 'ENTRY', 4, '["lower_shadow"]',
                'legacy row', 'CURRENT_BAR_CLOSE', '2026-01-01T00:46:00Z', 'old'
            );
            PRAGMA user_version=6;
            """
        )

    storage = StorageManager(path)
    rows = storage.list_entry_annotations(session_id="legacy_session")

    assert rows[0]["annotation_id"] == "legacy_ann"
    assert rows[0]["setup_bar_index"] == 9
    assert rows[0]["decision_bar_index"] == 9
    assert rows[0]["annotation_version"] == "entry_annotations_v1"
    assert rows[0]["is_active"] == 1


def test_existing_session_without_entry_annotations_exports_without_crashing(tmp_path):
    storage = StorageManager(tmp_path / "legacy_export.db")
    storage.upsert_session(
        {
            "session_id": "session_without_annotations",
            "symbol": "BTCUSDT",
            "interval": "5m",
            "last_saved_at": "2026-01-01T00:00:00Z",
        }
    )

    export_dir = Exporter(storage).export_session("session_without_annotations", tmp_path / "exports")
    manifest = json.loads((export_dir / "export_manifest.json").read_text(encoding="utf-8"))

    assert (export_dir / "entry_annotations.csv").exists()
    assert manifest["row_counts"]["entry_annotations"] == 0


def test_persisted_entry_annotations_are_exported_with_session(tmp_path):
    storage = StorageManager(tmp_path / "entry_annotation_export.db")
    storage.upsert_session(
        {
            "session_id": "session_1",
            "symbol": "BTCUSDT",
            "interval": "5m",
            "last_saved_at": "2026-01-01T00:00:00Z",
        }
    )
    storage.save_entry_annotation(_entry_annotation())

    export_dir = Exporter(storage).export_session("session_1", tmp_path / "exports")

    with (export_dir / "entry_annotations.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    report = json.loads((export_dir / "entry_logic_report.json").read_text(encoding="utf-8"))

    assert len(rows) == 1
    assert rows[0]["annotation_id"] == "ann_1"
    assert rows[0]["human_decision"] == "ENTRY"
    assert "lower_shadow" in rows[0]["reason_tags_json"]
    assert report["annotation_overview"]["ENTRY"] == 1


def test_soft_deleted_entry_annotations_are_not_exported_by_default(tmp_path):
    storage = StorageManager(tmp_path / "entry_annotation_export_deleted.db")
    storage.upsert_session(
        {
            "session_id": "session_1",
            "symbol": "BTCUSDT",
            "interval": "5m",
            "last_saved_at": "2026-01-01T00:00:00Z",
        }
    )
    storage.save_entry_annotation(_entry_annotation())
    storage.delete_entry_annotation("ann_1")

    export_dir = Exporter(storage).export_session("session_1", tmp_path / "exports")

    with (export_dir / "entry_annotations.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows == []
