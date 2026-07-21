from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore

try:
    from cancellation import CancellationToken
    from research.cancellation import ResearchCancelled
except ImportError:  # pragma: no cover - package import path
    from ..cancellation import CancellationToken
    from ..research.cancellation import ResearchCancelled


@dataclass(frozen=True, slots=True)
class ResearchSnapshotProgress:
    revision: int
    message: str


@dataclass(frozen=True, slots=True)
class ResearchSnapshotCompleted:
    revision: int
    publication: Any | None
    view: Any


@dataclass(frozen=True, slots=True)
class ResearchSnapshotFailure:
    revision: int
    message: str


class ResearchSnapshotWorker(QtCore.QObject):
    """Publish one snapshot without touching QWidget state."""

    progress = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(int)

    def __init__(self, service: Any, request: Any, revision: int) -> None:
        super().__init__()
        self._service = service
        self._request = request
        self._revision = int(revision)
        self.cancellation_token = CancellationToken()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            snapshot_id = getattr(self._request, "snapshot_id", None)
            if snapshot_id is not None:
                publication = None
                view = self._service.read(str(snapshot_id))
            else:
                publication = self._service.publish(
                    self._request.snapshot_input,
                    created_at=self._request.created_at,
                    cancelled=self.cancellation_token.is_requested,
                    progress=lambda message: self.progress.emit(
                        ResearchSnapshotProgress(self._revision, str(message))
                    ),
                )
                view = self._service.read(publication.snapshot.snapshot_id)
        except ResearchCancelled:
            self.cancelled.emit(self._revision)
        except Exception as exc:
            self.failed.emit(
                ResearchSnapshotFailure(
                    self._revision,
                    f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            self.finished.emit(
                ResearchSnapshotCompleted(
                    self._revision,
                    publication,
                    view,
                )
            )


__all__ = [
    "ResearchSnapshotCompleted",
    "ResearchSnapshotFailure",
    "ResearchSnapshotProgress",
    "ResearchSnapshotWorker",
]
