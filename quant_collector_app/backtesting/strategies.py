from __future__ import annotations

import json
import operator
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from backtesting.types import Signal
except ImportError:  # pragma: no cover - package import path
    from .types import Signal


FORBIDDEN_FEATURE_TOKENS = (
    "fwd",
    "post",
    "future",
    "mfe",
    "mae",
    "hit_tp",
    "hit_sl",
    "outcome",
    "label",
    "pnl",
    "manual_trade_final",
    "final_return",
    "net_return",
    "realized",
)
OPS = {
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
    "==": operator.eq,
}


def _is_future_field(column: str) -> bool:
    lower = str(column or "").lower()
    return any(token in lower for token in FORBIDDEN_FEATURE_TOKENS)


class BaseStrategy:
    name = "BaseStrategy"

    def __init__(self, **params):
        self.params = dict(params)

    def on_bar(self, i: int, row: pd.Series, history: pd.DataFrame, position: dict | None) -> str:
        return Signal.HOLD


class MovingAverageCrossStrategy(BaseStrategy):
    name = "MA Cross"

    def __init__(self, fast_window: int = 5, slow_window: int = 20, direction: str = "BOTH"):
        super().__init__(fast_window=fast_window, slow_window=slow_window, direction=direction)
        self.fast_window = max(1, int(fast_window))
        self.slow_window = max(self.fast_window + 1, int(slow_window))
        self.direction = str(direction or "BOTH").upper()

    def on_bar(self, i: int, row: pd.Series, history: pd.DataFrame, position: dict | None) -> str:
        if len(history) < self.slow_window + 1 or "close" not in history.columns:
            return Signal.HOLD
        close = pd.to_numeric(history["close"], errors="coerce")
        fast_cur = close.iloc[-self.fast_window:].mean()
        slow_cur = close.iloc[-self.slow_window:].mean()
        fast_prev = close.iloc[-self.fast_window - 1:-1].mean()
        slow_prev = close.iloc[-self.slow_window - 1:-1].mean()
        cross_up = fast_prev <= slow_prev and fast_cur > slow_cur
        cross_down = fast_prev >= slow_prev and fast_cur < slow_cur
        side = str((position or {}).get("side") or "").upper()
        if position:
            if side == "LONG" and cross_down:
                return Signal.CLOSE_LONG
            if side == "SHORT" and cross_up:
                return Signal.CLOSE_SHORT
            return Signal.HOLD
        if cross_up and self.direction in {"LONG_ONLY", "BOTH"}:
            return Signal.OPEN_LONG
        if cross_down and self.direction in {"SHORT_ONLY", "BOTH"}:
            return Signal.OPEN_SHORT
        return Signal.HOLD


class FeatureRuleLongStrategy(BaseStrategy):
    name = "Feature Rule Long"

    def __init__(
        self,
        conditions: list[dict] | None = None,
        exit_bars: int = 10,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
    ):
        conditions = list(conditions or [])
        for cond in conditions:
            column = str(cond.get("column") or "")
            if _is_future_field(column):
                raise ValueError(f"Future/label field is not allowed in strategy condition: {column}")
            if cond.get("op") not in OPS:
                raise ValueError(f"Unsupported condition operator: {cond.get('op')}")
        super().__init__(
            conditions=conditions,
            exit_bars=exit_bars,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        self.conditions = conditions
        self.exit_bars = max(1, int(exit_bars))
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def _conditions_match(self, row: pd.Series) -> bool:
        for cond in self.conditions:
            column = str(cond.get("column") or "")
            if column not in row.index:
                return False
            try:
                left = float(row[column])
                right = float(cond.get("value"))
            except (TypeError, ValueError):
                left = row[column]
                right = cond.get("value")
            if not OPS[cond["op"]](left, right):
                return False
        return True

    def on_bar(self, i: int, row: pd.Series, history: pd.DataFrame, position: dict | None) -> str:
        if position and str(position.get("side")).upper() == "LONG":
            raw_entry_idx = position.get("entry_i")
            if raw_entry_idx is None:
                raw_entry_idx = position.get("entry_bar_index")
            entry_idx = int(i if raw_entry_idx is None else raw_entry_idx)
            if i - entry_idx + 1 >= self.exit_bars:
                return Signal.CLOSE_LONG
            return Signal.HOLD
        if self._conditions_match(row):
            return Signal.OPEN_LONG
        return Signal.HOLD


def conditions_to_text(conditions: list[dict]) -> str:
    return json.dumps(conditions or [], ensure_ascii=False, sort_keys=True)


def load_candidate_rule(path_or_df, rule_index: int) -> FeatureRuleLongStrategy:
    if isinstance(path_or_df, pd.DataFrame):
        rules = path_or_df.copy()
    else:
        rules = pd.read_csv(Path(path_or_df))
    if rules.empty:
        raise ValueError("candidate_rules is empty")
    if "conditions_json" not in rules.columns:
        raise ValueError("candidate_rules must contain conditions_json")
    idx = int(rule_index)
    if idx < 0 or idx >= len(rules):
        raise IndexError(f"rule_index out of range: {idx}")
    raw = rules.iloc[idx].get("conditions_json")
    try:
        conditions = json.loads(raw if isinstance(raw, str) else "[]")
    except Exception as exc:
        raise ValueError(f"Invalid conditions_json at rule_index={idx}: {exc}") from exc
    if not isinstance(conditions, list):
        raise ValueError("conditions_json must decode to a list")
    return FeatureRuleLongStrategy(conditions)
