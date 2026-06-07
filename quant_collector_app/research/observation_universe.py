from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd


VALID_USER_ACTIONS = frozenset(
    {"OPEN_LONG", "OPEN_SHORT", "CLOSE_LONG", "CLOSE_SHORT", "HOLD", "NO_ACTION"}
)
VALID_SOURCE_TYPES = frozenset(
    {"USER_TRADE", "USER_EVENT", "AUTO_CANDIDATE", "SCHEDULED_BAR", "MATCHED_CONTROL"}
)
USER_TRADE_ACTIONS = frozenset({"OPEN_LONG", "OPEN_SHORT", "CLOSE_LONG", "CLOSE_SHORT"})
LONG_DEEP_V_PROFILE_ID = "LONG_DEEP_V_REVERSAL"


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


def create_matched_control_observation(
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
        source_type="MATCHED_CONTROL",
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
        is_matched_control=1,
        created_at=created_at,
    )


def _profile_id_from_strategy(
    strategy_profile: Any = None,
    strategy_id: str | None = None,
) -> str | None:
    if strategy_id:
        return str(strategy_id)
    if strategy_profile is None:
        return None
    if isinstance(strategy_profile, dict):
        return (
            strategy_profile.get("profile_id")
            or strategy_profile.get("strategy_id")
            or strategy_profile.get("name")
        )
    return (
        getattr(strategy_profile, "profile_id", None)
        or getattr(strategy_profile, "strategy_id", None)
        or getattr(strategy_profile, "name", None)
    )


def _event_time_from_row(row: pd.Series) -> str | None:
    for column in ("event_time_bjt", "open_time_bjt", "open_time", "timestamp"):
        if column in row and pd.notna(row[column]):
            return str(row[column])
    return None


def _finite_number(value: Any) -> float | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return None
    number = float(number)
    return number if np.isfinite(number) else None


def _deep_v_candidate_from_visible_history(
    ordered: pd.DataFrame,
    position: int,
    *,
    pre_ret_threshold: float,
    volume_zscore_threshold: float,
    volume_ratio_threshold: float,
    lower_wick_ratio_threshold: float,
    reclaim_lookback: int,
) -> bool:
    if position < max(20, reclaim_lookback, 10):
        return False
    current = ordered.iloc[position]
    prior10 = ordered.iloc[position - 10 : position]
    prior20 = ordered.iloc[position - 20 : position]
    if prior10.empty or prior20.empty:
        return False

    current_volume = _finite_number(current.get("volume"))
    current_open = _finite_number(current.get("open"))
    current_high = _finite_number(current.get("high"))
    current_low = _finite_number(current.get("low"))
    current_close = _finite_number(current.get("close"))
    first_close = _finite_number(prior10.iloc[0].get("close"))
    previous_close = _finite_number(prior10.iloc[-1].get("close"))
    if None in {
        current_volume,
        current_open,
        current_high,
        current_low,
        current_close,
        first_close,
        previous_close,
    }:
        return False
    if first_close == 0 or current_high <= current_low:
        return False

    pre_ret_10 = previous_close / first_close - 1.0
    prior_volume = pd.to_numeric(prior20["volume"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    prior_volume = prior_volume.dropna()
    if prior_volume.empty:
        return False
    volume_mean = float(prior_volume.mean())
    volume_std = float(prior_volume.std(ddof=0))
    volume_ratio = current_volume / volume_mean if volume_mean > 0 else 0.0
    volume_zscore = (current_volume - volume_mean) / volume_std if volume_std > 0 else 0.0

    candle_range = current_high - current_low
    lower_wick = max(min(current_open, current_close) - current_low, 0.0)
    lower_wick_ratio = lower_wick / candle_range if candle_range > 0 else 0.0

    reclaim_history = ordered.iloc[max(0, position - int(reclaim_lookback)) : position]
    previous_low = pd.to_numeric(reclaim_history["low"], errors="coerce").dropna().min()
    reclaim_prev_low = bool(
        pd.notna(previous_low)
        and current_low < float(previous_low)
        and current_close > float(previous_low)
    )

    volume_ok = volume_zscore >= float(volume_zscore_threshold) or volume_ratio >= float(volume_ratio_threshold)
    reversal_shape_ok = lower_wick_ratio >= float(lower_wick_ratio_threshold) or reclaim_prev_low
    return bool(pre_ret_10 < float(pre_ret_threshold) and volume_ok and reversal_shape_ok)


def _action_side(user_action: str) -> str | None:
    action = validate_user_action(user_action)
    if action.endswith("_LONG"):
        return "LONG"
    if action.endswith("_SHORT"):
        return "SHORT"
    return None


def generate_deep_v_observation_universe(
    klines: pd.DataFrame,
    *,
    session_id: str,
    symbol: str,
    interval: str,
    strategy_profile: Any = None,
    strategy_id: str | None = None,
    user_actions_by_bar: dict[int, str] | None = None,
    created_at: str | None = None,
    pre_ret_threshold: float = 0.0,
    volume_zscore_threshold: float = 1.0,
    volume_ratio_threshold: float = 1.5,
    lower_wick_ratio_threshold: float = 0.45,
    reclaim_lookback: int = 20,
) -> list[dict[str, Any]]:
    """Build a deterministic observation universe for LONG_DEEP_V_REVERSAL research.

    The scan only uses each bar and its previous OHLCV history. It deliberately
    ignores future/outcome columns if they exist in the input frame.
    """
    required = {"open", "high", "low", "close", "volume"}
    if not isinstance(klines, pd.DataFrame) or not required <= set(klines.columns):
        raise ValueError(f"klines requires columns: {sorted(required)}")
    if klines.empty:
        return []

    profile_id = _profile_id_from_strategy(strategy_profile, strategy_id) or LONG_DEEP_V_PROFILE_ID
    actions_by_bar = {int(key): validate_user_action(value) for key, value in (user_actions_by_bar or {}).items()}
    ordered = klines.copy()
    if "bar_index" not in ordered.columns:
        ordered["bar_index"] = range(len(ordered))
    ordered = ordered.sort_values("bar_index", kind="stable").reset_index(drop=True)

    observations: list[dict[str, Any]] = []
    for position, row in ordered.iterrows():
        bar_index = int(row["bar_index"])
        if position < max(20, int(reclaim_lookback), 10):
            continue
        event_time_bjt = _event_time_from_row(row)
        is_candidate = _deep_v_candidate_from_visible_history(
            ordered,
            position,
            pre_ret_threshold=pre_ret_threshold,
            volume_zscore_threshold=volume_zscore_threshold,
            volume_ratio_threshold=volume_ratio_threshold,
            lower_wick_ratio_threshold=lower_wick_ratio_threshold,
            reclaim_lookback=reclaim_lookback,
        )
        user_action = actions_by_bar.get(bar_index, "NO_ACTION")
        if user_action in USER_TRADE_ACTIONS:
            observations.append(
                _create_observation(
                    session_id=session_id,
                    profile_id=profile_id,
                    source_type="USER_TRADE",
                    symbol=symbol,
                    interval=interval,
                    bar_index=bar_index,
                    event_time_bjt=event_time_bjt,
                    user_action=user_action,
                    side=_action_side(user_action),
                    linked_trade_id=None,
                    linked_event_id=None,
                    is_user_trade=1,
                    is_candidate=int(is_candidate),
                    is_matched_control=0,
                    created_at=created_at,
                )
            )
            continue
        observations.append(
            _create_observation(
                session_id=session_id,
                profile_id=profile_id,
                source_type="AUTO_CANDIDATE" if is_candidate else "SCHEDULED_BAR",
                symbol=symbol,
                interval=interval,
                bar_index=bar_index,
                event_time_bjt=event_time_bjt,
                user_action=user_action,
                side=None,
                linked_trade_id=None,
                linked_event_id=None,
                is_user_trade=0,
                is_candidate=int(is_candidate),
                is_matched_control=0,
                created_at=created_at,
            )
        )
    return observations


__all__ = [
    "VALID_SOURCE_TYPES",
    "VALID_USER_ACTIONS",
    "build_observation_sample_id",
    "create_auto_candidate_observation",
    "create_matched_control_observation",
    "create_no_action_observation",
    "create_user_trade_observation",
    "generate_deep_v_observation_universe",
    "validate_source_type",
    "validate_user_action",
]
