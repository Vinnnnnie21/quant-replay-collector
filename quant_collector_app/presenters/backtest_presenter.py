from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Mapping

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

_WARNING_KEYS = {
    "Backtest result is for research only and does not represent live trading returns.": "backtest.warning.research_only",
    "Historical backtest summary is a rule-hypothesis diagnostic, not a trading signal or future-return forecast.": "backtest.warning.historical_diagnostic",
    "Manual-vs-rule comparison is descriptive and subject to manual-trade selection bias.": "backtest.warning.manual_selection_bias",
    "signal_timing=on_close forces strategy fills to CLOSE to avoid look-ahead execution.": "backtest.warning.on_close_fill",
    "input dataframe is empty": "backtest.warning.input_empty",
    "last-bar open signal ignored because signal_timing=next_open has no next bar.": "backtest.warning.last_bar_signal_ignored",
    "open position was force-closed on the last bar": "backtest.warning.position_force_closed",
    "sample size is small for train/validation/test split": "backtest.warning.small_split_sample",
    "Parameters are selected on validation only; test is evaluated once.": "backtest.warning.validation_selection",
    "Parameter scan results are candidate hypotheses and may be overfit.": "backtest.warning.candidate_overfit",
    "Best train params differ from selected validation params.": "backtest.warning.train_validation_mismatch",
    "Test performance is materially weaker than validation; overfit risk is high.": "backtest.warning.weak_test_performance",
}

_ERROR_KEYS = {
    "No analysis candidate parameters are available.": "backtest.validation.no_analysis_params",
    "selected symbol/interval does not match the currently loaded K-line data": "backtest.validation.market_mismatch",
    "backtest form values must be a mapping": "backtest.validation.invalid_form",
    "symbol must not be empty": "backtest.validation.symbol_required",
    "interval must not be empty": "backtest.validation.interval_required",
    "start must be earlier than end": "backtest.validation.date_order",
    "no K-line data is available": "backtest.validation.no_market_data",
    "K-line data requires open_time_bjt": "backtest.validation.market_time_required",
    "no K-line data exists in the requested backtest date range": "backtest.validation.no_range_data",
}

_TRUNCATED_COMBINATIONS_RE = re.compile(
    r"^parameter combinations truncated from (?P<total>\d+) to (?P<limit>\d+)$"
)


def format_summary(
    summary: Mapping[str, Any] | None,
    *,
    warnings: Iterable[str] = (),
    translator: Callable[[str], str] | None = None,
) -> str:
    values = dict(summary or {})
    lines = [
        _translated(
            translator,
            "backtest.disclaimer",
            "Historical simulation for rule-hypothesis research only; not a trading signal or future-return forecast.",
        ),
        "",
    ]
    if int(values.get("total_trades") or 0) == 0:
        lines.append(
            _translated(
                translator,
                "backtest.no_rule_trades",
                "Warning: No rule trades occurred in the selected period.",
            )
        )
    for field in SUMMARY_FIELDS:
        if field in values:
            label = _translated(translator, f"backtest.summary.{field}", field)
            lines.append(f"{label}: {_display(values.get(field))}")
    warning_values = localize_warnings(warnings, translator=translator)
    if warning_values:
        warning_label = _translated(translator, "backtest.warnings", "Warnings")
        lines.extend(["", f"{warning_label}:", *[f"- {value}" for value in warning_values]])
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


def format_errors(
    errors: Iterable[Any] | None,
    *,
    translator: Callable[[str], str] | None = None,
) -> str:
    messages = [
        _localize_error(str(value), translator)
        for value in (errors or [])
        if str(value).strip()
    ]
    if messages:
        template = _translated(translator, "backtest.error", "Error: {message}")
        return "\n".join(template.format(message=message) for message in messages)
    return _translated(translator, "backtest.unknown_error", "Unknown backtest error.")


def _translated(
    translator: Callable[[str], str] | None,
    key: str,
    default: str,
) -> str:
    return translator(key) if translator is not None else default


def _localize_warning(value: str, translator: Callable[[str], str] | None) -> str:
    if translator is None:
        return value
    key = _WARNING_KEYS.get(value)
    if key is not None:
        return translator(key)
    match = _TRUNCATED_COMBINATIONS_RE.fullmatch(value)
    if match is not None:
        return translator("backtest.warning.combinations_truncated").format(**match.groupdict())
    return value


def localize_warnings(
    warnings: Iterable[Any] | None,
    *,
    translator: Callable[[str], str] | None = None,
) -> list[str]:
    return [
        _localize_warning(str(value), translator)
        for value in (warnings or [])
        if str(value).strip()
    ]


def _localize_error(value: str, translator: Callable[[str], str] | None) -> str:
    if translator is None:
        return value
    key = _ERROR_KEYS.get(value)
    return translator(key) if key is not None else value


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
    "localize_warnings",
    "trade_rows",
]
