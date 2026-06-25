from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from app_config import BACKUP_DIR, DB_PATH
except ImportError:  # pragma: no cover - package import path
    from .app_config import BACKUP_DIR, DB_PATH


BACKUP_NAME_PREFIX = "quant_replay"
ANNOTATION_TABLES = ("entry_annotations", "entry_annotation_history")
PROTECTED_TABLES = ("sessions", "trades", "entry_annotations", "entry_annotation_history")


def backup_database(db_path: str | Path = DB_PATH, backup_dir: str | Path = BACKUP_DIR) -> dict[str, Any]:
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"Database does not exist: {source}")
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _next_backup_path(target_dir)
    with sqlite3.connect(source) as src, sqlite3.connect(backup_path) as dst:
        src.backup(dst)
    verification = verify_backup(backup_path)
    return {
        "status": "ok",
        "db_path": source,
        "backup_path": backup_path,
        "verification": verification,
    }


def list_backups(backup_dir: str | Path = BACKUP_DIR) -> list[Path]:
    directory = Path(backup_dir)
    if not directory.exists():
        return []
    return sorted(directory.glob(f"{BACKUP_NAME_PREFIX}_*.db"))


def verify_backup(backup_path: str | Path) -> dict[str, Any]:
    path = Path(backup_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup does not exist: {path}")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity.lower() != "ok":
                raise ValueError(f"integrity_check returned {integrity}")
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
    except Exception as exc:
        raise ValueError(f"SQLite backup verification failed: {exc}") from exc
    return {
        "status": "ok",
        "backup_path": path,
        "integrity_check": "ok",
        "schema_version": schema_version,
        "tables": tables,
    }


def run_database_integrity_check(
    db_path: str | Path = DB_PATH,
    *,
    expected_schema_version: int | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {
            "status": "warning",
            "database_exists": False,
            "db_path": str(path),
            "warning": f"Database does not exist: {path}",
        }
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            missing_required_tables = _missing_required_tables(tables, expected_schema_version)
            counts = _protected_table_counts(conn, tables)
    except Exception as exc:
        return {
            "status": "failed",
            "database_exists": True,
            "db_path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    migration_status = _migration_status(schema_version, expected_schema_version, missing_required_tables)
    status = _database_integrity_status(integrity, migration_status)
    return {
        "status": status,
        "database_exists": True,
        "db_path": str(path),
        "integrity_check": integrity,
        "schema_version": schema_version,
        "expected_schema_version": expected_schema_version,
        "migration_status": migration_status,
        "missing_required_tables": missing_required_tables,
        "protected_table_counts": counts,
    }


def backup_database_if_needed(
    db_path: str | Path = DB_PATH,
    backup_dir: str | Path = BACKUP_DIR,
    *,
    today: str | None = None,
) -> dict[str, Any]:
    date_text = today or datetime.now().strftime("%Y%m%d")
    existing_today = [
        path for path in list_backups(backup_dir) if path.name.startswith(f"{BACKUP_NAME_PREFIX}_{date_text}_")
    ]
    if existing_today:
        return {"status": "skipped", "reason": "daily_backup_already_exists", "backup_path": existing_today[-1]}
    return backup_database(db_path, backup_dir)


def export_annotations_jsonl(db_path: str | Path = DB_PATH, backup_dir: str | Path = BACKUP_DIR) -> dict[str, Any]:
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"Database does not exist: {source}")
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = _next_annotations_path(target_dir)
    rows = _entry_annotation_rows(source)
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return {"status": "ok", "jsonl_path": jsonl_path, "row_count": len(rows)}


def _next_backup_path(backup_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = backup_dir / f"{BACKUP_NAME_PREFIX}_{timestamp}.db"
    suffix = 1
    while candidate.exists():
        candidate = backup_dir / f"{BACKUP_NAME_PREFIX}_{timestamp}_{suffix:02d}.db"
        suffix += 1
    return candidate


def _next_annotations_path(backup_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = backup_dir / f"entry_annotations_{timestamp}.jsonl"
    suffix = 1
    while candidate.exists():
        candidate = backup_dir / f"entry_annotations_{timestamp}_{suffix:02d}.jsonl"
        suffix += 1
    return candidate


def _entry_annotation_rows(db_path: Path) -> list[dict[str, Any]]:
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            rows: list[dict[str, Any]] = []
            if "entry_annotations" in tables:
                for row in conn.execute("SELECT * FROM entry_annotations ORDER BY updated_at, annotation_id"):
                    item = dict(row)
                    item["_table"] = "entry_annotations"
                    _decode_reason_tags(item)
                    rows.append(item)
            if "entry_annotation_history" in tables:
                for row in conn.execute(
                    "SELECT * FROM entry_annotation_history ORDER BY annotation_id, revision_no, history_id"
                ):
                    item = dict(row)
                    item["_table"] = "entry_annotation_history"
                    _decode_snapshot(item)
                    rows.append(item)
            return rows
    except sqlite3.Error as exc:
        raise ValueError(f"Entry annotation JSONL export failed: {exc}") from exc


def _decode_reason_tags(row: dict[str, Any]) -> None:
    reason_tags_json = row.get("reason_tags_json")
    try:
        parsed = json.loads(reason_tags_json or "[]")
        row["reason_tags"] = parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        row["reason_tags"] = []


def _decode_snapshot(row: dict[str, Any]) -> None:
    try:
        snapshot = json.loads(row.get("snapshot_json") or "{}")
        row["snapshot"] = snapshot if isinstance(snapshot, dict) else {}
    except json.JSONDecodeError:
        row["snapshot"] = {}


def _protected_table_counts(conn: sqlite3.Connection, tables: set[str]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for table in PROTECTED_TABLES:
        counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if table in tables else None
    return counts


def _missing_required_tables(tables: set[str], expected_schema_version: int | None) -> list[str]:
    if expected_schema_version is None:
        return []
    required = {"sessions", "trades"}
    if int(expected_schema_version) >= 6:
        required.update(ANNOTATION_TABLES)
    return sorted(required - tables)


def _migration_status(
    schema_version: int,
    expected_schema_version: int | None,
    missing_required_tables: list[str],
) -> str:
    if expected_schema_version is None:
        return "unknown"
    expected = int(expected_schema_version)
    if schema_version > expected:
        return "newer_than_supported"
    if schema_version < expected:
        return "outdated"
    if missing_required_tables:
        return "incomplete_schema"
    return "current"


def _database_integrity_status(integrity: str, migration_status: str) -> str:
    if integrity.lower() != "ok" or migration_status == "newer_than_supported":
        return "failed"
    if migration_status in {"outdated", "incomplete_schema"}:
        return "warning"
    return "ok"


__all__ = [
    "backup_database",
    "backup_database_if_needed",
    "export_annotations_jsonl",
    "list_backups",
    "run_database_integrity_check",
    "verify_backup",
]