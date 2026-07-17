from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6 import QtCore

try:
    from cancellation import CancellationToken
    from database_backup import BackupCancelled, backup_database_if_needed
except ImportError:  # pragma: no cover - package import path
    from ..cancellation import CancellationToken
    from ..database_backup import BackupCancelled, backup_database_if_needed


class DatabaseBackupWorker(QtCore.QObject):
    progress = QtCore.Signal(str)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(
        self,
        db_path: str | Path,
        backup_dir: str | Path,
        *,
        backup_fn: Callable[..., dict[str, Any]] = backup_database_if_needed,
    ) -> None:
        super().__init__()
        self._db_path = Path(db_path)
        self._backup_dir = Path(backup_dir)
        self._backup_fn = backup_fn
        self.cancellation_token = CancellationToken()

    @QtCore.Slot()
    def request_stop(self) -> None:
        self.cancellation_token.request()

    def _on_pages_copied(self, copied: int, total: int) -> None:
        if total > 0:
            percent = min(100, max(0, int(copied * 100 / total)))
            self.progress.emit(f"Backing up local database in background... {percent}%")

    @QtCore.Slot()
    def run(self) -> None:
        if self.cancellation_token.is_requested():
            self.cancelled.emit()
            return
        self.progress.emit("Backing up local database in background...")
        try:
            result = self._backup_fn(
                self._db_path,
                self._backup_dir,
                cancelled=self.cancellation_token.is_requested,
                progress=self._on_pages_copied,
            )
        except BackupCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(result)


__all__ = ["DatabaseBackupWorker"]
