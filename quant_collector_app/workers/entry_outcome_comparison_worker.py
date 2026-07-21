from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore

try:
    from cancellation import CancellationToken
    from research.cancellation import ResearchCancelled
    from research.entry_outcome_comparison import (
        EntryOutcomeComparisonRequest,
        EntryOutcomeComparisonResult,
    )
except ImportError:  # pragma: no cover - package import path
    from ..cancellation import CancellationToken
    from ..research.cancellation import ResearchCancelled
    from ..research.entry_outcome_comparison import (
        EntryOutcomeComparisonRequest,
        EntryOutcomeComparisonResult,
    )


@dataclass(frozen=True, slots=True)
class EntryOutcomeComparisonProgress:
    revision: int
    completed: int
    total: int


@dataclass(frozen=True, slots=True)
class EntryOutcomeComparisonCompleted:
    revision: int
    result: EntryOutcomeComparisonResult


@dataclass(frozen=True, slots=True)
class EntryOutcomeComparisonFailure:
    revision: int
    message: str


class EntryOutcomeComparisonWorker(QtCore.QObject):
    progress = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(int)

    def __init__(
        self,
        service: Any,
        request: EntryOutcomeComparisonRequest,
        revision: int,
    ) -> None:
        super().__init__()
        self._service = service
        self._request = request
        self._revision = int(revision)
        self.cancellation_token = CancellationToken()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            result = self._service.run(
                setup_version_id=self._request.setup_version_id,
                grouping_version_id=self._request.grouping_version_id,
                direction=self._request.direction,
                random_seed=self._request.random_seed,
                cancelled=self.cancellation_token.is_requested,
                progress=lambda completed, total: self.progress.emit(
                    EntryOutcomeComparisonProgress(
                        self._revision,
                        int(completed),
                        int(total),
                    )
                ),
            )
        except ResearchCancelled:
            self.cancelled.emit(self._revision)
        except Exception as exc:
            self.failed.emit(
                EntryOutcomeComparisonFailure(
                    self._revision,
                    f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            self.finished.emit(
                EntryOutcomeComparisonCompleted(self._revision, result)
            )


__all__ = [
    "EntryOutcomeComparisonCompleted",
    "EntryOutcomeComparisonFailure",
    "EntryOutcomeComparisonProgress",
    "EntryOutcomeComparisonWorker",
]
