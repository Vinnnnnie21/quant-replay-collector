from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore

try:
    from cancellation import CancellationToken
    from research.candidate_retrieval import StructuralCandidateScanCancelled
except ImportError:  # pragma: no cover - package import path
    from ..cancellation import CancellationToken
    from ..research.candidate_retrieval import StructuralCandidateScanCancelled


@dataclass(frozen=True, slots=True)
class CandidateScanProgress:
    revision: int
    completed: int
    total: int


@dataclass(frozen=True, slots=True)
class CandidateScanCompleted:
    revision: int
    result: Any


@dataclass(frozen=True, slots=True)
class CandidateScanFailure:
    revision: int
    message: str


class EntryCandidateScanWorker(QtCore.QObject):
    progress = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(object)

    def __init__(self, service: Any, request: Any, revision: int) -> None:
        super().__init__()
        self._service = service
        self._request = request
        self._revision = int(revision)
        self.cancellation_token = CancellationToken()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            result = self._service.scan(
                self._request,
                cancelled=self.cancellation_token.is_requested,
                progress=lambda done, total: self.progress.emit(
                    CandidateScanProgress(self._revision, done, total)
                ),
            )
        except StructuralCandidateScanCancelled:
            self.cancelled.emit(self._revision)
        except Exception as exc:
            self.failed.emit(
                CandidateScanFailure(
                    self._revision,
                    f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            self.finished.emit(CandidateScanCompleted(self._revision, result))


__all__ = [
    "CandidateScanCompleted",
    "CandidateScanFailure",
    "CandidateScanProgress",
    "EntryCandidateScanWorker",
]
