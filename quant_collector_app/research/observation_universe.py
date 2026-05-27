from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any


VALID_USER_ACTIONS = frozenset(
    {"OPEN_LONG", "OPEN_SHORT", "CLOSE_LONG", "CLOSE_SHORT", "HOLD", "NO_ACTION"}
)
VALID_SOURCE_TYPES = frozenset(
    {"USER_TRADE", "USER_EVENT", "AUTO_CANDIDATE", "SCHEDULED_BAR", "MATCHED_CONTROL"}
)
USER_TRADE_ACTIONS = frozenset({"OPEN_LONG", "OPEN_SHORT", "CLOSE_LONG", "CLOSE_SHORT"})


def validate_user_action(user_action: str) -> str:
    value = str(user_action or "").upper()
    if value not in VALID_USER_ACTIONS:
        raise ValueError(f"Unsupported user_action: {user_action}")
    return value


def validate_source_type(source_type: str) -> str:
    value = str(source_type or "").upper()
    if value not in VALID_SOURCE_TYPES:
        raise ValueError(f"Unsupported source_type: {source_type}")
    return value


def build_observation_sample_id(
    session_id: str,
    symbol: str,
    interval: str,
    bar_index: int,
    source_type: str,
) -> str:
    source = validate_source_type(source_type)
    payload = "|".join(
        [str(session_id), str(symbol).upper(), str(interval), str(int(bar_index)), source]
    )
    return "obs_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _created_at(value: str | None) -> str:
    return value or datetime.now(UTC).isoformat(timespec="seconds")


def _create_observation(
    *,
    session_id: str,
    profile_id: str | None,
    source_type: str,
    symbol: str,
    interval: str,
    bar_index: int,
    event_time_bjt: str | None,
    user_action: str,
    side: str | None,
    linked_trade_id: str | None,
    linked_event_id: str | None,
    is_user_trade: int,
    is_candidate: int,
    is_matched_control: int,
    created_at: str | None,
) -> dict[str, Any]:
    source = validate_source_type(source_type)
    action = validate_user_action(user_action)
    return {
        "sample_id": build_observation_sample_id(session_id, symbol, interval, bar_index, source),
        "session_id": str(session_id),
        "profile_id": profile_id,
        "source_type": source,
        "symbol": str(symbol).upper(),
        "interval": str(interval),
        "bar_index": int(bar_index),
        "event_time_bjt": event_time_bjt,
        "user_action": action,
        "side": str(side).upper() if side else None,
        "linked_trade_id": linked_trade_id,
        "linked_event_id": linked_event_id,
        "is_user_trade": int(bool(is_user_trade)),
        "is_candidate": int(bool(is_candidate)),
        "is_matched_control": int(bool(is_matched_control)),
        "created_at": _created_at(created_at),
    }


def create_user_trade_observation(
    *,
    session_id: str,
    symbol: str,
    interval: str,
    bar_index: int,
    user_action: str,
    side: str | None = None,
    profile_id: str | None = None,
    event_time_bjt: str | None = None,
    linked_trade_id: str | None = None,
    linked_event_id: str | None = None,
    source_type: str = "USER_TRADE",
    created_at: str | None = None,
) -> dict[str, Any]:
    action = validate_user_action(user_action)
    if action not in USER_TRADE_ACTIONS:
        raise ValueError(f"User trade observation requires an executed action: {user_action}")
    inferred_side = "LONG" if action.endswith("_LONG") else "SHORT"
    normalized_side = str(side).upper() if side else inferred_side
    if normalized_side != inferred_side:
        raise ValueError(f"side {side} does not match user_action {action}")
    return _create_observation(
        session_id=session_id,
        profile_id=profile_id,
        source_type=source_type,
        symbol=symbol,
        interval=interval,
        bar_index=bar_index,
        event_time_bjt=event_time_bjt,
        user_action=action,
        side=normalized_side,
        linked_trade_id=linked_trade_id,
        linked_event_id=linked_event_id,
        is_user_trade=1,
        is_candidate=0,
        is_matched_control=0,
        created_at=created_at,
    )


def create_no_action_observation(
    *,
    session_id: str,
    symbol: str,
    interval: str,
    bar_index: int,
    profile_id: str | None = None,
    event_time_bjt: str | None = None,
    source_type: str = "SCHEDULED_BAR",
    created_at: str | None = None,
) -> dict[str, Any]:
    return _create_observation(
        session_id=session_id,
        profile_id=profile_id,
        source_type=source_type,
        symbol=symbol,
        interval=interval,
        bar_index=bar_index,
        event_time_bjt=event_time_bjt,
        user_action="NO_ACTION",
        side=None,
        linked_trade_id=None,
        linked_event_id=None,
        is_user_trade=0,
        is_candidate=0,
        is_matched_control=0,
        created_at=created_at,
    )


def create_auto_candidate_observation(
    *,
    session_id: str,
    symbol: str,
    interval: str,
    bar_index: int,
    profile_id: str | None = None,
    event_time_bjt: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    return _create_observation(
        session_id=session_id,
        profile_id=profile_id,
        source_type="AUTO_CANDIDATE",
        symbol=symbol,
        interval=interval,
        bar_index=bar_index,
        event_time_bjt=event_time_bjt,
        user_action="NO_ACTION",
        side=None,
        linked_trade_id=None,
        linked_event_id=None,
        is_user_trade=0,
        is_candidate=1,
        is_matched_control=0,
        created_at=created_at,
    )


__all__ = [
    "VALID_SOURCE_TYPES",
    "VALID_USER_ACTIONS",
    "build_observation_sample_id",
    "create_auto_candidate_observation",
    "create_no_action_observation",
    "create_user_trade_observation",
    "validate_source_type",
    "validate_user_action",
]
