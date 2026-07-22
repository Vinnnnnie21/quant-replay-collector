from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any


STRATEGY_SPEC_SCHEMA_VERSION = "strategy_spec_v1"
SUPPORTED_NUMERIC_OPERATORS = {"<", "<=", ">", ">=", "==", "!="}
FORBIDDEN_ENTRY_FEATURE_TOKENS = (
    "future",
    "outcome",
    "mfe",
    "mae",
    "hit_tp",
    "hit_sl",
    "pnl",
    "final_return",
    "realized_pnl",
    "realized_return",
    "realized_result",
)
_FEATURE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class StrategySpecValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StrategySpecProvenance:
    source: str
    setup_version_id: str
    research_snapshot_id: str
    decision_mode: str
    formula_version: str
    feature_version: str
    application_version: str
    random_seed: int
    maturity: str
    warnings: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StrategySpecProvenance:
        _require_mapping("provenance", payload)
        warnings = payload.get("warnings", ())
        if not isinstance(warnings, (list, tuple)) or not all(
            isinstance(item, str) for item in warnings
        ):
            raise StrategySpecValidationError("provenance.warnings must be a list of strings")
        return cls(
            source=_required_text(payload, "source"),
            setup_version_id=_required_text(payload, "setup_version_id"),
            research_snapshot_id=_required_text(payload, "research_snapshot_id"),
            decision_mode=_required_text(payload, "decision_mode"),
            formula_version=_required_text(payload, "formula_version"),
            feature_version=_required_text(payload, "feature_version"),
            application_version=_required_text(payload, "application_version"),
            random_seed=_required_int(payload, "random_seed"),
            maturity=_required_text(payload, "maturity"),
            warnings=tuple(warnings),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class StrategySpec:
    schema_version: str
    provenance: StrategySpecProvenance
    market: dict[str, Any]
    entry: dict[str, Any]
    exit: dict[str, Any]
    position: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StrategySpec:
        _require_mapping("StrategySpec payload", payload)
        schema_version = _required_text(payload, "schema_version")
        if schema_version != STRATEGY_SPEC_SCHEMA_VERSION:
            raise StrategySpecValidationError(
                f"schema_version is unsupported: {schema_version}"
            )
        market = _mapping_copy(payload, "market")
        entry = _mapping_copy(payload, "entry")
        exit_rules = _mapping_copy(payload, "exit")
        position = _mapping_copy(payload, "position")
        _validate_market(market)
        _validate_exit(exit_rules)
        _validate_position(position)
        _validate_entry(entry)
        return cls(
            schema_version=schema_version,
            provenance=StrategySpecProvenance.from_dict(payload["provenance"]),
            market=market,
            entry=entry,
            exit=exit_rules,
            position=position,
        )

    @classmethod
    def from_json(cls, value: str) -> StrategySpec:
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise StrategySpecValidationError(f"Invalid StrategySpec JSON: {exc}") from exc
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provenance": self.provenance.to_dict(),
            "market": deepcopy(self.market),
            "entry": deepcopy(self.entry),
            "exit": deepcopy(self.exit),
            "position": deepcopy(self.position),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def _require_mapping(name: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise StrategySpecValidationError(f"{name} must be a mapping")


def _mapping_copy(payload: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in payload:
        raise StrategySpecValidationError(f"StrategySpec payload missing {key}")
    value = payload[key]
    _require_mapping(key, value)
    return deepcopy(value)


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategySpecValidationError(f"{key} must be a non-empty string")
    return value


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StrategySpecValidationError(f"{key} must be an integer")
    return int(value)


def _finite_number(payload: dict[str, Any], key: str) -> float:
    try:
        number = float(payload.get(key))
    except (TypeError, ValueError) as exc:
        raise StrategySpecValidationError(f"{key} must be numeric") from exc
    if not math.isfinite(number):
        raise StrategySpecValidationError(f"{key} must be finite")
    return number


def _validate_market(market: dict[str, Any]) -> None:
    _required_text(market, "symbol")
    _required_text(market, "interval")
    start = _required_int(market, "data_start_utc_ms")
    end = _required_int(market, "data_end_utc_ms")
    if start > end:
        raise StrategySpecValidationError("market data range start must not be after end")


def _validate_entry(entry: dict[str, Any]) -> None:
    rule = entry.get("rule")
    _require_mapping("entry.rule", rule)
    _validate_rule_node(rule, path="entry.rule")


def _validate_rule_node(node: Any, *, path: str) -> None:
    _require_mapping(path, node)
    group_keys = [key for key in ("all", "any") if key in node]
    is_condition = "feature" in node
    if len(group_keys) + int(is_condition) != 1:
        raise StrategySpecValidationError(
            f"{path} must contain exactly one of all, any, or feature"
        )
    if group_keys:
        key = group_keys[0]
        children = node[key]
        if not isinstance(children, list) or not children:
            raise StrategySpecValidationError(f"{path}.{key} must be a non-empty list")
        for index, child in enumerate(children):
            _validate_rule_node(child, path=f"{path}.{key}[{index}]")
        return
    feature = _required_text(node, "feature")
    if _FEATURE_NAME.fullmatch(feature) is None:
        raise StrategySpecValidationError(f"entry feature has invalid name: {feature}")
    lower = feature.lower()
    if any(token in lower for token in FORBIDDEN_ENTRY_FEATURE_TOKENS):
        raise StrategySpecValidationError(
            f"entry feature is not allowed in backtestable rules: {feature}"
        )
    op = _required_text(node, "op")
    if op not in SUPPORTED_NUMERIC_OPERATORS:
        raise StrategySpecValidationError(f"entry operator is unsupported: {op}")
    _finite_number(node, "value")


def _validate_exit(exit_rules: dict[str, Any]) -> None:
    mode = _required_text(exit_rules, "mode")
    if mode != "tp_sl_timeout":
        raise StrategySpecValidationError(f"exit.mode is unsupported: {mode}")
    for key in ("take_profit_pct", "stop_loss_pct"):
        if _finite_number(exit_rules, key) < 0:
            raise StrategySpecValidationError(f"exit.{key} must be non-negative")
    max_holding = _required_int(exit_rules, "max_holding_bars")
    if max_holding <= 0:
        raise StrategySpecValidationError("exit.max_holding_bars must be positive")


def _validate_position(position: dict[str, Any]) -> None:
    direction = _required_text(position, "direction")
    if direction != "long_only":
        raise StrategySpecValidationError(f"position.direction is unsupported: {direction}")
    if position.get("allow_overlap_positions") is not False:
        raise StrategySpecValidationError("position.allow_overlap_positions must be False")
    cooldown = _required_int(position, "cooldown_bars")
    if cooldown < 0:
        raise StrategySpecValidationError("position.cooldown_bars must be non-negative")
    for key in ("notional_per_trade", "fee_bps", "slippage_bps"):
        number = _finite_number(position, key)
        if key == "notional_per_trade" and number <= 0:
            raise StrategySpecValidationError("position.notional_per_trade must be positive")
        if key != "notional_per_trade" and number < 0:
            raise StrategySpecValidationError(f"position.{key} must be non-negative")


__all__ = [
    "STRATEGY_SPEC_SCHEMA_VERSION",
    "StrategySpec",
    "StrategySpecProvenance",
    "StrategySpecValidationError",
]
