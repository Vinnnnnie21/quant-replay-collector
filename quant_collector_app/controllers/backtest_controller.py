from __future__ import annotations

from dataclasses import fields
from typing import Any, Mapping

import pandas as pd

try:
    from analysis.rule_parameter_export import analysis_output_to_backtest_params
    from backtesting.date_range import BacktestDateRange
    from backtesting.parameter_schema import StrategyRuleParams
    from backtesting.types import BacktestConfig
    from services.backtest_service import (
        EQUITY_OUTPUT_COLUMNS,
        TRADE_OUTPUT_COLUMNS,
        BacktestService,
        BacktestServiceResult,
    )
except ImportError:  # pragma: no cover - package import path
    from ..analysis.rule_parameter_export import analysis_output_to_backtest_params
    from ..backtesting.date_range import BacktestDateRange
    from ..backtesting.parameter_schema import StrategyRuleParams
    from ..backtesting.types import BacktestConfig
    from ..services.backtest_service import (
        EQUITY_OUTPUT_COLUMNS,
        TRADE_OUTPUT_COLUMNS,
        BacktestService,
        BacktestServiceResult,
    )


class BacktestController:
    """Translate user inputs into the pure backtest service contract."""

    def __init__(self, service: BacktestService | None = None) -> None:
        self._service = service or BacktestService()

    @staticmethod
    def default_form_values() -> dict[str, Any]:
        values = StrategyRuleParams().to_dict()
        values["initial_equity"] = 10_000.0
        values["symbol"] = ""
        values["interval"] = ""
        values["backtest_start"] = ""
        values["backtest_end"] = ""
        return values

    def run(
        self,
        form_values: Mapping[str, Any],
        market_df: pd.DataFrame,
        *,
        manual_trades: pd.DataFrame | list[dict[str, Any]] | None = None,
        loaded_market_key: Mapping[str, Any] | tuple[Any, ...] | list[Any] | None = None,
    ) -> BacktestServiceResult:
        try:
            params = self.build_rule_params(form_values)
            config = self.build_config(form_values)
            date_range = self.build_date_range(form_values)
            self.validate_loaded_market(date_range, loaded_market_key)
        except Exception as exc:
            return _failure_result(str(exc))
        return self._service.run(
            config,
            market_df,
            date_range=date_range,
            rule_params=params,
            manual_trades=manual_trades,
        )

    @staticmethod
    def validate_loaded_market(
        date_range: BacktestDateRange,
        loaded_market_key: Mapping[str, Any] | tuple[Any, ...] | list[Any] | None,
    ) -> None:
        loaded_identity = _loaded_market_identity(loaded_market_key)
        if loaded_identity is None:
            return
        requested_identity = (date_range.symbol.strip().upper(), date_range.interval.strip())
        if requested_identity != loaded_identity:
            raise ValueError(
                "selected symbol/interval does not match the currently loaded K-line data"
            )

    @staticmethod
    def build_rule_params(form_values: Mapping[str, Any]) -> StrategyRuleParams:
        if not isinstance(form_values, Mapping):
            raise ValueError("backtest form values must be a mapping")
        defaults = StrategyRuleParams().to_dict()
        values: dict[str, Any] = {}
        for field in fields(StrategyRuleParams):
            raw = form_values.get(field.name, defaults[field.name])
            values[field.name] = _coerce_like(field.name, raw, defaults[field.name])
        return StrategyRuleParams.from_dict(values)

    @staticmethod
    def build_config(form_values: Mapping[str, Any]) -> BacktestConfig:
        if not isinstance(form_values, Mapping):
            raise ValueError("backtest form values must be a mapping")
        params = BacktestController.build_rule_params(form_values)
        return BacktestConfig(
            initial_equity=_float_value("initial_equity", form_values.get("initial_equity", 10_000.0)),
            notional_quote=params.notional_per_trade,
            fee_bps=params.fee_bps,
            slippage_bps=params.slippage_bps,
            signal_timing="next_open",
            stop_loss_pct=None,
            take_profit_pct=None,
            max_bars_hold=None,
        )

    @staticmethod
    def build_date_range(form_values: Mapping[str, Any]) -> BacktestDateRange:
        if not isinstance(form_values, Mapping):
            raise ValueError("backtest form values must be a mapping")
        return BacktestDateRange(
            symbol=str(form_values.get("symbol") or "").strip().upper(),
            interval=str(form_values.get("interval") or "").strip(),
            start=form_values.get("backtest_start"),
            end=form_values.get("backtest_end"),
        ).validate()

    @staticmethod
    def apply_analysis_params(
        analysis_params: Mapping[str, Any] | None,
        *,
        current_values: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not analysis_params:
            raise ValueError("No analysis candidate parameters are available.")
        defaults = BacktestController.build_rule_params(
            current_values or BacktestController.default_form_values()
        )
        mapped = analysis_output_to_backtest_params(dict(analysis_params), defaults=defaults)
        merged = dict(current_values or BacktestController.default_form_values())
        merged.update(mapped.to_dict())
        return merged


def _coerce_like(field: str, value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"{field} must be a bool")
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be an integer") from exc
    if isinstance(default, float):
        return _float_value(field, value)
    return str(value)


def _float_value(field: str, value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc


def _loaded_market_identity(
    loaded_market_key: Mapping[str, Any] | tuple[Any, ...] | list[Any] | None,
) -> tuple[str, str] | None:
    if isinstance(loaded_market_key, Mapping):
        symbol = loaded_market_key.get("symbol")
        interval = loaded_market_key.get("interval")
    elif isinstance(loaded_market_key, (tuple, list)) and len(loaded_market_key) >= 2:
        symbol, interval = loaded_market_key[0], loaded_market_key[1]
    else:
        return None
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_interval = str(interval or "").strip()
    if not normalized_symbol or not normalized_interval:
        return None
    return normalized_symbol, normalized_interval


def _failure_result(message: str) -> BacktestServiceResult:
    return BacktestServiceResult(
        success=False,
        summary={},
        trades=pd.DataFrame(columns=TRADE_OUTPUT_COLUMNS),
        equity_curve=pd.DataFrame(columns=EQUITY_OUTPUT_COLUMNS),
        manual_vs_rule_comparison=None,
        warnings=[],
        errors=[str(message)],
    )


__all__ = ["BacktestController"]
