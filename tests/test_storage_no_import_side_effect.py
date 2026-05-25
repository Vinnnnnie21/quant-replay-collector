from __future__ import annotations

import importlib
import sqlite3


def test_importing_storage_does_not_construct_manager(monkeypatch):
    module = importlib.import_module("storage")
    called = []
    original_connect = sqlite3.connect

    def monitored_connect(*args, **kwargs):
        called.append(args[0] if args else None)
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", monitored_connect)

    importlib.reload(module)

    assert called == []
