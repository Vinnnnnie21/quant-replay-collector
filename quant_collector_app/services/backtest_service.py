from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any

import pandas as pd

try:
    from analysis.rule_parameter_export import analysis_output_to_backtest_params
    from backtesting.date_range import BacktestDateRange, slice_backtest_date_range
    from backtesting.deep_v_reversal import DeepVReversalStrategy
    from backtesting.engine import run_backtest
    from backtesting.manual_comparison import compare_manual_vs_rule
    from backtesting.parameter_schema import StrategyRuleParams
    from backtesting.result_summary import summarize_backtest_result
    from backtesting.types import BacktestConfig
except ImportError:  # pragma: no cover - package import path
    from ..analysis.rule_parameter_export import analysis_output_to_backtest_params
    from ..backtesting.date_range import BacktestDateRange, slice_backtest_date_range
    from ..backtesting.deep_v_reversal import DeepVReversalStrategy
    from ..backtesting.engine import run_backtest
    from ..backtesting.manual_comparison import compare_manual_vs_rule
    from ..backtesting.parameter_schema import StrategyRuleParams
    from ..backtesting.result_summary import summarize_backtest_result
    from ..backtesting.types import BacktestConfig


TRADE_OUTPUT_COLUMNS = (
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
EQUITY_OUTPUT_COLUMNS = ("bar_index", "time", "equity", "drawdown")


@dataclass(frozen=True)
class BacktestServiceResult:
    success: bool
    summary: dict[str, Any]
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    manual_vs_rule_comparison: dict[str, Any] | None
    warnings: list[str]
    errors: list[str]


class BacktestService:
    """Qt-free orchestration for historical deep-V rule simulation."""

    def run(
        self,
        config: BacktestConfig,
        market_df: pd.DataFrame,
        *,
        date_range: BacktestDateRange,
        rule_params: StrategyRuleParams | None = None,
        manual_trades: pd.DataFrame | list[dict[str, Any]] | None = None,
        analysis_params_source: dict[str, Any] | None = None,
    ) -> BacktestServiceResult:
        try:
            params = (
                rule_params
                or (
                    analysis_output_to_backtest_params(analysis_params_source)
                    if analysis_params_source is not None
                    else StrategyRuleParams()
                )
            ).validate()
            self._validate_config(config)
            required_lookbacks = [params.trend_lookback, params.drop_lookback, params.volume_lookback]
            if params.regime_filter == "uptrend":
                required_lookbacks.append(params.uptrend_lookback)
            minimum_bars = max(required_lookbacks) + 2
            selected = slice_backtest_date_range(
                market_df,
                date_range,
                minimum_bars=minimum_bars,
            )
            if selected.status != "ready":
                return self._failure(selected.message)
            effective_config = self._effective_config(config, params)
            raw = run_backtest(
                selected.data,
                DeepVReversalStrategy(params),
                effective_config,
                date_range.symbol,
                date_range.interval,
            )
            summary = summarize_backtest_result(
                raw.trades,
                raw.equity_curve,
                initial_equity=effective_config.initial_equity,
            )
            trades = _standardize_trades(raw.trades)
            comparison = None
            if manual_trades is not None and not _frame(manual_trades).empty:
                comparison = compare_manual_vs_rule(
                    manual_trades,
                    trades,
                    symbol=date_range.symbol,
                    interval=date_range.interval,
                    valid_entry_bars=selected.data["bar_index"].tolist(),
                )
            warnings = list(dict.fromkeys([*raw.warnings, *summary.get("warnings", [])]))
            if comparison is not None:
                warnings = list(dict.fromkeys([*warnings, *comparison.get("warnings", [])]))
            return BacktestServiceResult(
                success=True,
                summary=summary,
                trades=trades,
                equity_curve=_standardize_equity(raw.equity_curve),
                manual_vs_rule_comparison=comparison,
                warnings=warnings,
                errors=[],
            )
        except Exception as exc:
            return self._failure(str(exc))

    @staticmethod
    def _failure(message: str) -> BacktestServiceResult:
        return BacktestServiceResult(
            success=False,
            summary={},
            trades=pd.DataFrame(columns=TRADE_OUTPUT_COLUMNS),
            equity_curve=pd.DataFrame(columns=EQUITY_OUTPUT_COLUMNS),
            manual_vs_rule_comparison=None,
            warnings=[],
            errors=[str(message)],
        )

    @staticmethod
    def _validate_config(config: BacktestConfig) -> None:
        if not isinstance(config, BacktestConfig):
            raise ValueError("config must be a BacktestConfig")
        for field in ("initial_equity", "notional_quote"):
            value = _finite(getattr(config, field))
            if value is None or value <= 0:
                raise ValueError(f"{field} must be greater than zero")
        for field in ("fee_bps", "slippage_bps"):
            value = _finite(getattr(config, field))
            if value is None or value < 0:
                raise ValueError(f"{field} must be non-negative")
        for field in (
            "maker_fee_bps",
            "taker_fee_bps",
            "funding_fee_bps",
            "stop_loss_pct",
            "take_profit_pct",
        ):
            raw = getattr(config, field)
            if raw is not None:
                value = _finite(raw)
                if value is None or value < 0:
                    raise ValueError(f"{field} must be non-negative")
        if config.max_bars_hold is not None:
            if isinstance(config.max_bars_hold, bool) or int(config.max_bars_hold) <= 0:
                raise ValueError("max_bars_hold must be a positive integer")
        if config.signal_timing != "next_open":
            raise ValueError("deep-V BacktestService requires signal_timing=next_open")

    @staticmethod
    def _effective_config(config: BacktestConfig, params: StrategyRuleParams) -> BacktestConfig:
        return replace(
            config,
            allow_short=False,
            single_position=True,
            max_bars_hold=config.max_bars_hold if config.max_bars_hold is not None else params.max_holding_bars,
            stop_loss_pct=config.stop_loss_pct if config.stop_loss_pct is not None else params.stop_loss_pct * 100.0,
            take_profit_pct=config.take_profit_pct if config.take_profit_pct is not None else params.take_profit_pct * 100.0,
            signal_timing="next_open",
        )


def _standardize_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(trades, pd.DataFrame) or trades.empty:
        return pd.DataFrame(columns=TRADE_OUTPUT_COLUMNS)
    out = trades.copy()
    out["entry_time"] = out.get("entry_bar_time_bjt")
    out["entry_price"] = out.get("entry_fill_price")
    out["exit_time"] = out.get("exit_bar_time_bjt")
    out["exit_price"] = out.get("exit_fill_price")
    out["return_pct"] = out.get("net_return_pct")
    out["pnl"] = out.get("net_pnl_quote")
    out["fee"] = _numeric_series(out, "entry_fee_quote") + _numeric_series(out, "exit_fee_quote")
    out["slippage"] = out.apply(_trade_slippage_quote, axis=1)
    return out


def _standardize_equity(equity: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(equity, pd.DataFrame) or equity.empty:
        return pd.DataFrame(columns=EQUITY_OUTPUT_COLUMNS)
    out = equity.copy()
    out["time"] = out.get("bar_open_time_bjt")
    out["equity"] = out.get("equity_after")
    out["drawdown"] = out.get("drawdown_pct")
    return out


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _trade_slippage_quote(row: pd.Series) -> float:
    quantity = _finite(row.get("quantity"))
    entry_raw = _finite(row.get("entry_price_raw"))
    entry_fill = _finite(row.get("entry_fill_price"))
    exit_raw = _finite(row.get("exit_price_raw"))
    exit_fill = _finite(row.get("exit_fill_price"))
    if None in {quantity, entry_raw, entry_fill, exit_raw, exit_fill}:
        return 0.0
    return float((abs(entry_fill - entry_raw) + abs(exit_raw - exit_fill)) * quantity)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame(value or [])


__all__ = ["BacktestService", "BacktestServiceResult"]
