from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExportResult:
    output_dir: Path | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.output_dir is not None


class ExportController:
    def __init__(self, exporter) -> None:
        self.exporter = exporter

    def export_session(self, session_id: str, target: Path) -> ExportResult:
        try:
            return ExportResult(self.exporter.export_session(session_id, target).resolve())
        except Exception as exc:
            return ExportResult(None, f"{type(exc).__name__}: {exc}")
