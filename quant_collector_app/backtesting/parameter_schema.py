from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyRuleParams:
    """Reproducible semantic parameters for the deep-V research rule.

    Percentage-like strategy thresholds use decimal fractions: ``0.02`` means
    two percent. Execution assumptions remain separate from the existing
    ``backtesting.types.BacktestConfig``.
    """

    strategy_name: str = "deep_v_reversal"
    direction: str = "long_only"
    trend_lookback: int = 20
    drop_lookback: int = 5
    min_drop_pct: float = 0.02
    volume_lookback: int = 20
    volume_spike_multiple: float = 2.0
    lower_shadow_min_ratio: float = 0.45
    bullish_next_candle_min_body_ratio: float = 0.6
    rebound_confirm_bars: int = 1
    regime_filter: str = "disabled"
    uptrend_lookback: int = 50
    uptrend_min_return_pct: float = 0.0
    entry_mode: str = "next_open"
    exit_mode: str = "tp_sl_timeout"
    take_profit_pct: float = 0.03
    stop_loss_pct: float = 0.015
    max_holding_bars: int = 20
    fee_bps: float = 4.0
    slippage_bps: float = 2.0
    notional_per_trade: float = 1000.0
    cooldown_bars: int = 0
    allow_overlap_positions: bool = False

    def validate(self) -> StrategyRuleParams:
        if self.strategy_name != "deep_v_reversal":
            raise ValueError(
                f"strategy_name is unsupported by the current backtest service: {self.strategy_name}"
            )
        if self.direction != "long_only":
            raise ValueError(f"direction is unsupported by deep_v_reversal: {self.direction}")
        for field in (
            "trend_lookback",
            "drop_lookback",
            "volume_lookback",
            "uptrend_lookback",
            "max_holding_bars",
        ):
            _require_positive_int(field, getattr(self, field))
        for field in ("rebound_confirm_bars", "cooldown_bars"):
            _require_non_negative_int(field, getattr(self, field))
        for field in (
            "min_drop_pct",
            "lower_shadow_min_ratio",
            "bullish_next_candle_min_body_ratio",
            "take_profit_pct",
            "stop_loss_pct",
        ):
            _require_fraction(field, getattr(self, field), allow_zero=False)
        _require_fraction("uptrend_min_return_pct", self.uptrend_min_return_pct, allow_zero=True)
        _require_positive_number("volume_spike_multiple", self.volume_spike_multiple)
        _require_positive_number("notional_per_trade", self.notional_per_trade)
        _require_non_negative_number("fee_bps", self.fee_bps)
        _require_non_negative_number("slippage_bps", self.slippage_bps)
        if self.entry_mode not in {"next_open", "confirmation_next_open"}:
            raise ValueError(f"entry_mode is unsupported: {self.entry_mode}")
        if self.exit_mode != "tp_sl_timeout":
            raise ValueError(f"exit_mode is unsupported by deep_v_reversal: {self.exit_mode}")
        if self.regime_filter not in {"disabled", "uptrend"}:
            raise ValueError(f"regime_filter is unsupported: {self.regime_filter}")
        if self.allow_overlap_positions is not False:
            raise ValueError("allow_overlap_positions must be False for the current single-position engine")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StrategyRuleParams:
        if not isinstance(value, dict):
            raise ValueError("StrategyRuleParams payload must be a mapping")
        return cls(**value).validate()

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> StrategyRuleParams:
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid StrategyRuleParams JSON: {exc}") from exc
        return cls.from_dict(payload)


def _number(field: str, value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _require_positive_int(field: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


def _require_non_negative_int(field: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _require_positive_number(field: str, value: Any) -> None:
    if _number(field, value) <= 0:
        raise ValueError(f"{field} must be greater than zero")


def _require_non_negative_number(field: str, value: Any) -> None:
    if _number(field, value) < 0:
        raise ValueError(f"{field} must be non-negative")


def _require_fraction(field: str, value: Any, *, allow_zero: bool) -> None:
    number = _number(field, value)
    lower_ok = number >= 0 if allow_zero else number > 0
    if not lower_ok or number > 1:
        qualifier = "between 0 and 1" if allow_zero else "greater than 0 and no greater than 1"
        raise ValueError(f"{field} must be {qualifier}")


__all__ = ["StrategyRuleParams"]
