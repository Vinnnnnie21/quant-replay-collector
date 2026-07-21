from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from PySide6 import QtCore

try:
    from cancellation import CancellationToken
    from market_data.client import MarketDataClient
    from market_data.types import DataLoadCancelled
    from services.full_history_ancillary_backfill import (
        FullHistoryAncillaryBackfillService,
        FullHistoryBackfillError,
        FullHistoryBackfillResult,
    )
    from services.research_data_availability import (
        ResearchDataAvailabilityService,
        ResearchRangeRequest,
    )
    from services.research_data_backfill import (
        ResearchBackfillError,
        ResearchBackfillProgress,
        ResearchBackfillResult,
        ResearchBackfillStatus,
        ResearchDataBackfillService,
    )
    from storage import StorageManager
except ImportError:  # pragma: no cover - package import path
    from ..cancellation import CancellationToken
    from ..market_data.client import MarketDataClient
    from ..market_data.types import DataLoadCancelled
    from ..services.full_history_ancillary_backfill import (
        FullHistoryAncillaryBackfillService,
        FullHistoryBackfillError,
        FullHistoryBackfillResult,
    )
    from ..services.research_data_availability import (
        ResearchDataAvailabilityService,
        ResearchRangeRequest,
    )
    from ..services.research_data_backfill import (
        ResearchBackfillError,
        ResearchBackfillProgress,
        ResearchBackfillResult,
        ResearchBackfillStatus,
        ResearchDataBackfillService,
    )
    from ..storage import StorageManager


class ResearchDataTaskMode(str, Enum):
    AUDIT = "audit"
    BACKFILL = "backfill"
    FULL_HISTORY = "full_history"


@dataclass(frozen=True)
class ResearchBackfillTask:
    revision: int
    db_path: str
    request: ResearchRangeRequest | None
    mode: ResearchDataTaskMode = ResearchDataTaskMode.BACKFILL


@dataclass(frozen=True)
class ResearchBackfillProgressEvent:
    revision: int
    progress: ResearchBackfillProgress


@dataclass(frozen=True)
class ResearchBackfillFinished:
    revision: int
    result: ResearchBackfillResult


@dataclass(frozen=True)
class ResearchBackfillFailure:
    revision: int
    message: str
    result: ResearchBackfillResult | None


@dataclass(frozen=True)
class ResearchBackfillCancellation:
    revision: int
    result: ResearchBackfillResult


@dataclass(frozen=True)
class ResearchAuditFinished:
    revision: int
    report: Any


@dataclass(frozen=True)
class ResearchAuditCancellation:
    revision: int


@dataclass(frozen=True)
class FullHistoryBackfillFinished:
    revision: int
    result: FullHistoryBackfillResult


@dataclass(frozen=True)
class FullHistoryBackfillFailure:
    revision: int
    message: str
    result: FullHistoryBackfillResult | None


@dataclass(frozen=True)
class FullHistoryBackfillCancellation:
    revision: int
    result: FullHistoryBackfillResult


class ResearchBackfillWorker(QtCore.QObject):
    """Run research-data backfill without accessing any QWidget."""

    progress = QtCore.Signal(object)
    inspected = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(object)
    maintenanceFinished = QtCore.Signal(object)
    maintenanceFailed = QtCore.Signal(object)
    maintenanceCancelled = QtCore.Signal(object)

    def __init__(
        self,
        *,
        network_factory: Callable[[], Any] = MarketDataClient,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._network_factory = network_factory
        self.cancellation_token = CancellationToken()

    @QtCore.Slot(object)
    def run(self, task: ResearchBackfillTask) -> None:
        try:
            storage = StorageManager(task.db_path)
            if task.mode is ResearchDataTaskMode.FULL_HISTORY:
                result = FullHistoryAncillaryBackfillService(
                    storage=storage,
                    network=self._network_factory(),
                ).backfill(
                    cancelled=self.cancellation_token.is_requested,
                )
                event = (
                    FullHistoryBackfillCancellation(task.revision, result)
                    if result.cancelled
                    else FullHistoryBackfillFinished(task.revision, result)
                )
                signal = (
                    self.maintenanceCancelled
                    if result.cancelled
                    else self.maintenanceFinished
                )
                signal.emit(event)
                return
            if task.request is None:
                raise ValueError(
                    "Research audit/backfill task requires a range request"
                )
            if task.mode is ResearchDataTaskMode.AUDIT:
                report = ResearchDataAvailabilityService(storage).inspect(
                    task.request,
                    cancelled=self.cancellation_token.is_requested,
                )
                self.inspected.emit(
                    ResearchAuditFinished(task.revision, report)
                )
                return
            service = ResearchDataBackfillService(
                storage=storage,
                network=self._network_factory(),
            )
            result = service.backfill(
                task.request,
                cancelled=self.cancellation_token.is_requested,
                progress=lambda event: self.progress.emit(
                    ResearchBackfillProgressEvent(task.revision, event)
                ),
            )
            if result.status is ResearchBackfillStatus.CANCELLED:
                self.cancelled.emit(
                    ResearchBackfillCancellation(task.revision, result)
                )
                return
            self.finished.emit(ResearchBackfillFinished(task.revision, result))
        except DataLoadCancelled:
            if task.mode is ResearchDataTaskMode.FULL_HISTORY:
                self.maintenanceCancelled.emit(
                    FullHistoryBackfillCancellation(
                        task.revision,
                        FullHistoryBackfillResult(
                            total_series=0,
                            completed_series=0,
                            downloaded_bars=0,
                            is_complete=False,
                            cancelled=True,
                        ),
                    )
                )
                return
            self.cancelled.emit(ResearchAuditCancellation(task.revision))
        except FullHistoryBackfillError as exc:
            self.maintenanceFailed.emit(
                FullHistoryBackfillFailure(
                    revision=task.revision,
                    message=str(exc),
                    result=exc.result,
                )
            )
        except ResearchBackfillError as exc:
            self.failed.emit(
                ResearchBackfillFailure(
                    revision=task.revision,
                    message=str(exc),
                    result=exc.result,
                )
            )
        except Exception as exc:
            if task.mode is ResearchDataTaskMode.FULL_HISTORY:
                self.maintenanceFailed.emit(
                    FullHistoryBackfillFailure(
                        revision=task.revision,
                        message=f"{type(exc).__name__}: {exc}",
                        result=None,
                    )
                )
                return
            self.failed.emit(
                ResearchBackfillFailure(
                    revision=task.revision,
                    message=f"{type(exc).__name__}: {exc}",
                    result=None,
                )
            )


__all__ = [
    "ResearchBackfillCancellation",
    "ResearchBackfillFailure",
    "ResearchBackfillFinished",
    "ResearchBackfillProgressEvent",
    "ResearchBackfillTask",
    "ResearchBackfillWorker",
    "ResearchAuditFinished",
    "ResearchAuditCancellation",
    "ResearchDataTaskMode",
    "FullHistoryBackfillCancellation",
    "FullHistoryBackfillFailure",
    "FullHistoryBackfillFinished",
]
