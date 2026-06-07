from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

try:
    from ..market_data import interval_to_ms
except ImportError:  # Compatibility with the project's legacy top-level imports.
    from market_data import interval_to_ms


@dataclass(frozen=True)
class BacktestDateRange:
    symbol: str
    interval: str
    start: Any
    end: Any

    def validate(self) -> BacktestDateRange:
        if not str(self.symbol or "").strip():
            raise ValueError("symbol must not be empty")
        if not str(self.interval or "").strip():
            raise ValueError("interval must not be empty")
        interval_to_ms(self.interval)
        start = normalize_market_timestamp(self.start)
        end = normalize_market_timestamp(self.end)
        if start >= end:
            raise ValueError("start must be earlier than end")
        return self

    @property
    def normalized_start(self) -> pd.Timestamp:
        return normalize_market_timestamp(self.start)

    @property
    def normalized_end(self) -> pd.Timestamp:
        return normalize_market_timestamp(self.end)


@dataclass(frozen=True)
class BacktestDateRangeResult:
    status: str
    data: pd.DataFrame
    message: str = ""


def normalize_market_timestamp(value: Any) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid market timestamp: {value!r}") from exc
    if pd.isna(timestamp):
        raise ValueError(f"invalid market timestamp: {value!r}")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("Asia/Shanghai")
    return timestamp.tz_convert("UTC")


def slice_backtest_date_range(
    df: pd.DataFrame,
    date_range: BacktestDateRange,
    *,
    minimum_bars: int = 2,
) -> BacktestDateRangeResult:
    """Select a reproducible half-open ``[start, end)`` K-line range.

    This function does not load data. A coverage miss is returned explicitly so
    a higher-level service can decide whether to call the existing market-data
    loader without mutating replay state.
    """
    date_range.validate()
    if isinstance(minimum_bars, bool) or int(minimum_bars) <= 0:
        raise ValueError("minimum_bars must be a positive integer")
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError("no K-line data is available")
    if "open_time_bjt" not in df.columns:
        raise ValueError("K-line data requires open_time_bjt")

    data = df.copy()
    data["_normalized_open_time"] = data["open_time_bjt"].map(_normalize_optional_timestamp)
    data = data[data["_normalized_open_time"].notna()].sort_values("_normalized_open_time", kind="stable")
    if data.empty:
        raise ValueError("no K-line data is available")

    start, end = date_range.normalized_start, date_range.normalized_end
    available_start = data["_normalized_open_time"].iloc[0]
    available_end = data["_normalized_open_time"].iloc[-1] + pd.Timedelta(
        milliseconds=interval_to_ms(date_range.interval)
    )
    if available_start > start or available_end < end:
        return BacktestDateRangeResult(
            status="needs_market_data",
            data=pd.DataFrame(columns=df.columns),
            message="current K-line data does not cover the requested backtest date range",
        )

    selected = data[(data["_normalized_open_time"] >= start) & (data["_normalized_open_time"] < end)].copy()
    selected = selected.drop(columns=["_normalized_open_time"]).reset_index(drop=True)
    if selected.empty:
        raise ValueError("no K-line data exists in the requested backtest date range")
    if len(selected) < int(minimum_bars):
        raise ValueError(
            f"insufficient bars in requested backtest date range: {len(selected)} < {int(minimum_bars)}"
        )
    return BacktestDateRangeResult(status="ready", data=selected)


def _normalize_optional_timestamp(value: Any) -> pd.Timestamp | None:
    try:
        return normalize_market_timestamp(value)
    except ValueError:
        return None


__all__ = [
    "BacktestDateRange",
    "BacktestDateRangeResult",
    "normalize_market_timestamp",
    "slice_backtest_date_range",
]
