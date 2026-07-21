from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable, Iterable

try:
    from market_data.cache import read_cached_kline_range
except ImportError:  # pragma: no cover - package import path
    from ..market_data.cache import read_cached_kline_range


BJT = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class SessionPerformanceMarketData:
    """Replay-time market rows aligned to the session's saved bar indices."""

    rows: tuple[dict[str, Any], ...]
    cursor: int


def _session_market_range_utc_ms(session: dict[str, Any]) -> tuple[int, int]:
    start_text = str(session.get("start_date_bjt") or "").strip()
    end_text = str(session.get("end_date_bjt") or "").strip()
    if not start_text or not end_text:
        raise ValueError("Performance session is missing its saved market-data range")
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
    trades: Iterable[dict[str, Any]],
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
    primary_rows: Iterable[dict[str, Any]],
    fallback_rows: Iterable[dict[str, Any]],
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


def load_session_performance_market_data(
    storage: Any,
    session: dict[str, Any],
    trades: Iterable[dict[str, Any]],
    *,
    cache_dir: str | Path,
    cancelled: Callable[[], bool] | None = None,
) -> SessionPerformanceMarketData | None:
    """Load enough local K-lines to position a session's equity and trade events."""

    cancelled = cancelled or (lambda: False)
    trade_rows = tuple(trades)
    symbol = str(session.get("symbol") or "").strip().upper()
    interval = str(session.get("interval") or "").strip()
    if not symbol or not interval:
        raise ValueError("Performance session is missing symbol or interval")
    start_time_utc_ms, end_time_utc_ms = _session_market_range_utc_ms(session)
    market_rows = storage.fetch_klines_for_range(
        symbol=symbol,
        interval=interval,
        start_time_utc_ms=start_time_utc_ms,
        end_time_utc_ms=end_time_utc_ms,
        cancelled=cancelled,
    )
    realized_rows: list[dict[str, Any]] = []
    for index, row in enumerate(market_rows):
        if index % 1_024 == 0 and cancelled():
            return None
        realized_rows.append(dict(row))
    if cancelled():
        return None
    required_rows = max(1, _required_market_row_count(session, trade_rows))
    if len(realized_rows) < required_rows:
        cached_rows = read_cached_kline_range(
            cache_dir,
            symbol=symbol,
            interval=interval,
            start_time_utc_ms=start_time_utc_ms,
            end_time_utc_ms=end_time_utc_ms,
            minimum_rows=required_rows,
            cancelled=cancelled,
        )
        if cancelled():
            return None
        realized_rows = (
            _merge_market_rows(realized_rows, cached_rows)
            if realized_rows
            else cached_rows
        )
    if len(realized_rows) < required_rows:
        return None
    normalized_rows = tuple(
        {
            **row,
            "bar_index": index,
            "open_time_bjt": _market_time(row),
        }
        for index, row in enumerate(realized_rows)
    )
    try:
        saved_cursor = int(session.get("cursor_bar_index"))
    except (TypeError, ValueError):
        saved_cursor = len(normalized_rows) - 1
    cursor = max(0, min(len(normalized_rows) - 1, saved_cursor))
    return SessionPerformanceMarketData(normalized_rows, cursor)


__all__ = [
    "SessionPerformanceMarketData",
    "load_session_performance_market_data",
]
