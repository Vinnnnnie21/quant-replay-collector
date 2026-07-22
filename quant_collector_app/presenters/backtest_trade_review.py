from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class BacktestKlineSeries:
    x: tuple[float, ...]
    opening: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]
    upmask: tuple[bool, ...]
    bar_indices: tuple[int, ...]

    @property
    def has_data(self) -> bool:
        return bool(self.x)


@dataclass(frozen=True)
class BacktestTradePoint:
    trade_index: int
    entry_bar_index: int
    exit_bar_index: int | None
    entry_x: float
    exit_x: float | None
    entry_price: float
    exit_price: float | None
    side: str
    entry_time: str
    exit_time: str
    return_pct: float | None
    pnl: float | None
    holding_bars: int | None
    exit_reason: str


@dataclass(frozen=True)
class BacktestTradeReviewModel:
    klines: BacktestKlineSeries
    trades: tuple[BacktestTradePoint, ...]


def build_backtest_trade_review_model(
    market_df: pd.DataFrame | None,
    result: Any,
) -> BacktestTradeReviewModel:
    klines = _klines_from_frame(market_df)
    trades = _trades_from_frame(getattr(result, "trades", None), klines)
    return BacktestTradeReviewModel(klines=klines, trades=trades)


def _klines_from_frame(value: pd.DataFrame | None) -> BacktestKlineSeries:
    frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()
    required = ("open", "high", "low", "close", "volume")
    if frame.empty or any(column not in frame.columns for column in required):
        return _empty_klines()

    if "bar_index" in frame.columns:
        bar_indices = pd.to_numeric(frame["bar_index"], errors="coerce")
    else:
        bar_indices = pd.Series(range(len(frame)), index=frame.index, dtype=float)

    opening = pd.to_numeric(frame["open"], errors="coerce")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)

    x_values: list[float] = []
    open_values: list[float] = []
    high_values: list[float] = []
    low_values: list[float] = []
    close_values: list[float] = []
    volume_values: list[float] = []
    upmask: list[bool] = []
    index_values: list[int] = []
    for fallback, (_, row) in enumerate(frame.iterrows()):
        values = (
            opening.iloc[fallback],
            high.iloc[fallback],
            low.iloc[fallback],
            close.iloc[fallback],
        )
        if any(pd.isna(item) for item in values):
            continue
        bar_index = bar_indices.iloc[fallback]
        if pd.isna(bar_index):
            bar_index = fallback
        x = _x_value(row, fallback)
        open_value, high_value, low_value, close_value = (float(item) for item in values)
        x_values.append(x)
        open_values.append(open_value)
        high_values.append(high_value)
        low_values.append(low_value)
        close_values.append(close_value)
        volume_values.append(float(volume.iloc[fallback]))
        upmask.append(close_value >= open_value)
        index_values.append(int(bar_index))

    return BacktestKlineSeries(
        x=tuple(x_values),
        opening=tuple(open_values),
        high=tuple(high_values),
        low=tuple(low_values),
        close=tuple(close_values),
        volume=tuple(volume_values),
        upmask=tuple(upmask),
        bar_indices=tuple(index_values),
    )


def _trades_from_frame(value: Any, klines: BacktestKlineSeries) -> tuple[BacktestTradePoint, ...]:
    frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value or [])
    if frame.empty or not klines.has_data:
        return ()
    by_bar = {bar_index: position for position, bar_index in enumerate(klines.bar_indices)}
    trades: list[BacktestTradePoint] = []
    for trade_index, (_, row) in enumerate(frame.iterrows()):
        entry_bar = _optional_int(row.get("entry_bar_index"))
        if entry_bar is None or entry_bar not in by_bar:
            continue
        exit_bar = _optional_int(row.get("exit_bar_index"))
        entry_position = by_bar[entry_bar]
        exit_position = by_bar.get(exit_bar) if exit_bar is not None else None
        entry_price = _optional_float(row.get("entry_price"))
        exit_price = _optional_float(row.get("exit_price"))
        trades.append(
            BacktestTradePoint(
                trade_index=trade_index,
                entry_bar_index=entry_bar,
                exit_bar_index=exit_bar,
                entry_x=klines.x[entry_position],
                exit_x=klines.x[exit_position] if exit_position is not None else None,
                entry_price=entry_price
                if entry_price is not None
                else klines.close[entry_position],
                exit_price=exit_price,
                side=str(row.get("side") or "LONG").upper(),
                entry_time=str(row.get("entry_time") or ""),
                exit_time=str(row.get("exit_time") or ""),
                return_pct=_optional_float(row.get("return_pct")),
                pnl=_optional_float(row.get("pnl")),
                holding_bars=_optional_int(row.get("holding_bars")),
                exit_reason=str(row.get("exit_reason") or ""),
            )
        )
    return tuple(trades)


def _x_value(row: pd.Series, fallback: int) -> float:
    for column in ("open_time_bjt", "bar_open_time_bjt", "time"):
        if column not in row:
            continue
        timestamp = pd.to_datetime(row.get(column), errors="coerce")
        if pd.notna(timestamp):
            return float(pd.Timestamp(timestamp).timestamp())
    return float(fallback)


def _optional_int(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _empty_klines() -> BacktestKlineSeries:
    return BacktestKlineSeries((), (), (), (), (), (), (), ())


__all__ = [
    "BacktestKlineSeries",
    "BacktestTradePoint",
    "BacktestTradeReviewModel",
    "build_backtest_trade_review_model",
]
