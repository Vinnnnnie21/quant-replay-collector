from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore

try:
    from cancellation import CancellationToken
    from research.entry_behavior_model import (
        EntryBehaviorTrainingRequest,
        EntryBehaviorTrainingResult,
    )
    from services.entry_behavior_training import (
        EntryBehaviorTrainingCancelled,
    )
except ImportError:  # pragma: no cover - package import path
    from ..cancellation import CancellationToken
    from ..research.entry_behavior_model import (
        EntryBehaviorTrainingRequest,
        EntryBehaviorTrainingResult,
    )
    from ..services.entry_behavior_training import (
        EntryBehaviorTrainingCancelled,
    )


@dataclass(frozen=True, slots=True)
class EntryBehaviorTrainingProgress:
    revision: int
    completed: int
    total: int


@dataclass(frozen=True, slots=True)
class EntryBehaviorTrainingCompleted:
    revision: int
    result: EntryBehaviorTrainingResult


@dataclass(frozen=True, slots=True)
class EntryBehaviorTrainingFailure:
    revision: int
    message: str


class EntryBehaviorTrainingWorker(QtCore.QObject):
    progress = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(int)

    def __init__(
        self,
        service: Any,
        request: EntryBehaviorTrainingRequest,
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
            result = self._service.train(
                self._request,
                cancelled=self.cancellation_token.is_requested,
                progress=lambda completed, total: self.progress.emit(
                    EntryBehaviorTrainingProgress(
                        self._revision,
                        int(completed),
                        int(total),
                    )
                ),
            )
        except EntryBehaviorTrainingCancelled:
            self.cancelled.emit(self._revision)
        except Exception as exc:
            self.failed.emit(
                EntryBehaviorTrainingFailure(
                    self._revision,
                    f"{type(exc).__name__}: {exc}",
                )
            )
        else:
            self.finished.emit(
                EntryBehaviorTrainingCompleted(self._revision, result)
            )


__all__ = [
    "EntryBehaviorTrainingCompleted",
    "EntryBehaviorTrainingFailure",
    "EntryBehaviorTrainingProgress",
    "EntryBehaviorTrainingWorker",
]
