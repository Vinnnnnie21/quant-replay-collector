from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

try:
    from market_data.types import interval_to_ms
    from research.entry_blind_review import (
        BlindedKline,
        BlindedTimeframeChart,
    )
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms
    from ..research.entry_blind_review import (
        BlindedKline,
        BlindedTimeframeChart,
    )


DEFAULT_CHART_LOOKBACK_BARS = 200
DEFAULT_REVEAL_BARS = 40


@dataclass(frozen=True, slots=True)
class ActualActionTiming:
    decision_time_utc: datetime
    observed_time_utc: datetime | None
    timing_approximate: bool


def actual_action_timing(
    trade_event: Mapping[str, Any],
    trade: Mapping[str, Any] | None,
    *,
    trade_bar_time_field: str,
    trade_real_time_field: str,
) -> ActualActionTiming:
    """Separate replay-market cutoff time from the wall-clock audit time."""

    trade = trade or {}
    market_value = (
        trade_event.get("bar_open_time_bjt")
        or trade.get(trade_bar_time_field)
    )
    observed_value = (
        trade_event.get("real_key_time_bjt")
        or trade.get(trade_real_time_field)
    )
    observed = _aware_utc(observed_value) if observed_value else None
    if market_value:
        return ActualActionTiming(
            decision_time_utc=_aware_utc(market_value),
            observed_time_utc=observed,
            timing_approximate=True,
        )
    if observed is not None:
        return ActualActionTiming(
            decision_time_utc=observed,
            observed_time_utc=observed,
            timing_approximate=False,
        )
    raise ValueError("Actual trade event has no usable action time")


def _aware_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Decision times must include an explicit timezone")
    return parsed.astimezone(UTC)


class BlindReviewKlineStorage(Protocol):
    def fetch_klines_for_range(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_utc_ms: int,
        end_time_utc_ms: int,
    ) -> list[dict[str, Any]]: ...


class BlindReviewMarketData:
    """Own the closed-bar boundary shared by entry and exit blind review."""

    def __init__(self, storage: BlindReviewKlineStorage) -> None:
        self._storage = storage

    def blinded_charts(
        self,
        row: Mapping[str, Any],
    ) -> tuple[BlindedTimeframeChart, ...]:
        return self._charts(row, reveal_future=False)

    def future_charts(
        self,
        row: Mapping[str, Any],
    ) -> tuple[BlindedTimeframeChart, ...]:
        return self._charts(row, reveal_future=True)

    def decision_bar_boundary(
        self,
        *,
        symbol: str,
        interval: str,
        decision_time_utc_ms: int,
    ) -> tuple[int, int]:
        duration = interval_to_ms(interval)
        rows = self._storage.fetch_klines_for_range(
            symbol=symbol,
            interval=interval,
            start_time_utc_ms=max(
                0,
                decision_time_utc_ms - duration * 3,
            ),
            end_time_utc_ms=decision_time_utc_ms,
        )
        closed = [
            row
            for row in rows
            if row.get("close_time_utc_ms") is not None
            and int(row["close_time_utc_ms"]) <= decision_time_utc_ms
        ]
        if closed:
            last = max(
                closed,
                key=lambda item: int(item["close_time_utc_ms"]),
            )
            return (
                int(last["open_time_utc_ms"]),
                int(last["close_time_utc_ms"]),
            )
        cutoff = decision_time_utc_ms - decision_time_utc_ms % duration
        return cutoff - duration, cutoff

    def _charts(
        self,
        row: Mapping[str, Any],
        *,
        reveal_future: bool,
    ) -> tuple[BlindedTimeframeChart, ...]:
        cutoff = int(row["decision_cutoff_utc_ms"])
        charts = []
        for interval in (
            str(row["decision_timeframe"]),
            str(row["context_timeframe_one"]),
            str(row["context_timeframe_two"]),
        ):
            duration = interval_to_ms(interval)
            start = (
                max(0, cutoff - duration)
                if reveal_future
                else max(0, cutoff - duration * DEFAULT_CHART_LOOKBACK_BARS)
            )
            end = (
                cutoff + duration * DEFAULT_REVEAL_BARS
                if reveal_future
                else cutoff - 1
            )
            charts.append(
                BlindedTimeframeChart(
                    interval=interval,
                    cutoff_time_utc_ms=cutoff,
                    bars=self._bars(
                        symbol=str(row["symbol"]),
                        interval=interval,
                        start_time_utc_ms=start,
                        end_time_utc_ms=end,
                        cutoff_time_utc_ms=cutoff,
                        reveal_future=reveal_future,
                    ),
                )
            )
        return tuple(charts)

    def _bars(
        self,
        *,
        symbol: str,
        interval: str,
        start_time_utc_ms: int,
        end_time_utc_ms: int,
        cutoff_time_utc_ms: int,
        reveal_future: bool,
    ) -> tuple[BlindedKline, ...]:
        duration = interval_to_ms(interval)
        rows = self._storage.fetch_klines_for_range(
            symbol=symbol,
            interval=interval,
            start_time_utc_ms=start_time_utc_ms,
            end_time_utc_ms=end_time_utc_ms,
        )
        bars = []
        for row in rows:
            open_time = int(row["open_time_utc_ms"])
            raw_close_time = row.get("close_time_utc_ms")
            close_time = (
                int(raw_close_time)
                if raw_close_time is not None
                else open_time + duration
            )
            if (close_time > cutoff_time_utc_ms) is not reveal_future:
                continue
            bars.append(
                BlindedKline(
                    open_time_utc_ms=open_time,
                    close_time_utc_ms=close_time,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        return tuple(bars)


__all__ = [
    "ActualActionTiming",
    "BlindReviewKlineStorage",
    "BlindReviewMarketData",
    "DEFAULT_CHART_LOOKBACK_BARS",
    "DEFAULT_REVEAL_BARS",
    "actual_action_timing",
]
