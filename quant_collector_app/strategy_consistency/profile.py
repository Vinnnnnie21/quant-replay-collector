from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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
        strategy_id="reversal_long_after_drop",
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


def _profile_from_dict(data: dict[str, Any]) -> StrategyProfile:
    default = default_reversal_long_profile()
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


def load_strategy_profile(path: Path) -> StrategyProfile:
    path = Path(path)
    if not path.exists():
        return default_reversal_long_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return _profile_from_dict(data if isinstance(data, dict) else {})


def save_strategy_profile(profile: StrategyProfile, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile_to_dict(profile), ensure_ascii=False, indent=2), encoding="utf-8")
