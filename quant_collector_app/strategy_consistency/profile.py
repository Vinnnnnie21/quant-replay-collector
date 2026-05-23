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
    expected_direction: str = "BOTH"
    expected_market_state: str = "OTHER"
    required_tags: list[str] = field(default_factory=list)
    forbidden_tags: list[str] = field(default_factory=list)
    expected_entry_features: dict[str, dict[str, Any]] = field(default_factory=dict)
    max_missing_note_pct: float = 40.0
    min_sample_count: int = 30


def default_reversal_long_profile() -> StrategyProfile:
    return StrategyProfile(
        strategy_id="reversal_long_after_drop",
        name="大跌后的反转 K 线做多",
        description="用于审计人工标注样本是否集中在大跌后的反转做多逻辑。",
        expected_direction="LONG_ONLY",
        expected_market_state="AFTER_DROP",
        required_tags=["长下影", "放量", "恐慌针", "跌破前低后收回", "深V反转"],
        forbidden_tags=[],
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
    values.update({k: v for k, v in (data or {}).items() if k in values})
    values["required_tags"] = list(values.get("required_tags") or [])
    values["forbidden_tags"] = list(values.get("forbidden_tags") or [])
    values["expected_entry_features"] = dict(values.get("expected_entry_features") or {})
    try:
        values["max_missing_note_pct"] = float(values.get("max_missing_note_pct", 40.0))
    except Exception:
        values["max_missing_note_pct"] = 40.0
    try:
        values["min_sample_count"] = int(values.get("min_sample_count", 30))
    except Exception:
        values["min_sample_count"] = 30
    return StrategyProfile(**values)


def load_strategy_profile(path: Path) -> StrategyProfile:
    p = Path(path)
    if not p.exists():
        return default_reversal_long_profile()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return _profile_from_dict(data if isinstance(data, dict) else {})


def save_strategy_profile(profile: StrategyProfile, path: Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile_to_dict(profile), ensure_ascii=False, indent=2), encoding="utf-8")
