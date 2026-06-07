from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .parameter_schema import StrategyRuleParams
from .strategies import BaseStrategy
from .types import Signal


REQUIRED_OHLCV_COLUMNS = frozenset({"open", "high", "low", "close", "volume"})


@dataclass(frozen=True)
class DeepVEntryDecision:
    should_open_long: bool
    reason: str
    signal_bar_index: int | None = None
    entry_timing: str = "next_open"


def evaluate_deep_v_entry(
    visible_history: pd.DataFrame,
    params: StrategyRuleParams,
) -> DeepVEntryDecision:
    """Evaluate a deep-V entry using only the supplied visible OHLCV history."""
    params.validate()
    if params.direction not in {"long_only", "both"}:
        return DeepVEntryDecision(False, "direction_disallows_long", entry_timing=params.entry_mode)
    if not isinstance(visible_history, pd.DataFrame) or visible_history.empty:
        return DeepVEntryDecision(False, "insufficient_history", entry_timing=params.entry_mode)
    if not REQUIRED_OHLCV_COLUMNS <= set(visible_history.columns):
        return DeepVEntryDecision(False, "missing_ohlcv", entry_timing=params.entry_mode)

    history = visible_history.reset_index(drop=True)
    current_position = len(history) - 1
    current = history.iloc[current_position]
    signal_bar_index = _bar_index(current, current_position)

    if params.entry_mode == "next_open" and _is_setup_bar(
        history,
        current_position,
        params,
        require_long_lower_shadow=True,
    ):
        return DeepVEntryDecision(True, "pinbar_close", signal_bar_index, "next_open")

    if _is_bullish_confirmation(current, params):
        maximum_lag = min(params.rebound_confirm_bars, current_position)
        for lag in range(1, maximum_lag + 1):
            if _is_setup_bar(
                history,
                current_position - lag,
                params,
                require_long_lower_shadow=False,
            ):
                return DeepVEntryDecision(True, "confirmation_bar", signal_bar_index, "next_open")

    return DeepVEntryDecision(False, "conditions_not_met", signal_bar_index, params.entry_mode)


class DeepVReversalStrategy(BaseStrategy):
    name = "Deep V Reversal"

    def __init__(self, params: StrategyRuleParams | None = None):
        self.rule_params = (params or StrategyRuleParams()).validate()
        self._last_entry_signal_i: int | None = None
        super().__init__(**self.rule_params.to_dict())

    def on_bar(
        self,
        i: int,
        row: pd.Series,
        history: pd.DataFrame,
        position: dict | None,
    ) -> str:
        if position is not None and not self.rule_params.allow_overlap_positions:
            return Signal.HOLD
        if self._last_entry_signal_i is not None:
            elapsed = int(i) - self._last_entry_signal_i
            if elapsed <= self.rule_params.cooldown_bars:
                return Signal.HOLD
        decision = evaluate_deep_v_entry(history, self.rule_params)
        if decision.should_open_long:
            self._last_entry_signal_i = int(i)
            return Signal.OPEN_LONG
        return Signal.HOLD


def _is_setup_bar(
    history: pd.DataFrame,
    position: int,
    params: StrategyRuleParams,
    *,
    require_long_lower_shadow: bool,
) -> bool:
    required_history = max(params.trend_lookback, params.drop_lookback, params.volume_lookback)
    if params.regime_filter == "uptrend":
        required_history = max(required_history, params.uptrend_lookback)
    if position < required_history:
        return False

    current = history.iloc[position]
    current_close = _finite(current.get("close"))
    current_open = _finite(current.get("open"))
    current_high = _finite(current.get("high"))
    current_low = _finite(current.get("low"))
    current_volume = _finite(current.get("volume"))
    if None in {current_close, current_open, current_high, current_low, current_volume}:
        return False
    if current_high <= current_low:
        return False

    trend_start = _finite(history.iloc[position - params.trend_lookback].get("close"))
    trend_end = _finite(history.iloc[position - 1].get("close"))
    drop_start = _finite(history.iloc[position - params.drop_lookback].get("close"))
    if None in {trend_start, trend_end, drop_start} or trend_start <= 0 or drop_start <= 0:
        return False
    prior_downtrend = trend_end < trend_start
    drop_return = current_close / drop_start - 1.0
    drop_ok = drop_return <= -params.min_drop_pct

    prior_volume = pd.to_numeric(
        history.iloc[position - params.volume_lookback : position]["volume"],
        errors="coerce",
    ).dropna()
    if prior_volume.empty:
        return False
    average_volume = float(prior_volume.mean())
    volume_ok = average_volume > 0 and current_volume / average_volume >= params.volume_spike_multiple

    candle_range = current_high - current_low
    lower_shadow = max(min(current_open, current_close) - current_low, 0.0)
    lower_shadow_ratio = lower_shadow / candle_range
    shape_ok = not require_long_lower_shadow or lower_shadow_ratio >= params.lower_shadow_min_ratio

    regime_ok = True
    if params.regime_filter == "uptrend":
        uptrend_start = _finite(history.iloc[position - params.uptrend_lookback].get("close"))
        regime_ok = bool(
            uptrend_start is not None
            and uptrend_start > 0
            and current_close / uptrend_start - 1.0 >= params.uptrend_min_return_pct
        )
    return bool(prior_downtrend and drop_ok and volume_ok and shape_ok and regime_ok)


def _is_bullish_confirmation(row: pd.Series, params: StrategyRuleParams) -> bool:
    open_price = _finite(row.get("open"))
    high = _finite(row.get("high"))
    low = _finite(row.get("low"))
    close = _finite(row.get("close"))
    if None in {open_price, high, low, close} or high <= low or close <= open_price:
        return False
    body_ratio = (close - open_price) / (high - low)
    return bool(body_ratio >= params.bullish_next_candle_min_body_ratio)


def _bar_index(row: pd.Series, fallback: int) -> int:
    try:
        return int(row.get("bar_index"))
    except (TypeError, ValueError):
        return int(fallback)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "DeepVEntryDecision",
    "DeepVReversalStrategy",
    "evaluate_deep_v_entry",
]
