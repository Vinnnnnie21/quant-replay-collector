from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

try:
    from presenters.backtest_presenter import SUMMARY_FIELDS
except ImportError:  # pragma: no cover - package import path
    from .backtest_presenter import SUMMARY_FIELDS


SIGNED_PROFIT_FIELDS = frozenset(
    {
        "return_pct",
        "pnl",
        "avg_return",
        "median_return",
        "total_return",
        "expectancy",
        "manual_avg_return",
        "rule_avg_return",
    }
)
RISK_FIELDS = frozenset({"drawdown", "max_drawdown"})


@dataclass(frozen=True)
class BacktestSummaryRow:
    key: str
    label: str
    value: str
    tone: str


@dataclass(frozen=True)
class BacktestSummaryModel:
    rows: tuple[BacktestSummaryRow, ...]


def build_backtest_summary_model(
    summary: Mapping[str, Any] | None,
    *,
    translator: Callable[[str], str],
) -> BacktestSummaryModel:
    values = dict(summary or {})
    rows: list[BacktestSummaryRow] = []
    for key in SUMMARY_FIELDS:
        if key not in values:
            continue
        rows.append(
            BacktestSummaryRow(
                key=key,
                label=translator(f"backtest.summary.{key}"),
                value=_display(values.get(key)),
                tone=value_tone(key, values.get(key)),
            )
        )
    return BacktestSummaryModel(rows=tuple(rows))


def value_tone(field: str, value: Any) -> str:
    number = _number(value)
    if number is None:
        return "secondary"
    if field in RISK_FIELDS:
        return "danger" if number != 0 else "secondary"
    if field in SIGNED_PROFIT_FIELDS:
        if number > 0:
            return "success"
        if number < 0:
            return "danger"
        return "secondary"
    return "secondary"


def _display(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "BacktestSummaryModel",
    "BacktestSummaryRow",
    "build_backtest_summary_model",
    "value_tone",
]
