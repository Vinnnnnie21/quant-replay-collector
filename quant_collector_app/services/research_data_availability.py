from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping

try:
    from market_data.types import (
        KLINE_ANCILLARY_COLUMNS,
        DataLoadCancelled,
        interval_to_ms,
        normalize_interval,
        normalize_symbol,
    )
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import (
        KLINE_ANCILLARY_COLUMNS,
        DataLoadCancelled,
        interval_to_ms,
        normalize_interval,
        normalize_symbol,
    )


_WEEK_ALIGNMENT_UTC_MS = 4 * 24 * 60 * 60 * 1_000


def _alignment_offset_ms(interval: str) -> int:
    return _WEEK_ALIGNMENT_UTC_MS if interval == "1w" else 0


def _floor_open_time(value_ms: int, interval: str) -> int:
    step_ms = interval_to_ms(interval)
    offset_ms = _alignment_offset_ms(interval)
    return ((int(value_ms) - offset_ms) // step_ms) * step_ms + offset_ms


def _ceil_open_time(value_ms: int, interval: str) -> int:
    floor_ms = _floor_open_time(value_ms, interval)
    return (
        floor_ms
        if floor_ms == int(value_ms)
        else floor_ms + interval_to_ms(interval)
    )


@dataclass(frozen=True)
class FormulaDataWindow:
    version: str
    warmup_bars: int
    outcome_bars: int

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("Formula data-window version must be non-empty")
        if self.warmup_bars < 0 or self.outcome_bars < 0:
            raise ValueError("Formula data-window bars must be non-negative")


V1_6_FORMULA_DATA_WINDOW = FormulaDataWindow(
    version="decision-research-v1.6",
    warmup_bars=60,
    outcome_bars=20,
)


@dataclass(frozen=True)
class ResearchRangeRequest:
    symbol: str
    timeframes: tuple[str, ...]
    start_time_utc_ms: int
    end_time_utc_ms: int
    as_of_utc_ms: int

    def __post_init__(self) -> None:
        if len(self.timeframes) not in {1, 3}:
            raise ValueError(
                "Completeness requires one maintenance timeframe "
                "or three research timeframes"
            )
        if self.end_time_utc_ms < self.start_time_utc_ms:
            raise ValueError("Research range ends before it starts")


@dataclass(frozen=True)
class MissingKlineRange:
    start_time_utc_ms: int
    end_time_utc_ms: int
    missing_fields: tuple[str, ...]


@dataclass(frozen=True)
class TimeframeCompleteness:
    interval: str
    required_start_time_utc_ms: int
    required_end_time_utc_ms: int
    expected_bars: int
    present_bars: int
    missing_bar_count: int
    missing_field_counts: Mapping[str, int]
    missing_ranges: tuple[MissingKlineRange, ...]
    coverage_ratio: float

    @property
    def is_complete(self) -> bool:
        return not self.missing_ranges


@dataclass(frozen=True)
class ResearchCompletenessReport:
    formula_version: str
    symbol: str
    research_start_time_utc_ms: int
    research_end_time_utc_ms: int
    timeframes: tuple[TimeframeCompleteness, ...]

    @property
    def is_complete(self) -> bool:
        return all(item.is_complete for item in self.timeframes)


class ResearchOperation(str, Enum):
    MANUAL_REVIEW = "manual_review"
    CANDIDATE_GENERATION = "candidate_generation"
    MODEL_TRAINING = "model_training"
    FORMAL_MATCHING = "formal_matching"


@dataclass(frozen=True)
class ResearchDataDeficit:
    interval: str
    missing_bar_count: int
    missing_field_counts: Mapping[str, int]
    missing_ranges: tuple[MissingKlineRange, ...]


class ResearchDataIncompleteError(RuntimeError):
    def __init__(
        self,
        operation: ResearchOperation,
        deficits: tuple[ResearchDataDeficit, ...],
    ) -> None:
        super().__init__(
            f"Research data is incomplete for {operation.value}: "
            + ", ".join(item.interval for item in deficits)
        )
        self.operation = operation
        self.deficits = deficits


def require_complete_research_data(
    operation: ResearchOperation,
    report: ResearchCompletenessReport,
) -> None:
    if operation is ResearchOperation.MANUAL_REVIEW:
        return
    deficits = tuple(
        ResearchDataDeficit(
            interval=timeframe.interval,
            missing_bar_count=timeframe.missing_bar_count,
            missing_field_counts=MappingProxyType(
                {
                    field: count
                    for field, count in timeframe.missing_field_counts.items()
                    if count
                }
            ),
            missing_ranges=timeframe.missing_ranges,
        )
        for timeframe in report.timeframes
        if not timeframe.is_complete
    )
    if deficits:
        raise ResearchDataIncompleteError(operation, deficits)


class ResearchDataAvailabilityService:
    """Audit the exact closed K-line grid required by decision research."""

    AUDIT_BATCH_BARS = 50_000

    def __init__(
        self,
        storage: Any,
        *,
        formula_window: FormulaDataWindow = V1_6_FORMULA_DATA_WINDOW,
    ) -> None:
        self._storage = storage
        self._formula_window = formula_window

    def inspect(
        self,
        request: ResearchRangeRequest,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> ResearchCompletenessReport:
        cancellation_requested = cancelled or (lambda: False)
        if cancellation_requested():
            raise DataLoadCancelled("Research completeness audit cancelled.")
        symbol = normalize_symbol(request.symbol)
        timeframes = tuple(
            normalize_interval(interval) for interval in request.timeframes
        )
        reports = []
        for index, interval in enumerate(timeframes):
            if cancellation_requested():
                raise DataLoadCancelled(
                    "Research completeness audit cancelled."
                )
            reports.append(
                self._inspect_timeframe(
                    symbol=symbol,
                    interval=interval,
                    request=request,
                    decision_timeframe=index == 0,
                    cancelled=cancellation_requested,
                )
            )
        return ResearchCompletenessReport(
            formula_version=self._formula_window.version,
            symbol=symbol,
            research_start_time_utc_ms=int(request.start_time_utc_ms),
            research_end_time_utc_ms=int(request.end_time_utc_ms),
            timeframes=tuple(reports),
        )

    def _inspect_timeframe(
        self,
        *,
        symbol: str,
        interval: str,
        request: ResearchRangeRequest,
        decision_timeframe: bool,
        cancelled: Callable[[], bool],
    ) -> TimeframeCompleteness:
        step_ms = interval_to_ms(interval)
        required_start_ms = (
            _ceil_open_time(request.start_time_utc_ms, interval)
            - self._formula_window.warmup_bars * step_ms
        )
        requested_end_ms = (
            _floor_open_time(request.end_time_utc_ms, interval)
            + (
                self._formula_window.outcome_bars * step_ms
                if decision_timeframe
                else 0
            )
        )
        last_closed_open_ms = (
            _floor_open_time(request.as_of_utc_ms, interval) - step_ms
        )
        required_end_ms = min(requested_end_ms, last_closed_open_ms)
        if required_end_ms < required_start_ms:
            return TimeframeCompleteness(
                interval=interval,
                required_start_time_utc_ms=required_start_ms,
                required_end_time_utc_ms=required_end_ms,
                expected_bars=0,
                present_bars=0,
                missing_bar_count=0,
                missing_field_counts=MappingProxyType(
                    {field: 0 for field in KLINE_ANCILLARY_COLUMNS}
                ),
                missing_ranges=(),
                coverage_ratio=1.0,
            )

        expected_bars = (
            (required_end_ms - required_start_ms) // step_ms
        ) + 1
        present_bars = 0
        complete_bars = 0
        missing_bar_count = 0
        missing_field_counts = {
            field: 0 for field in KLINE_ANCILLARY_COLUMNS
        }
        missing_ranges: list[MissingKlineRange] = []
        range_start_ms: int | None = None
        previous_missing_ms: int | None = None
        range_fields: set[str] = set()
        batch_span_ms = (self.AUDIT_BATCH_BARS - 1) * step_ms
        batch_start_ms = required_start_ms
        while batch_start_ms <= required_end_ms:
            if cancelled():
                raise DataLoadCancelled(
                    "Research completeness audit cancelled."
                )
            batch_end_ms = min(
                batch_start_ms + batch_span_ms,
                required_end_ms,
            )
            stored_rows = (
                self._storage.fetch_kline_ancillary_rows_for_range(
                    symbol=symbol,
                    interval=interval,
                    start_time_utc_ms=batch_start_ms,
                    end_time_utc_ms=batch_end_ms,
                    cancelled=cancelled,
                )
            )
            if cancelled():
                raise DataLoadCancelled(
                    "Research completeness audit cancelled."
                )
            rows_by_open = {
                int(row["open_time_utc_ms"]): row
                for row in stored_rows
            }
            for open_time_ms in range(
                batch_start_ms,
                batch_end_ms + 1,
                step_ms,
            ):
                row = rows_by_open.get(open_time_ms)
                if row is None:
                    missing_bar_count += 1
                    missing_fields = KLINE_ANCILLARY_COLUMNS
                else:
                    present_bars += 1
                    missing_fields = tuple(
                        field
                        for field in KLINE_ANCILLARY_COLUMNS
                        if row.get(field) is None
                    )
                if missing_fields:
                    for field in missing_fields:
                        missing_field_counts[field] += 1
                    if range_start_ms is None:
                        range_start_ms = open_time_ms
                        range_fields = set(missing_fields)
                    else:
                        range_fields.update(missing_fields)
                    previous_missing_ms = open_time_ms
                else:
                    complete_bars += 1
                    if range_start_ms is not None:
                        missing_ranges.append(
                            self._missing_range(
                                range_start_ms,
                                previous_missing_ms,
                                range_fields,
                            )
                        )
                        range_start_ms = None
                        previous_missing_ms = None
                        range_fields = set()
            batch_start_ms = batch_end_ms + step_ms
        if range_start_ms is not None:
            missing_ranges.append(
                self._missing_range(
                    range_start_ms,
                    previous_missing_ms,
                    range_fields,
                )
            )

        return TimeframeCompleteness(
            interval=interval,
            required_start_time_utc_ms=required_start_ms,
            required_end_time_utc_ms=required_end_ms,
            expected_bars=expected_bars,
            present_bars=present_bars,
            missing_bar_count=missing_bar_count,
            missing_field_counts=MappingProxyType(missing_field_counts),
            missing_ranges=tuple(missing_ranges),
            coverage_ratio=complete_bars / expected_bars,
        )

    @staticmethod
    def _missing_range(
        start_time_utc_ms: int,
        end_time_utc_ms: int | None,
        fields: set[str],
    ) -> MissingKlineRange:
        return MissingKlineRange(
            start_time_utc_ms=start_time_utc_ms,
            end_time_utc_ms=(
                start_time_utc_ms
                if end_time_utc_ms is None
                else end_time_utc_ms
            ),
            missing_fields=tuple(
                field
                for field in KLINE_ANCILLARY_COLUMNS
                if field in fields
            ),
        )


__all__ = [
    "FormulaDataWindow",
    "MissingKlineRange",
    "ResearchCompletenessReport",
    "ResearchDataDeficit",
    "ResearchDataIncompleteError",
    "ResearchDataAvailabilityService",
    "ResearchOperation",
    "ResearchRangeRequest",
    "TimeframeCompleteness",
    "V1_6_FORMULA_DATA_WINDOW",
    "require_complete_research_data",
]
