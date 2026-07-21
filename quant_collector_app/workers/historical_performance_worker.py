from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6 import QtCore

try:
    from accounting import EquityCurveCancelled, build_continuous_equity_curve
    from cancellation import CancellationToken
    from services.analysis_refresh import build_performance_workspace_payload
    from services.performance_market_data import load_session_performance_market_data
    from storage import StorageManager
except ImportError:  # pragma: no cover - package import path
    from ..accounting import EquityCurveCancelled, build_continuous_equity_curve
    from ..cancellation import CancellationToken
    from ..services.analysis_refresh import build_performance_workspace_payload
    from ..services.performance_market_data import load_session_performance_market_data
    from ..storage import StorageManager


@dataclass(frozen=True)
class HistoricalPerformanceResult:
    session_id: str
    revision: int
    payload: Any | None
    empty_reason: str | None = None


@dataclass(frozen=True)
class HistoricalPerformanceFailure:
    revision: int
    message: str


@dataclass(frozen=True)
class HistoricalPerformanceCancellation:
    revision: int


class HistoricalPerformanceWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(object)

    def __init__(self, db_path: str, cache_dir: str | Path | None = None) -> None:
        super().__init__()
        self._db_path = str(db_path)
        self._cache_dir = (
            Path(cache_dir)
            if cache_dir is not None
            else Path(db_path).parent / "cache"
        )
        self.cancellation_token = CancellationToken()

    def request_stop(self) -> None:
        self.cancellation_token.request()

    @QtCore.Slot(object)
    def run(self, request: Any) -> None:
        revision = int(request.revision)
        if self.cancellation_token.is_requested():
            self.cancelled.emit(HistoricalPerformanceCancellation(revision))
            return
        try:
            storage = StorageManager(self._db_path)
            session, trades, _events = storage.load_session_snapshot(request.session_id)
            if self.cancellation_token.is_requested():
                self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                return
            if session is None:
                raise ValueError(f"Historical session not found: {request.session_id}")
            market_data = load_session_performance_market_data(
                storage,
                session,
                trades,
                cache_dir=self._cache_dir,
                cancelled=self.cancellation_token.is_requested,
            )
            if self.cancellation_token.is_requested():
                self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                return
            if market_data is None:
                self.finished.emit(
                    HistoricalPerformanceResult(
                        str(request.session_id),
                        revision,
                        None,
                        "performance.curve_missing_market_data",
                    )
                )
                return
            equity_rows = build_continuous_equity_curve(
                market_data.rows,
                trades,
                str(request.session_id),
                float(session.get("initial_equity") or 10_000.0),
                float(session.get("trade_notional") or 1_000.0),
                cancelled=self.cancellation_token.is_requested,
            )
            if self.cancellation_token.is_requested():
                self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                return
            payload = build_performance_workspace_payload(
                equity_rows=equity_rows,
                trades=trades,
                initial_equity=float(session.get("initial_equity") or 10_000.0),
                default_notional=float(session.get("trade_notional") or 1_000.0),
            )
            if self.cancellation_token.is_requested():
                self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                return
            self.finished.emit(
                HistoricalPerformanceResult(request.session_id, revision, payload)
            )
        except EquityCurveCancelled:
            self.cancelled.emit(HistoricalPerformanceCancellation(revision))
        except Exception as exc:
            if self.cancellation_token.is_requested():
                self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                return
            self.failed.emit(
                HistoricalPerformanceFailure(
                    revision,
                    f"{type(exc).__name__}: {exc}",
                )
            )


__all__ = [
    "HistoricalPerformanceCancellation",
    "HistoricalPerformanceFailure",
    "HistoricalPerformanceResult",
    "HistoricalPerformanceWorker",
]
