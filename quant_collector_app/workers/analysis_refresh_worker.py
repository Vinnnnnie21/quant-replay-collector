from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import time
from typing import Any

import pandas as pd
from PySide6 import QtCore

try:
    from app_logger import get_logger
    from cancellation import CancellationToken
    from services.analysis_refresh import (
        AnalysisRefreshCancelled,
        AnalysisRefreshCancellation,
        AnalysisRefreshFailure,
        AnalysisRefreshProgress,
        AnalysisRefreshRequest,
        AnalysisRefreshResult,
        AnalysisRefreshSnapshot,
        build_analysis_refresh_result,
        prepare_analysis_refresh_snapshot,
    )
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger
    from ..cancellation import CancellationToken
    from ..services.analysis_refresh import (
        AnalysisRefreshCancelled,
        AnalysisRefreshCancellation,
        AnalysisRefreshFailure,
        AnalysisRefreshProgress,
        AnalysisRefreshRequest,
        AnalysisRefreshResult,
        AnalysisRefreshSnapshot,
        build_analysis_refresh_result,
        prepare_analysis_refresh_snapshot,
    )


logger = get_logger(__name__)


class AnalysisRefreshWorker(QtCore.QObject):
    progress = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(object)
    cancelled = QtCore.Signal(object)

    def __init__(
        self,
        *,
        build_event_study_fn: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame] | None = None,
        build_ml_datasets_fn: Callable[[pd.DataFrame], dict[str, pd.DataFrame]] | None = None,
        build_performance_summary_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]], float], dict[str, Any]] | None = None,
        format_performance_report_fn: Callable[[dict[str, Any]], str] | None = None,
        storage_factory: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__()
        self._build_event_study_fn = build_event_study_fn
        self._build_ml_datasets_fn = build_ml_datasets_fn
        self._build_performance_summary_fn = build_performance_summary_fn
        self._format_performance_report_fn = format_performance_report_fn
        self._storage_factory = storage_factory
        self.cancellation_token = CancellationToken()

    @QtCore.Slot()
    def request_stop(self) -> None:
        self.cancellation_token.request()

    @QtCore.Slot(object)
    def run(self, request: AnalysisRefreshSnapshot | AnalysisRefreshRequest) -> None:
        revision = int(request.revision)
        if self.cancellation_token.is_requested():
            self.cancelled.emit(AnalysisRefreshCancellation(revision))
            return
        try:
            preparation = None
            snapshot = request
            if isinstance(request, AnalysisRefreshRequest):
                snapshot, preparation = prepare_analysis_refresh_snapshot(
                    request,
                    storage_factory=self._storage_factory,
                    cancelled=self.cancellation_token.is_requested,
                )
            calculation_started = time.perf_counter()
            result: AnalysisRefreshResult = build_analysis_refresh_result(
                snapshot,
                build_event_study_fn=self._build_event_study_fn,
                build_ml_datasets_fn=self._build_ml_datasets_fn,
                build_performance_summary_fn=self._build_performance_summary_fn,
                format_performance_report_fn=self._format_performance_report_fn,
                cancelled=self.cancellation_token.is_requested,
                progress=lambda message: self.progress.emit(
                    AnalysisRefreshProgress(revision, str(message))
                ),
            )
            if preparation is not None:
                preparation = replace(
                    preparation,
                    calculation_seconds=time.perf_counter() - calculation_started,
                )
                result = replace(result, preparation=preparation)
            self.finished.emit(result)
        except AnalysisRefreshCancelled:
            self.cancelled.emit(AnalysisRefreshCancellation(revision))
        except Exception as exc:
            logger.exception("Analysis refresh worker failed.")
            self.failed.emit(
                AnalysisRefreshFailure(revision, f"{type(exc).__name__}: {exc}")
            )


__all__ = ["AnalysisRefreshWorker"]
