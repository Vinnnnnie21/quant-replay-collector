from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
from PySide6 import QtCore

try:
    from app_logger import get_logger
    from services.analysis_refresh import (
        AnalysisRefreshResult,
        AnalysisRefreshSnapshot,
        build_analysis_refresh_result,
    )
except ImportError:  # pragma: no cover - package import path
    from ..app_logger import get_logger
    from ..services.analysis_refresh import (
        AnalysisRefreshResult,
        AnalysisRefreshSnapshot,
        build_analysis_refresh_result,
    )


logger = get_logger(__name__)


class AnalysisRefreshWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self,
        *,
        build_event_study_fn: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame] | None = None,
        build_ml_datasets_fn: Callable[[pd.DataFrame], dict[str, pd.DataFrame]] | None = None,
        build_performance_summary_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]], float], dict[str, Any]] | None = None,
        format_performance_report_fn: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        super().__init__()
        self._build_event_study_fn = build_event_study_fn
        self._build_ml_datasets_fn = build_ml_datasets_fn
        self._build_performance_summary_fn = build_performance_summary_fn
        self._format_performance_report_fn = format_performance_report_fn

    @QtCore.Slot(object)
    def run(self, snapshot: AnalysisRefreshSnapshot) -> None:
        try:
            result: AnalysisRefreshResult = build_analysis_refresh_result(
                snapshot,
                build_event_study_fn=self._build_event_study_fn,
                build_ml_datasets_fn=self._build_ml_datasets_fn,
                build_performance_summary_fn=self._build_performance_summary_fn,
                format_performance_report_fn=self._format_performance_report_fn,
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("Analysis refresh worker failed.")
            self.failed.emit(f"{type(exc).__name__}: {exc}")


__all__ = ["AnalysisRefreshWorker"]
