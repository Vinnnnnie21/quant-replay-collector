from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_EXPORT_LANGUAGE = "zh_CN"
DEFAULT_EXPORT_LABEL = "fwd_ret_10_side_adj"


@dataclass(frozen=True)
class ExportTaskRequest:
    target: Path
    session_id: str
    language: str
    selected_label: str


def build_export_task_request(
    *,
    target: str | Path,
    session_id: Any,
    language: str | None,
    selected_label: str | None,
) -> ExportTaskRequest:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id is required")
    return ExportTaskRequest(
        target=Path(target),
        session_id=normalized_session_id,
        language=str(language or DEFAULT_EXPORT_LANGUAGE),
        selected_label=str(selected_label or DEFAULT_EXPORT_LABEL),
    )


class ExportService:
    """Run session exports through a stable service entry point."""

    def __init__(self, storage):
        self.storage = storage

    def export_session(self, session_id: str, target: Path) -> Path:
        from exporter import Exporter

        return Path(Exporter(self.storage).export_session(session_id, target))


__all__ = [
    "DEFAULT_EXPORT_LABEL",
    "DEFAULT_EXPORT_LANGUAGE",
    "ExportService",
    "ExportTaskRequest",
    "build_export_task_request",
]
