from __future__ import annotations

import json
import re
from dataclasses import fields
from typing import Any

try:
    from ..backtesting.parameter_schema import StrategyRuleParams
except ImportError:  # Compatibility with the project's legacy top-level imports.
    from backtesting.parameter_schema import StrategyRuleParams


ANALYSIS_TO_BACKTEST_PARAM_MAP = {
    "drop_pct_threshold": "min_drop_pct",
    "volume_spike_threshold": "volume_spike_multiple",
    "lower_shadow_ratio": "lower_shadow_min_ratio",
    "next_candle_body_ratio": "bullish_next_candle_min_body_ratio",
    "trend_window": "trend_lookback",
    "future_window": "max_holding_bars",
    "tp_threshold": "take_profit_pct",
    "sl_threshold": "stop_loss_pct",
}

FORBIDDEN_OUTCOME_TOKENS = (
    "fwd",
    "future_return",
    "mfe",
    "mae",
    "hit_tp",
    "hit_sl",
    "outcome",
    "pnl",
    "manual_trade_final",
)


def analysis_output_to_backtest_params(
    analysis_output: dict[str, Any],
    *,
    defaults: StrategyRuleParams | None = None,
) -> StrategyRuleParams:
    """Map auditable analysis thresholds into semantic backtest parameters.

    ``future_window`` is retained as a legacy name for an exit timeout only.
    Outcome values and outcome-label columns are rejected and never become
    entry conditions.
    """
    if not isinstance(analysis_output, dict):
        raise ValueError("analysis_output must be a mapping")
    _reject_outcome_fields(analysis_output)

    values = (defaults or StrategyRuleParams()).to_dict()
    param_names = {field.name for field in fields(StrategyRuleParams)}
    for key, value in analysis_output.items():
        if key in param_names:
            values[key] = value
        mapped = ANALYSIS_TO_BACKTEST_PARAM_MAP.get(key)
        if mapped is not None:
            values[mapped] = abs(value) if mapped == "min_drop_pct" else value

    for condition in _conditions(analysis_output.get("conditions_json")):
        if not _apply_condition(values, condition):
            column = str(condition.get("column") or "")
            raise ValueError(f"Candidate condition has no semantic StrategyRuleParams mapping: {column}")
    return StrategyRuleParams.from_dict(values)


def _reject_outcome_fields(payload: dict[str, Any]) -> None:
    for key in payload:
        lower = str(key).lower()
        if lower == "future_window":
            continue
        if any(token in lower for token in FORBIDDEN_OUTCOME_TOKENS):
            raise ValueError(f"Outcome field is not allowed in backtest parameter mapping: {key}")
    for condition in _conditions(payload.get("conditions_json")):
        column = str(condition.get("column") or "")
        lower = column.lower()
        if any(token in lower for token in FORBIDDEN_OUTCOME_TOKENS):
            raise ValueError(f"Outcome field is not allowed in backtest parameter mapping: {column}")


def _conditions(value: Any) -> list[dict[str, Any]]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"conditions_json is invalid: {exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("conditions_json must contain a list of conditions")
    return value


def _apply_condition(values: dict[str, Any], condition: dict[str, Any]) -> bool:
    column = str(condition.get("column") or "")
    operation = str(condition.get("op") or "")
    raw_value = condition.get("value")
    if operation not in {"<=", "<", ">=", ">"}:
        return False
    try:
        threshold = float(raw_value)
    except (TypeError, ValueError):
        return False

    ret_match = re.fullmatch(r"(?:pre_)?ret_(\d+)|pre_ret_(\d+)", column)
    if ret_match and operation in {"<=", "<"} and threshold < 0:
        values["drop_lookback"] = int(next(group for group in ret_match.groups() if group))
        values["min_drop_pct"] = abs(threshold)
        return True

    volume_match = re.fullmatch(r"(?:event_)?volume_ratio_(\d+)", column)
    if volume_match and operation in {">=", ">"}:
        values["volume_lookback"] = int(volume_match.group(1))
        values["volume_spike_multiple"] = threshold
        return True

    if column in {"event_lower_wick_ratio", "lower_wick_ratio", "lower_shadow_ratio"} and operation in {">=", ">"}:
        values["lower_shadow_min_ratio"] = threshold
        return True
    return False


__all__ = ["ANALYSIS_TO_BACKTEST_PARAM_MAP", "analysis_output_to_backtest_params"]
