from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROFILE_STATUS_UNDECLARED = "UNDECLARED"
PROFILE_STATUS_DEFAULT_REVERSAL_LONG_TEMPLATE = "DEFAULT_REVERSAL_LONG_TEMPLATE"
PROFILE_STATUS_CUSTOM = "CUSTOM"
DEFAULT_REVERSAL_LONG_STRATEGY_ID = "reversal_long_after_drop"


@dataclass
class StrategyProfile:
    strategy_id: str = "generic_strategy"
    name: str = "Generic Strategy"
    description: str = ""
    allowed_sides: list[str] | None = None
    required_entry_tags: list[str] = field(default_factory=list)
    optional_entry_tags: list[str] = field(default_factory=list)
    forbidden_tags: list[str] = field(default_factory=list)
    max_holding_bars: int | None = None
    min_holding_bars: int | None = None
    risk_model: str | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    allowed_intervals: list[str] | None = None
    allowed_symbols: list[str] | None = None
    allowed_regimes: list[str] | None = None
    exit_rules_required: bool = True
    # Compatibility fields retained for existing saved profiles and UI readers.
    expected_direction: str | None = None
    expected_market_state: str = "OTHER"
    required_tags: list[str] = field(default_factory=list)
    expected_entry_features: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_missing_note_pct: float = 40.0
    min_sample_count: int = 30

    def __post_init__(self) -> None:
        if not self.required_entry_tags and self.required_tags:
            self.required_entry_tags = list(self.required_tags)
        if not self.required_tags and self.required_entry_tags:
            self.required_tags = list(self.required_entry_tags)
        if self.allowed_sides is None and self.expected_direction:
            mapping = {
                "LONG_ONLY": ["LONG"],
                "SHORT_ONLY": ["SHORT"],
                "BOTH": ["LONG", "SHORT"],
            }
            self.allowed_sides = mapping.get(str(self.expected_direction).upper())
        if self.allowed_sides is not None:
            self.allowed_sides = [str(side).upper() for side in self.allowed_sides]
            if self.expected_direction is None:
                sides = set(self.allowed_sides)
                self.expected_direction = (
                    "LONG_ONLY" if sides == {"LONG"} else "SHORT_ONLY" if sides == {"SHORT"} else "BOTH"
                )


def default_reversal_long_profile() -> StrategyProfile:
    return StrategyProfile(
        strategy_id=DEFAULT_REVERSAL_LONG_STRATEGY_ID,
        name="大跌后的反转 K 线做多",
        description="用于审计人工标注样本是否集中在大跌后的反转做多逻辑。",
        allowed_sides=["LONG"],
        required_entry_tags=["长下影", "放量"],
        optional_entry_tags=["恐慌针", "跌破前低后收回", "深V反转"],
        risk_model="fixed_stop_take",
        stop_loss_pct=1.0,
        take_profit_pct=2.0,
        max_holding_bars=20,
        expected_direction="LONG_ONLY",
        expected_market_state="AFTER_DROP",
        expected_entry_features={
            "pre_ret_20": {"op": "<=", "value": -0.02},
            "event_lower_wick_ratio": {"op": ">=", "value": 0.3},
        },
        max_missing_note_pct=40.0,
        min_sample_count=30,
    )


def profile_to_dict(profile: StrategyProfile) -> dict[str, Any]:
    return asdict(profile)


def strategy_profile_status(profile: StrategyProfile | None) -> str:
    if profile is None:
        return PROFILE_STATUS_UNDECLARED
    if profile.strategy_id == DEFAULT_REVERSAL_LONG_STRATEGY_ID:
        return PROFILE_STATUS_DEFAULT_REVERSAL_LONG_TEMPLATE
    return PROFILE_STATUS_CUSTOM


def strategy_profile_to_storage_row(
    profile: StrategyProfile,
    *,
    profile_id: str | None = None,
    profile_version: str = "1",
    mode: str | None = None,
    selected_label: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    return {
        "profile_id": profile_id or profile.strategy_id,
        "profile_version": str(profile_version),
        "name": profile.name,
        "mode": mode or strategy_profile_status(profile),
        "allowed_sides_json": json.dumps(profile.allowed_sides, ensure_ascii=False),
        "allowed_symbols_json": json.dumps(profile.allowed_symbols, ensure_ascii=False),
        "allowed_intervals_json": json.dumps(profile.allowed_intervals, ensure_ascii=False),
        "entry_setup_rules_json": json.dumps(profile.expected_entry_features, ensure_ascii=False),
        "entry_filter_rules_json": json.dumps(
            {
                "required_entry_tags": profile.required_entry_tags,
                "optional_entry_tags": profile.optional_entry_tags,
                "forbidden_tags": profile.forbidden_tags,
                "allowed_regimes": profile.allowed_regimes,
            },
            ensure_ascii=False,
        ),
        "risk_rules_json": json.dumps(
            {
                "risk_model": profile.risk_model,
                "stop_loss_pct": profile.stop_loss_pct,
                "take_profit_pct": profile.take_profit_pct,
            },
            ensure_ascii=False,
        ),
        "exit_rules_json": json.dumps(
            {
                "exit_rules_required": profile.exit_rules_required,
                "min_holding_bars": profile.min_holding_bars,
                "max_holding_bars": profile.max_holding_bars,
            },
            ensure_ascii=False,
        ),
        "invalidation_rules_json": json.dumps({}, ensure_ascii=False),
        "expected_holding_bars": profile.max_holding_bars,
        "selected_label": selected_label,
        # Preserve existing JSON-file fields while SQLite profile fields mature.
        "profile_payload_json": json.dumps(profile_to_dict(profile), ensure_ascii=False),
        "created_at": created_at or timestamp,
        "updated_at": updated_at or timestamp,
    }


def strategy_profile_from_storage_row(row: dict[str, Any] | None) -> StrategyProfile | None:
    if not row:
        return None
    try:
        payload = json.loads(row.get("profile_payload_json") or "")
    except (TypeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and payload:
        return _profile_from_dict(payload)

    def load_json(field_name: str, default):
        try:
            value = json.loads(row.get(field_name) or "null")
        except (TypeError, json.JSONDecodeError):
            return default
        return default if value is None else value

    entry_filters = load_json("entry_filter_rules_json", {})
    risk_rules = load_json("risk_rules_json", {})
    exit_rules = load_json("exit_rules_json", {})
    return _profile_from_dict(
        {
            "strategy_id": row.get("profile_id") or "generic_strategy",
            "name": row.get("name") or "Generic Strategy",
            "allowed_sides": load_json("allowed_sides_json", None),
            "allowed_symbols": load_json("allowed_symbols_json", None),
            "allowed_intervals": load_json("allowed_intervals_json", None),
            "expected_entry_features": load_json("entry_setup_rules_json", {}),
            "required_entry_tags": entry_filters.get("required_entry_tags", []),
            "optional_entry_tags": entry_filters.get("optional_entry_tags", []),
            "forbidden_tags": entry_filters.get("forbidden_tags", []),
            "allowed_regimes": entry_filters.get("allowed_regimes"),
            "risk_model": risk_rules.get("risk_model"),
            "stop_loss_pct": risk_rules.get("stop_loss_pct"),
            "take_profit_pct": risk_rules.get("take_profit_pct"),
            "exit_rules_required": exit_rules.get("exit_rules_required", True),
            "min_holding_bars": exit_rules.get("min_holding_bars"),
            "max_holding_bars": exit_rules.get("max_holding_bars", row.get("expected_holding_bars")),
        }
    )


def _profile_from_dict(data: dict[str, Any]) -> StrategyProfile:
    default = StrategyProfile()
    values = profile_to_dict(default)
    values.update({key: value for key, value in (data or {}).items() if key in values})
    if "allowed_sides" not in data and "expected_direction" in data:
        values["allowed_sides"] = None
    if "required_entry_tags" not in data and "required_tags" in data:
        values["required_entry_tags"] = []
    for field_name in (
        "allowed_sides",
        "required_entry_tags",
        "optional_entry_tags",
        "required_tags",
        "forbidden_tags",
        "allowed_intervals",
        "allowed_symbols",
        "allowed_regimes",
    ):
        if values.get(field_name) is not None:
            values[field_name] = list(values.get(field_name) or [])
    values["expected_entry_features"] = dict(values.get("expected_entry_features") or {})
    for field_name in ("max_missing_note_pct", "stop_loss_pct", "take_profit_pct"):
        if values.get(field_name) is not None:
            try:
                values[field_name] = float(values[field_name])
            except (TypeError, ValueError):
                values[field_name] = None if field_name != "max_missing_note_pct" else 40.0
    for field_name in ("min_sample_count", "max_holding_bars", "min_holding_bars"):
        if values.get(field_name) is not None:
            try:
                values[field_name] = int(values[field_name])
            except (TypeError, ValueError):
                values[field_name] = None if field_name != "min_sample_count" else 30
    return StrategyProfile(**values)


def load_strategy_profile(path: Path) -> StrategyProfile | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _profile_from_dict(data) if isinstance(data, dict) and data else None


def save_strategy_profile(profile: StrategyProfile, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile_to_dict(profile), ensure_ascii=False, indent=2), encoding="utf-8")
