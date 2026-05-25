from __future__ import annotations

import sqlite3

import pytest

from errors import DatabaseError
from storage import StorageManager


def test_locked_database_returns_user_facing_error(tmp_path):
    path = tmp_path / "locked.db"
    storage = StorageManager(path)
    storage.upsert_session({"session_id": "seed"})
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN EXCLUSIVE")
    blocker.execute("UPDATE sessions SET symbol='LOCKED' WHERE session_id='seed'")
    try:
        with pytest.raises(DatabaseError, match="temporarily busy"):
            storage.upsert_session({"session_id": "other"})
    finally:
        blocker.rollback()
        blocker.close()
