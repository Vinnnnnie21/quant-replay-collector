from __future__ import annotations

from pathlib import Path


class ExportService:
    """Run session exports through a stable service entry point."""

    def __init__(self, storage):
        self.storage = storage

    def export_session(self, session_id: str, target: Path) -> Path:
        from exporter import Exporter

        return Path(Exporter(self.storage).export_session(session_id, target))


__all__ = ["ExportService"]
