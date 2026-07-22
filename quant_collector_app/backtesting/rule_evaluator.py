from __future__ import annotations

import math
import operator
from typing import Any, Mapping

import pandas as pd


class RuleEvaluationError(ValueError):
    pass


OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


def evaluate_rule(rule: Mapping[str, Any], row: pd.Series) -> bool:
    """Evaluate the controlled StrategySpec rule DSL against one bar."""
    if "all" in rule:
        children = rule["all"]
        if not isinstance(children, list) or not children:
            raise RuleEvaluationError("all must contain at least one rule")
        return all(evaluate_rule(child, row) for child in children)
    if "any" in rule:
        children = rule["any"]
        if not isinstance(children, list) or not children:
            raise RuleEvaluationError("any must contain at least one rule")
        return any(evaluate_rule(child, row) for child in children)
    return _evaluate_condition(rule, row)


def _evaluate_condition(rule: Mapping[str, Any], row: pd.Series) -> bool:
    try:
        feature = str(rule["feature"])
        op = str(rule["op"])
        right = float(rule["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuleEvaluationError(f"Invalid rule condition: {rule!r}") from exc
    if op not in OPS:
        raise RuleEvaluationError(f"Unsupported rule operator: {op}")
    if feature not in row.index:
        raise RuleEvaluationError(f"Required feature is missing: {feature}")
    try:
        left = float(row[feature])
    except (TypeError, ValueError) as exc:
        raise RuleEvaluationError(f"Required feature is not numeric: {feature}") from exc
    if not math.isfinite(left) or not math.isfinite(right):
        return False
    return bool(OPS[op](left, right))


__all__ = ["RuleEvaluationError", "evaluate_rule"]
