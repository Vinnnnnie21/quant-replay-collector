from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

import pandas as pd

try:
    from market_data.client import MarketDataClient
    from market_data.transforms import iter_kline_storage_rows, normalize_kline_df
    from market_data.types import (
        BINANCE_RAW_COLUMNS,
        DataLoadCancelled,
        interval_to_ms,
        utc_ms_to_bjt,
    )
    from services.research_data_availability import (
        ResearchCompletenessReport,
        ResearchDataAvailabilityService,
        ResearchRangeRequest,
    )
except ImportError:  # pragma: no cover - package import path
    from ..market_data.client import MarketDataClient
    from ..market_data.transforms import (
        iter_kline_storage_rows,
        normalize_kline_df,
    )
    from ..market_data.types import (
        BINANCE_RAW_COLUMNS,
        DataLoadCancelled,
        interval_to_ms,
        utc_ms_to_bjt,
    )
    from .research_data_availability import (
        ResearchCompletenessReport,
        ResearchDataAvailabilityService,
        ResearchRangeRequest,
    )


class ResearchBackfillStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ResearchBackfillResult:
    completeness: ResearchCompletenessReport
    status: ResearchBackfillStatus
    total_chunks: int
    completed_chunks: int
    downloaded_bars: int


@dataclass(frozen=True)
class ResearchBackfillProgress:
    completed_chunks: int
    total_chunks: int
    downloaded_bars: int
    interval: str
    start_time_utc_ms: int
    end_time_utc_ms: int


@dataclass(frozen=True)
class ResearchBackfillChunk:
    interval: str
    start_time_utc_ms: int
    end_time_utc_ms: int


class ResearchBackfillError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        result: ResearchBackfillResult,
    ) -> None:
        super().__init__(message)
        self.result = result


class ResearchDataBackfillService:
    """Fill audited research gaps and commit each successful range."""

    EXCHANGE_PAGE_LIMIT = 1_000

    def __init__(
        self,
        *,
        storage: Any,
        network: Any | None = None,
        availability: ResearchDataAvailabilityService | None = None,
    ) -> None:
        self._storage = storage
        self._network = network or MarketDataClient()
        self._availability = availability or ResearchDataAvailabilityService(
            storage
        )

    def backfill(
        self,
        request: ResearchRangeRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[ResearchBackfillProgress], None] | None = None,
    ) -> ResearchBackfillResult:
        cancellation_requested = cancelled or (lambda: False)
        report_progress = progress or (lambda _event: None)
        before = self._availability.inspect(
            request,
            cancelled=cancellation_requested,
        )
        chunks = self._plan_chunks(before)
        completed_chunks = 0
        downloaded_bars = 0
        for chunk in chunks:
            if cancellation_requested():
                return self._result(
                    request,
                    status=ResearchBackfillStatus.CANCELLED,
                    total_chunks=len(chunks),
                    completed_chunks=completed_chunks,
                    downloaded_bars=downloaded_bars,
                )
            try:
                raw_rows = self._network.download(
                    before.symbol,
                    chunk.interval,
                    utc_ms_to_bjt(chunk.start_time_utc_ms),
                    utc_ms_to_bjt(chunk.end_time_utc_ms),
                    cancelled=cancellation_requested,
                )
                frame, _quality = normalize_kline_df(
                    pd.DataFrame(raw_rows, columns=BINANCE_RAW_COLUMNS),
                    utc_ms_to_bjt(chunk.start_time_utc_ms),
                    utc_ms_to_bjt(chunk.end_time_utc_ms),
                    chunk.interval,
                    "Binance Futures API",
                )
                self._storage.upsert_klines(
                    iter_kline_storage_rows(
                        frame,
                        symbol=before.symbol,
                        interval=chunk.interval,
                        source="research_backfill",
                    )
                )
            except DataLoadCancelled:
                return self._result(
                    request,
                    status=ResearchBackfillStatus.CANCELLED,
                    total_chunks=len(chunks),
                    completed_chunks=completed_chunks,
                    downloaded_bars=downloaded_bars,
                )
            except Exception as exc:
                result = ResearchBackfillResult(
                    completeness=self._availability.inspect(request),
                    status=ResearchBackfillStatus.PARTIAL,
                    total_chunks=len(chunks),
                    completed_chunks=completed_chunks,
                    downloaded_bars=downloaded_bars,
                )
                raise ResearchBackfillError(
                    f"{type(exc).__name__}: {exc}",
                    result=result,
                ) from exc
            completed_chunks += 1
            downloaded_bars += len(frame)
            report_progress(
                ResearchBackfillProgress(
                    completed_chunks=completed_chunks,
                    total_chunks=len(chunks),
                    downloaded_bars=downloaded_bars,
                    interval=chunk.interval,
                    start_time_utc_ms=chunk.start_time_utc_ms,
                    end_time_utc_ms=chunk.end_time_utc_ms,
                )
            )
        result = self._result(
            request,
            status=ResearchBackfillStatus.COMPLETE,
            total_chunks=len(chunks),
            completed_chunks=completed_chunks,
            downloaded_bars=downloaded_bars,
        )
        if not result.completeness.is_complete:
            return ResearchBackfillResult(
                completeness=result.completeness,
                status=ResearchBackfillStatus.PARTIAL,
                total_chunks=result.total_chunks,
                completed_chunks=result.completed_chunks,
                downloaded_bars=result.downloaded_bars,
            )
        return result

    def _result(
        self,
        request: ResearchRangeRequest,
        *,
        status: ResearchBackfillStatus,
        total_chunks: int,
        completed_chunks: int,
        downloaded_bars: int,
    ) -> ResearchBackfillResult:
        return ResearchBackfillResult(
            completeness=self._availability.inspect(request),
            status=status,
            total_chunks=total_chunks,
            completed_chunks=completed_chunks,
            downloaded_bars=downloaded_bars,
        )

    @classmethod
    def _plan_chunks(
        cls,
        completeness: ResearchCompletenessReport,
    ) -> tuple[ResearchBackfillChunk, ...]:
        chunks: list[ResearchBackfillChunk] = []
        seen: set[tuple[str, int, int]] = set()
        for timeframe in completeness.timeframes:
            step_ms = interval_to_ms(timeframe.interval)
            chunk_span_ms = (cls.EXCHANGE_PAGE_LIMIT - 1) * step_ms
            for missing_range in timeframe.missing_ranges:
                start_ms = missing_range.start_time_utc_ms
                while start_ms <= missing_range.end_time_utc_ms:
                    end_ms = min(
                        start_ms + chunk_span_ms,
                        missing_range.end_time_utc_ms,
                    )
                    key = (timeframe.interval, start_ms, end_ms)
                    if key not in seen:
                        chunks.append(
                            ResearchBackfillChunk(
                                interval=timeframe.interval,
                                start_time_utc_ms=start_ms,
                                end_time_utc_ms=end_ms,
                            )
                        )
                        seen.add(key)
                    start_ms = end_ms + step_ms
        return tuple(chunks)


__all__ = [
    "ResearchBackfillChunk",
    "ResearchBackfillError",
    "ResearchBackfillProgress",
    "ResearchBackfillResult",
    "ResearchBackfillStatus",
    "ResearchDataBackfillService",
]
