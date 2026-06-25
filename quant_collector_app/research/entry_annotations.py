from __future__ import annotations

import hashlib
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any


class HumanDecision(str, Enum):
    ENTRY = "ENTRY"
    REJECT = "REJECT"
    UNCERTAIN = "UNCERTAIN"
    UNLABELED = "UNLABELED"


class DecisionTiming(str, Enum):
    CURRENT_BAR_CLOSE = "CURRENT_BAR_CLOSE"
    NEXT_BAR_CONFIRMATION = "NEXT_BAR_CONFIRMATION"


class EntryReasonTag(str, Enum):
    PRIOR_DOWNTREND = "prior_downtrend"
    VOLUME_CLIMAX = "volume_climax"
    LONG_LOWER_SHADOW = "long_lower_shadow"
    LOWER_SHADOW = "lower_shadow"
    VOLUME_SPIKE = "volume_spike"
    RANGE_EXPANSION = "range_expansion"
    BULLISH_CONFIRMATION = "bullish_confirmation"
    INSUFFICIENT_CONFIRMATION = "insufficient_confirmation"
    RECLAIM_RECENT_LOW = "reclaim_recent_low"
    TREND_CONTEXT = "trend_context"
    WEAK_VOLUME = "weak_volume"
    NO_CONFIRMATION = "no_confirmation"
    CHOPPY_CONTEXT = "choppy_context"
    TOO_LATE = "too_late"
    RISK_TOO_WIDE = "risk_too_wide"
    MIXED_SETUP = "mixed_setup"
    MANUAL_REVIEW = "manual_review"
    DATA_QUALITY_WARNING = "data_quality_warning"
    OTHER = "other"


FORBIDDEN_NAME_TOKENS = ("buy", "sell", "signal")
FORBIDDEN_OUTCOME_TOKENS = ("future_return", "fwd_ret", "mfe", "mae", "hit_tp", "hit_sl")
DEFAULT_ANNOTATION_VERSION = "entry_annotations_v1"
ALLOWED_REASON_TAGS = frozenset(tag.value for tag in EntryReasonTag)


@dataclass(frozen=True)
class EntryAnnotation:
    annotation_id: str
    session_id: str
    symbol: str
    interval: str
    bar_index: int | None
    bar_time: str | None
    human_decision: HumanDecision
    confidence: int | None
    reason_tags: list[str]
    note: str
    decision_timing: DecisionTiming
    created_at: str
    app_version: str
    observation_id: str | None = None
    setup_bar_index: int | None = None
    decision_bar_index: int | None = None
    setup_bar_time: str | None = None
    decision_bar_time: str | None = None
    annotation_version: str = DEFAULT_ANNOTATION_VERSION
    updated_at: str | None = None
    is_active: bool = True
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        decision = _human_decision(self.human_decision)
        timing = _decision_timing(self.decision_timing)
        bar_index, setup_index, decision_index = _resolve_bar_indexes(
            self.bar_index,
            self.setup_bar_index,
            self.decision_bar_index,
            timing,
            decision,
        )
        bar_time, setup_time, decision_time = _resolve_bar_times(
            self.bar_time,
            self.setup_bar_time,
            self.decision_bar_time,
            timing,
        )
        object.__setattr__(self, "human_decision", decision)
        object.__setattr__(self, "decision_timing", timing)
        object.__setattr__(self, "bar_index", bar_index)
        object.__setattr__(self, "setup_bar_index", setup_index)
        object.__setattr__(self, "decision_bar_index", decision_index)
        object.__setattr__(self, "bar_time", bar_time)
        object.__setattr__(self, "setup_bar_time", setup_time)
        object.__setattr__(self, "decision_bar_time", decision_time)
        object.__setattr__(self, "confidence", _confidence(self.confidence, decision))
        object.__setattr__(self, "reason_tags", _reason_tags(self.reason_tags))
        object.__setattr__(self, "annotation_version", _annotation_version(self.annotation_version))
        object.__setattr__(self, "updated_at", self.updated_at or self.created_at)
        object.__setattr__(self, "is_active", _is_active(self.is_active))
        object.__setattr__(self, "superseded_by", _optional_text(self.superseded_by, "superseded_by"))
        object.__setattr__(self, "observation_id", _optional_text(self.observation_id, "observation_id"))
        _validate_required_text(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "observation_id": self.observation_id,
            "session_id": self.session_id,
            "symbol": self.symbol,
            "interval": self.interval,
            "bar_index": self.bar_index,
            "bar_time": self.bar_time,
            "setup_bar_index": self.setup_bar_index,
            "decision_bar_index": self.decision_bar_index,
            "setup_bar_time": self.setup_bar_time,
            "decision_bar_time": self.decision_bar_time,
            "human_decision": self.human_decision.value,
            "confidence": self.confidence,
            "reason_tags": list(self.reason_tags),
            "note": self.note,
            "decision_timing": self.decision_timing.value,
            "annotation_version": self.annotation_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_active": self.is_active,
            "superseded_by": self.superseded_by,
            "app_version": self.app_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EntryAnnotation:
        if not isinstance(payload, dict):
            raise ValueError("EntryAnnotation payload must be a mapping")
        validate_annotation_payload(payload)
        field_names = {field.name for field in fields(cls)}
        extras = sorted(set(payload) - field_names)
        if extras:
            raise ValueError(f"Unsupported annotation fields: {extras}")
        return cls(**{name: payload[name] for name in field_names if name in payload})


def build_entry_annotation_id(
    *,
    session_id: str,
    symbol: str,
    interval: str,
    decision_bar_index: int | None,
    observation_id: str | None = None,
    created_at: str | None = None,
) -> str:
    """Build a stable annotation id without human_decision.

    observation_id is preferred when available. Legacy data without
    observation_id falls back to session/symbol/interval/decision_bar_index;
    created_at is only used when the bar key is missing.
    """
    stable_key = observation_id or str(decision_bar_index if decision_bar_index is not None else created_at or "")
    payload = "|".join([str(session_id or ""), str(symbol or ""), str(interval or ""), str(stable_key)])
    return "entry_ann_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def validate_annotation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("EntryAnnotation payload must be a mapping")
    _reject_forbidden_names(payload)
    return payload


def _human_decision(value: HumanDecision | str) -> HumanDecision:
    try:
        return value if isinstance(value, HumanDecision) else HumanDecision(str(value).upper())
    except ValueError as exc:
        raise ValueError(f"Unsupported human_decision: {value}") from exc


def _decision_timing(value: DecisionTiming | str | None) -> DecisionTiming:
    if value is None or value == "":
        raise ValueError("decision_timing is required")
    try:
        return value if isinstance(value, DecisionTiming) else DecisionTiming(str(value).upper())
    except ValueError as exc:
        raise ValueError(f"Unsupported decision_timing: {value}") from exc


def _bar_index(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bar_index must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("bar_index must be an integer") from exc


def _resolve_bar_indexes(
    legacy_bar_index: Any,
    setup_bar_index: Any,
    decision_bar_index: Any,
    timing: DecisionTiming,
    decision: HumanDecision,
) -> tuple[int | None, int | None, int | None]:
    legacy = _bar_index(legacy_bar_index)
    setup = _bar_index(setup_bar_index)
    decision_index = _bar_index(decision_bar_index)
    if decision_index is None:
        decision_index = legacy
    if legacy is None:
        legacy = decision_index
    if timing is DecisionTiming.CURRENT_BAR_CLOSE:
        if setup is None:
            setup = decision_index
        if decision_index is None:
            decision_index = setup
        if setup is not None and decision_index is not None and setup != decision_index:
            raise ValueError("CURRENT_BAR_CLOSE requires setup_bar_index == decision_bar_index")
    else:
        if setup is None and decision_index is not None:
            setup = decision_index - 1
        if decision is not HumanDecision.UNLABELED and (setup is None or decision_index is None):
            raise ValueError("NEXT_BAR_CONFIRMATION annotations require setup_bar_index and decision_bar_index")
        if setup is not None and decision_index is not None and setup >= decision_index:
            raise ValueError("NEXT_BAR_CONFIRMATION requires setup_bar_index < decision_bar_index")
    if decision is not HumanDecision.UNLABELED and decision_index is None:
        raise ValueError("ENTRY, REJECT and UNCERTAIN annotations require decision_bar_index")
    return decision_index, setup, decision_index


def _resolve_bar_times(
    legacy_bar_time: Any,
    setup_bar_time: Any,
    decision_bar_time: Any,
    timing: DecisionTiming,
) -> tuple[str | None, str | None, str | None]:
    legacy = _optional_text(legacy_bar_time, "bar_time")
    setup = _optional_text(setup_bar_time, "setup_bar_time")
    decision = _optional_text(decision_bar_time, "decision_bar_time")
    if decision is None:
        decision = legacy
    if timing is DecisionTiming.CURRENT_BAR_CLOSE and setup is None:
        setup = decision
    if legacy is None:
        legacy = decision
    return legacy, setup, decision


def _confidence(value: Any, decision: HumanDecision) -> int | None:
    if value is None or value == "":
        if decision is HumanDecision.UNLABELED:
            return None
        raise ValueError("confidence is required for labeled annotations")
    if isinstance(value, bool):
        raise ValueError("confidence must be between 1 and 5")
    try:
        confidence = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be between 1 and 5") from exc
    if confidence < 1 or confidence > 5:
        raise ValueError("confidence must be between 1 and 5")
    return confidence


def _reason_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("reason_tags must be list[str] or an empty list")
    normalized = [item.value if isinstance(item, EntryReasonTag) else str(item).strip().lower() for item in value]
    _reject_forbidden_names({tag: None for tag in normalized})
    unsupported = [tag for tag in normalized if tag not in ALLOWED_REASON_TAGS]
    if unsupported:
        raise ValueError(f"Unsupported reason_tags: {unsupported}")
    return normalized


def _annotation_version(value: Any) -> str:
    text = str(value or DEFAULT_ANNOTATION_VERSION).strip()
    if not text:
        raise ValueError("annotation_version is required")
    return text


def _is_active(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "inactive"}
    return bool(value)


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or None")
    return value


def _validate_required_text(annotation: EntryAnnotation) -> None:
    for name in ("annotation_id", "session_id", "symbol", "interval", "annotation_version", "created_at", "updated_at", "app_version"):
        value = getattr(annotation, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
    if not isinstance(annotation.note, str):
        raise ValueError("note must be a string")


def _reject_forbidden_names(payload: dict[str, Any]) -> None:
    for key in payload:
        name = str(key).lower()
        if any(token in name for token in FORBIDDEN_NAME_TOKENS):
            raise ValueError(f"Trading-signal naming is not allowed in entry annotation: {key}")
        if any(token in name for token in FORBIDDEN_OUTCOME_TOKENS):
            raise ValueError(f"Future outcome field is not allowed in entry annotation: {key}")


__all__ = [
    "ALLOWED_REASON_TAGS",
    "DEFAULT_ANNOTATION_VERSION",
    "DecisionTiming",
    "EntryAnnotation",
    "EntryReasonTag",
    "HumanDecision",
    "build_entry_annotation_id",
    "validate_annotation_payload",
]
