from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from PySide6 import QtCore

try:
    from accounting import EquityCurveCancelled, build_continuous_equity_curve
    from cancellation import CancellationToken
    from market_data.cache import read_cached_kline_range
    from services.analysis_refresh import build_performance_workspace_payload
    from storage import StorageManager
except ImportError:  # pragma: no cover - package import path
    from ..accounting import EquityCurveCancelled, build_continuous_equity_curve
    from ..cancellation import CancellationToken
    from ..market_data.cache import read_cached_kline_range
    from ..services.analysis_refresh import build_performance_workspace_payload
    from ..storage import StorageManager


BJT = timezone(timedelta(hours=8))


def _session_market_range_utc_ms(session: dict[str, Any]) -> tuple[int, int]:
    start_text = str(session.get("start_date_bjt") or "").strip()
    end_text = str(session.get("end_date_bjt") or "").strip()
    if not start_text or not end_text:
        raise ValueError("Historical session is missing its saved market-data range")
    start_date = datetime.fromisoformat(start_text).date()
    end_date = datetime.fromisoformat(end_text).date()
    start = datetime.combine(start_date, time.min, tzinfo=BJT)
    end_exclusive = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=BJT,
    )
    return (
        int(start.astimezone(timezone.utc).timestamp() * 1_000),
        int(end_exclusive.astimezone(timezone.utc).timestamp() * 1_000) - 1,
    )


def _market_time(row: dict[str, Any]) -> str | None:
    value = row.get("open_time_bjt")
    if value:
        return str(value)
    utc_ms = row.get("open_time_utc_ms")
    if utc_ms is None:
        return None
    return datetime.fromtimestamp(
        int(utc_ms) / 1_000,
        tz=timezone.utc,
    ).astimezone(BJT).isoformat()


def _required_market_row_count(
    session: dict[str, Any],
    trades: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> int:
    indices = [session.get("cursor_bar_index")]
    for trade in trades:
        indices.extend((trade.get("entry_bar_index"), trade.get("exit_bar_index")))
    parsed = []
    for value in indices:
        try:
            parsed.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(parsed, default=-1) + 1


def _merge_market_rows(
    primary_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_time: dict[int, dict[str, Any]] = {}
    for rows in (fallback_rows, primary_rows):
        for row in rows:
            try:
                utc_ms = int(row.get("open_time_utc_ms"))
            except (TypeError, ValueError):
                continue
            rows_by_time[utc_ms] = {
                "open_time_utc_ms": utc_ms,
                "open_time_bjt": row.get("open_time_bjt"),
                "close": row.get("close"),
            }
    return [
        {"bar_index": index, **rows_by_time[utc_ms]}
        for index, utc_ms in enumerate(sorted(rows_by_time))
    ]


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
            symbol = str(session.get("symbol") or "").strip().upper()
            interval = str(session.get("interval") or "").strip()
            start_time_utc_ms, end_time_utc_ms = _session_market_range_utc_ms(session)
            market_rows = storage.fetch_klines_for_range(
                symbol=symbol,
                interval=interval,
                start_time_utc_ms=start_time_utc_ms,
                end_time_utc_ms=end_time_utc_ms,
                cancelled=self.cancellation_token.is_requested,
            )
            if self.cancellation_token.is_requested():
                self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                return
            realized_market_rows = []
            for index, row in enumerate(market_rows):
                if index % 1_024 == 0 and self.cancellation_token.is_requested():
                    self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                    return
                realized_market_rows.append(dict(row))
            market_rows = realized_market_rows
            if self.cancellation_token.is_requested():
                self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                return
            required_rows = max(1, _required_market_row_count(session, trades))
            if len(market_rows) < required_rows:
                cached_rows = read_cached_kline_range(
                    self._cache_dir,
                    symbol=symbol,
                    interval=interval,
                    start_time_utc_ms=start_time_utc_ms,
                    end_time_utc_ms=end_time_utc_ms,
                    minimum_rows=required_rows,
                    cancelled=self.cancellation_token.is_requested,
                )
                if self.cancellation_token.is_requested():
                    self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                    return
                market_rows = (
                    _merge_market_rows(market_rows, cached_rows)
                    if market_rows
                    else cached_rows
                )
            if len(market_rows) < required_rows:
                self.finished.emit(
                    HistoricalPerformanceResult(
                        str(request.session_id),
                        revision,
                        None,
                        "performance.curve_missing_market_data",
                    )
                )
                return
            normalized_market_rows = []
            for index, row in enumerate(market_rows):
                if index % 1_024 == 0 and self.cancellation_token.is_requested():
                    self.cancelled.emit(HistoricalPerformanceCancellation(revision))
                    return
                normalized_market_rows.append(
                    {
                        **row,
                        "bar_index": index,
                        "open_time_bjt": _market_time(row),
                    }
                )
            market_rows = normalized_market_rows
            equity_rows = build_continuous_equity_curve(
                market_rows,
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
