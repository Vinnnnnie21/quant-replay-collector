from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

try:
    from market_data.types import DataLoadCancelled, interval_to_ms
    from services.research_data_availability import (
        FormulaDataWindow,
        ResearchDataAvailabilityService,
        ResearchRangeRequest,
    )
    from services.research_data_backfill import (
        ResearchBackfillError,
        ResearchBackfillStatus,
        ResearchDataBackfillService,
    )
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import DataLoadCancelled, interval_to_ms
    from .research_data_availability import (
        FormulaDataWindow,
        ResearchDataAvailabilityService,
        ResearchRangeRequest,
    )
    from .research_data_backfill import (
        ResearchBackfillError,
        ResearchBackfillStatus,
        ResearchDataBackfillService,
    )


_FULL_HISTORY_WINDOW = FormulaDataWindow(
    version="full-history-local-range-v1",
    warmup_bars=0,
    outcome_bars=0,
)


@dataclass(frozen=True)
class FullHistoryBackfillResult:
    total_series: int
    completed_series: int
    downloaded_bars: int
    is_complete: bool
    cancelled: bool


class FullHistoryBackfillError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        result: FullHistoryBackfillResult,
    ) -> None:
        super().__init__(message)
        self.result = result


class FullHistoryAncillaryBackfillService:
    """Backfill ancillary fields over existing local series bounds on demand."""

    def __init__(self, *, storage: Any, network: Any) -> None:
        self._storage = storage
        self._network = network

    def backfill(
        self,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> FullHistoryBackfillResult:
        cancellation_requested = cancelled or (lambda: False)
        series = self._storage.list_kline_series_ranges(
            ancillary_incomplete_only=True
        )
        completed_series = 0
        downloaded_bars = 0
        was_cancelled = False
        for item in series:
            if cancellation_requested():
                was_cancelled = True
                break
            interval = str(item["interval"])
            end_ms = int(item["end_time_utc_ms"])
            availability = ResearchDataAvailabilityService(
                self._storage,
                formula_window=_FULL_HISTORY_WINDOW,
            )
            try:
                result = ResearchDataBackfillService(
                    storage=self._storage,
                    network=self._network,
                    availability=availability,
                ).backfill(
                    ResearchRangeRequest(
                        symbol=str(item["symbol"]),
                        timeframes=(interval,),
                        start_time_utc_ms=int(item["start_time_utc_ms"]),
                        end_time_utc_ms=end_ms,
                        as_of_utc_ms=end_ms + interval_to_ms(interval),
                    ),
                    cancelled=cancellation_requested,
                )
            except DataLoadCancelled:
                was_cancelled = True
                break
            except ResearchBackfillError as exc:
                downloaded_bars += exc.result.downloaded_bars
                partial = FullHistoryBackfillResult(
                    total_series=len(series),
                    completed_series=completed_series,
                    downloaded_bars=downloaded_bars,
                    is_complete=False,
                    cancelled=False,
                )
                raise FullHistoryBackfillError(
                    "Full-history ancillary backfill failed for "
                    f"{item['symbol']} {interval}: {exc}",
                    result=partial,
                ) from exc
            downloaded_bars += result.downloaded_bars
            if result.status is ResearchBackfillStatus.CANCELLED:
                was_cancelled = True
                break
            if result.completeness.is_complete:
                completed_series += 1
        remaining = self._storage.list_kline_series_ranges(
            ancillary_incomplete_only=True
        )
        return FullHistoryBackfillResult(
            total_series=len(series),
            completed_series=completed_series,
            downloaded_bars=downloaded_bars,
            is_complete=not remaining,
            cancelled=was_cancelled,
        )


__all__ = [
    "FullHistoryAncillaryBackfillService",
    "FullHistoryBackfillError",
    "FullHistoryBackfillResult",
]
