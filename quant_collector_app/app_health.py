from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path


CORE_REQUIRED_DEPENDENCIES = ("pandas", "numpy", "requests")
GUI_REQUIRED_DEPENDENCIES = ("PySide6", "pyqtgraph")
REQUIRED_DEPENDENCIES = CORE_REQUIRED_DEPENDENCIES + GUI_REQUIRED_DEPENDENCIES
OPTIONAL_DEPENDENCIES = ("pyarrow", "matplotlib", "fastapi", "uvicorn")


def _directory_write_check(path: Path) -> dict:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".health_", dir=path, delete=True):
            pass
        return {"path": str(path), "writable": True, "error": None}
    except OSError as exc:
        return {"path": str(path), "writable": False, "error": str(exc)}


def _database_check(path: Path) -> dict:
    conn = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("SELECT 1").fetchone()
        return {"path": str(path), "connectable": True, "error": None}
    except sqlite3.Error as exc:
        return {"path": str(path), "connectable": False, "error": str(exc)}
    finally:
        if conn is not None:
            conn.close()


def run_health_checks(runtime_root: Path, db_path: Path | None = None, require_gui: bool | None = None) -> dict:
    runtime_root = Path(runtime_root)
    dirs = [_directory_write_check(runtime_root / name) for name in ("data", "cache", "exports", "logs")]
    dependencies = (
        REQUIRED_DEPENDENCIES
        if require_gui is None
        else CORE_REQUIRED_DEPENDENCIES + GUI_REQUIRED_DEPENDENCIES
        if require_gui
        else CORE_REQUIRED_DEPENDENCIES
    )
    required = {name: importlib.util.find_spec(name) is not None for name in dependencies}
    optional = {name: importlib.util.find_spec(name) is not None for name in OPTIONAL_DEPENDENCIES}
    database = _database_check(Path(db_path or runtime_root / "data" / "health.db"))
    errors = [row["error"] for row in dirs if not row["writable"]]
    errors.extend(f"missing dependency: {name}" for name, present in required.items() if not present)
    if not database["connectable"]:
        errors.append(f"database: {database['error']}")
    return {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "ok" if not errors else "failed",
        "directories": dirs,
        "database": database,
        "required_dependencies": required,
        "gui_required": bool(require_gui),
        "optional_dependencies": optional,
        "errors": errors,
    }
