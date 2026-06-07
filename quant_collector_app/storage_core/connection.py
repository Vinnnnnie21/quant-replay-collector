from __future__ import annotations

import sqlite3
from contextlib import contextmanager

try:
    from errors import DatabaseError
except ImportError:  # pragma: no cover - package import path
    from ..errors import DatabaseError


@contextmanager
def connect_db(db_path: str):
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        raise DatabaseError(f"Cannot open database: {exc}") from exc
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower():
            raise DatabaseError("Database is temporarily busy. Please retry after the current save completes.") from exc
        raise DatabaseError(f"SQLite operation failed: {exc}") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def require_rowcount(cursor, expected: int, message: str) -> None:
    if cursor.rowcount != expected:
        raise RuntimeError(f"{message}，期望影响 {expected} 行，实际影响 {cursor.rowcount} 行")
