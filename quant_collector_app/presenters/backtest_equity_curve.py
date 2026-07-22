from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class EquityCurveSeries:
    x: tuple[float, ...]
    y: tuple[float, ...]

    @property
    def has_data(self) -> bool:
        return bool(self.x and self.y)


@dataclass(frozen=True)
class EquityCurveEntryPoint:
    trade_index: int
    x: float
    y: float


@dataclass(frozen=True)
class BacktestEquityCurveModel:
    strategy: EquityCurveSeries
    random_baseline: EquityCurveSeries
    initial_equity: float | None
    random_baseline_status: str
    strategy_entries: tuple[EquityCurveEntryPoint, ...] = ()


def build_backtest_equity_curve_model(
    result: Any,
    *,
    initial_equity: float | None = None,
) -> BacktestEquityCurveModel:
    strategy = _series_from_frame(getattr(result, "equity_curve", None))
    random_status = _random_status(getattr(result, "random_baseline_summary", None))
    random_baseline = (
        _series_from_frame(getattr(result, "random_baseline_equity_curve", None))
        if random_status == "ready"
        else EquityCurveSeries((), ())
    )
    return BacktestEquityCurveModel(
        strategy=strategy,
        random_baseline=random_baseline,
        initial_equity=_initial_equity(result, strategy, initial_equity),
        random_baseline_status=random_status,
        strategy_entries=_entry_points_from_result(result, strategy),
    )


def _series_from_frame(value: Any) -> EquityCurveSeries:
    frame = value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame(value or [])
    if frame.empty:
        return EquityCurveSeries((), ())
    y_source = "equity" if "equity" in frame.columns else "equity_after"
    if y_source not in frame.columns:
        return EquityCurveSeries((), ())
    y = pd.to_numeric(frame[y_source], errors="coerce")
    x_values: list[float] = []
    y_values: list[float] = []
    for fallback, (_, row) in enumerate(frame.iterrows()):
        y_value = y.iloc[fallback]
        if pd.isna(y_value):
            continue
        x_values.append(_x_value(row, fallback))
        y_values.append(float(y_value))
    return EquityCurveSeries(tuple(x_values), tuple(y_values))


def _x_value(row: pd.Series, fallback: int) -> float:
    for column in ("time", "bar_open_time_bjt", "open_time_bjt"):
        if column not in row:
            continue
        timestamp = pd.to_datetime(row.get(column), errors="coerce")
        if pd.notna(timestamp):
            return float(pd.Timestamp(timestamp).timestamp())
    try:
        return float(row.get("bar_index"))
    except (TypeError, ValueError):
        return float(fallback)


def _initial_equity(
    result: Any,
    strategy: EquityCurveSeries,
    fallback: float | None,
) -> float | None:
    summary = getattr(result, "summary", None)
    if isinstance(summary, dict) and summary.get("initial_equity") is not None:
        try:
            return float(summary["initial_equity"])
        except (TypeError, ValueError):
            pass
    config = getattr(result, "config", None)
    if isinstance(config, dict) and config.get("initial_equity") is not None:
        try:
            return float(config["initial_equity"])
        except (TypeError, ValueError):
            pass
    if fallback is not None:
        return float(fallback)
    return strategy.y[0] if strategy.y else None


def _random_status(summary: Any) -> str:
    if isinstance(summary, dict):
        return str(summary.get("status") or "").lower()
    return ""


def _entry_points_from_result(
    result: Any,
    strategy: EquityCurveSeries,
) -> tuple[EquityCurveEntryPoint, ...]:
    trades = getattr(result, "trades", None)
    equity = getattr(result, "equity_curve", None)
    trade_frame = trades.copy() if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades or [])
    equity_frame = equity.copy() if isinstance(equity, pd.DataFrame) else pd.DataFrame(equity or [])
    if trade_frame.empty or equity_frame.empty:
        return ()
    y_source = "equity" if "equity" in equity_frame.columns else "equity_after"
    if y_source not in equity_frame.columns:
        return ()
    by_bar: dict[int, tuple[float, float]] = {}
    for fallback, (_, row) in enumerate(equity_frame.iterrows()):
        try:
            bar_index = int(row.get("bar_index"))
            y_value = float(row.get(y_source))
        except (TypeError, ValueError):
            continue
        if pd.isna(y_value):
            continue
        by_bar[bar_index] = (_x_value(row, fallback), y_value)

    points: list[EquityCurveEntryPoint] = []
    for trade_index, (_, row) in enumerate(trade_frame.iterrows()):
        try:
            entry_bar = int(row.get("entry_bar_index"))
        except (TypeError, ValueError):
            continue
        if entry_bar in by_bar:
            x_value, y_value = by_bar[entry_bar]
        elif trade_index < len(strategy.x) and trade_index < len(strategy.y):
            x_value, y_value = strategy.x[trade_index], strategy.y[trade_index]
        else:
            continue
        points.append(EquityCurveEntryPoint(trade_index, x_value, y_value))
    return tuple(points)


__all__ = [
    "BacktestEquityCurveModel",
    "EquityCurveEntryPoint",
    "EquityCurveSeries",
    "build_backtest_equity_curve_model",
]
