from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

import pandas as pd

try:
    from backtesting.engine import run_backtest
    from backtesting.features import (
        FeatureBuildError,
        build_ohlcv_feature_frame,
        registered_ohlcv_feature_names,
    )
    from backtesting.random_baseline import run_random_entry_baseline
    from backtesting.rule_evaluator import RuleEvaluationError, evaluate_rule
    from backtesting.strategy_spec import StrategySpec
    from backtesting.types import BacktestConfig, BacktestResult, Signal
except ImportError:  # pragma: no cover - package import path
    from .engine import run_backtest
    from .features import (
        FeatureBuildError,
        build_ohlcv_feature_frame,
        registered_ohlcv_feature_names,
    )
    from .random_baseline import run_random_entry_baseline
    from .rule_evaluator import RuleEvaluationError, evaluate_rule
    from .strategy_spec import StrategySpec
    from .types import BacktestConfig, BacktestResult, Signal


class StrategySpecLongStrategy:
    name = "StrategySpec v1"

    def __init__(self, spec: StrategySpec) -> None:
        self.spec = spec
        self.rule = spec.entry["rule"]

    def on_bar(
        self,
        i: int,
        row: pd.Series,
        history: pd.DataFrame,
        position: dict | None,
    ) -> str:
        if position is not None:
            return Signal.HOLD
        try:
            return Signal.OPEN_LONG if evaluate_rule(self.rule, row) else Signal.HOLD
        except RuleEvaluationError as exc:
            raise ValueError(str(exc)) from exc


def run_strategy_spec_backtest(
    spec: StrategySpec,
    market_df: pd.DataFrame,
    config: BacktestConfig,
    *,
    symbol: str,
    interval: str,
) -> BacktestResult:
    if not isinstance(spec, StrategySpec):
        spec = StrategySpec.from_dict(spec)
    data = _frame_with_required_features(market_df, _rule_features(spec.entry["rule"]))
    effective_config = _effective_config(config, spec)
    result = run_backtest(
        data,
        StrategySpecLongStrategy(spec),
        effective_config,
        symbol,
        interval,
    )
    try:
        random_baseline = run_random_entry_baseline(
            data,
            result.trades,
            effective_config,
            symbol=symbol,
            interval=interval,
        )
        result.random_baseline_equity_curve = random_baseline.median_equity_curve
        result.random_baseline_summary = random_baseline.summary
        result.warnings = list(dict.fromkeys([*result.warnings, *random_baseline.warnings]))
    except Exception as exc:  # pragma: no cover - defensive boundary
        warning = f"random baseline skipped: {exc}"
        result.random_baseline_summary = {"status": "skipped", "warnings": [warning]}
        result.warnings = list(dict.fromkeys([*result.warnings, warning]))
    return result


def _frame_with_required_features(
    frame: pd.DataFrame,
    required_features: set[str],
) -> pd.DataFrame:
    data = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    missing = sorted(feature for feature in required_features if feature not in data.columns)
    computable = sorted(
        feature for feature in missing if feature in registered_ohlcv_feature_names()
    )
    unsupported = sorted(set(missing).difference(computable))
    if unsupported:
        raise FeatureBuildError(f"Missing unsupported features: {', '.join(unsupported)}")
    if computable:
        data = build_ohlcv_feature_frame(data, required_features=computable)
    still_missing = sorted(feature for feature in required_features if feature not in data.columns)
    if still_missing:
        raise FeatureBuildError(f"Missing features after OHLCV build: {', '.join(still_missing)}")
    return data


def _rule_features(rule: Mapping[str, Any]) -> set[str]:
    if "feature" in rule:
        return {str(rule["feature"])}
    features: set[str] = set()
    for key in ("all", "any"):
        for child in rule.get(key, []) or []:
            features.update(_rule_features(child))
    return features


def _effective_config(config: BacktestConfig, spec: StrategySpec) -> BacktestConfig:
    exit_rules = spec.exit
    position = spec.position
    return replace(
        config,
        notional_quote=float(position["notional_per_trade"]),
        fee_bps=float(position["fee_bps"]),
        slippage_bps=float(position["slippage_bps"]),
        allow_short=False,
        single_position=True,
        max_bars_hold=int(exit_rules["max_holding_bars"]),
        stop_loss_pct=float(exit_rules["stop_loss_pct"]) * 100.0,
        take_profit_pct=float(exit_rules["take_profit_pct"]) * 100.0,
        signal_timing="next_open",
        cooldown_bars=int(position["cooldown_bars"]),
    )


__all__ = [
    "StrategySpecLongStrategy",
    "run_strategy_spec_backtest",
]
