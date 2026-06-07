from __future__ import annotations

from typing import Any, Iterable, Mapping

import pandas as pd


SUMMARY_FIELDS = (
    "total_trades",
    "closed_trades",
    "win_rate",
    "avg_return",
    "median_return",
    "total_return",
    "max_drawdown",
    "profit_factor",
    "expectancy",
    "avg_holding_bars",
    "max_holding_bars",
    "fee_total",
    "slippage_total",
    "hit_tp_count",
    "hit_sl_count",
    "timeout_exit_count",
)
TRADE_COLUMNS = (
    "entry_bar_index",
    "entry_time",
    "entry_price",
    "exit_bar_index",
    "exit_time",
    "exit_price",
    "side",
    "return_pct",
    "pnl",
    "exit_reason",
    "holding_bars",
    "fee",
    "slippage",
)
EQUITY_COLUMNS = ("bar_index", "time", "equity", "drawdown")
COMPARISON_COLUMNS = (
    "manual_trade_count",
    "rule_trade_count",
    "overlap_entry_bars",
    "manual_only_bars",
    "rule_only_bars",
    "manual_avg_return",
    "rule_avg_return",
    "manual_win_rate",
    "rule_win_rate",
    "overlap_ratio",
)


def format_summary(
    summary: Mapping[str, Any] | None,
    *,
    warnings: Iterable[str] = (),
) -> str:
    values = dict(summary or {})
    lines = [
        "Historical simulation for rule-hypothesis research only; not a trading signal or future-return forecast.",
        "",
    ]
    if int(values.get("total_trades") or 0) == 0:
        lines.append("Warning: No rule trades occurred in the selected period.")
    for field in SUMMARY_FIELDS:
        if field in values:
            lines.append(f"{field}: {_display(values.get(field))}")
    warning_values = [str(value) for value in warnings if str(value).strip()]
    if warning_values:
        lines.extend(["", "Warnings:", *[f"- {value}" for value in warning_values]])
    return "\n".join(lines)


def trade_rows(trades: pd.DataFrame | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return _table_rows(trades, TRADE_COLUMNS)


def equity_rows(equity_curve: pd.DataFrame | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return _table_rows(equity_curve, EQUITY_COLUMNS)


def comparison_rows(comparison: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    values = dict(comparison or {})
    return [
        {"metric": metric, "value": _display(values.get(metric))}
        for metric in COMPARISON_COLUMNS
    ]


def format_errors(errors: Iterable[Any] | None) -> str:
    messages = [str(value) for value in (errors or []) if str(value).strip()]
    return "\n".join(f"Error: {message}" for message in messages) or "Unknown backtest error."


def _table_rows(
    value: pd.DataFrame | list[dict[str, Any]] | None,
    columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    if isinstance(value, pd.DataFrame):
        records = value.to_dict("records")
    else:
        records = list(value or [])
    return [
        {column: record.get(column) for column in columns}
        for record in records
        if isinstance(record, Mapping)
    ]


def _display(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value) if value else "-"
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


__all__ = [
    "COMPARISON_COLUMNS",
    "EQUITY_COLUMNS",
    "SUMMARY_FIELDS",
    "TRADE_COLUMNS",
    "comparison_rows",
    "equity_rows",
    "format_errors",
    "format_summary",
    "trade_rows",
]
