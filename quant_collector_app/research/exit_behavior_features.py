from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

from .entry_behavior_model import (
    EXIT_BEHAVIOR_FEATURES,
    BehaviorFeatureValue,
)
from .entry_context_features import EntryStructuralFeatureSnapshot


EXIT_POSITION_STATE_FEATURE_VERSION = "exit-position-state-v1.6"


@dataclass(frozen=True, slots=True)
class ExitPositionStateSnapshot:
    unrealized_atr: float
    mfe_atr: float
    mae_atr: float
    giveback_atr: float
    range_position: float | None
    holding_bars: int
    bars_since_mfe: int
    bars_since_mae: int
    take_profit_status: str = "NOT_SET"
    take_profit_distance_atr: float | None = None
    stop_loss_status: str = "NOT_SET"
    stop_loss_distance_atr: float | None = None

    def __post_init__(self) -> None:
        for name in (
            "unrealized_atr",
            "mfe_atr",
            "mae_atr",
            "giveback_atr",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.range_position is not None:
            range_position = _finite(
                self.range_position,
                "range_position",
            )
            if not 0.0 <= range_position <= 1.0:
                raise ValueError("range_position must be between 0 and 1")
            object.__setattr__(self, "range_position", range_position)
        holding_bars = _path_count(self.holding_bars, "holding_bars")
        if holding_bars < 1:
            raise ValueError("holding_bars must be positive")
        object.__setattr__(self, "holding_bars", holding_bars)
        for name in ("bars_since_mfe", "bars_since_mae"):
            count = _path_count(getattr(self, name), name)
            if count >= holding_bars:
                raise ValueError(f"{name} must be less than holding_bars")
            object.__setattr__(self, name, count)
        for prefix in ("take_profit", "stop_loss"):
            raw_status = getattr(self, f"{prefix}_status")
            status = str(getattr(raw_status, "value", raw_status) or "").upper()
            if status not in {"SET", "NOT_SET", "MISSING"}:
                raise ValueError(f"{prefix}_status must be SET, NOT_SET, or MISSING")
            distance = getattr(self, f"{prefix}_distance_atr")
            if status == "SET":
                number = _finite(distance, f"{prefix}_distance_atr")
                object.__setattr__(self, f"{prefix}_distance_atr", number)
            elif distance is not None:
                raise ValueError(
                    f"{prefix}_distance_atr requires {prefix}_status SET"
                )
            object.__setattr__(self, f"{prefix}_status", status)

    def compact_values(self) -> Mapping[str, float | None]:
        return {
            "unrealized_atr": self.unrealized_atr,
            "mfe_atr": self.mfe_atr,
            "mae_atr": self.mae_atr,
            "giveback_atr": self.giveback_atr,
            "range_position": self.range_position,
            "log_holding_bars": math.log1p(self.holding_bars),
            "log_bars_since_mfe": math.log1p(self.bars_since_mfe),
            "log_bars_since_mae": math.log1p(self.bars_since_mae),
        }


def build_exit_position_state(
    rows: Sequence[Mapping[str, object]],
    *,
    direction: str,
    actual_entry_price: float | None,
    entry_atr20: float | None,
    take_profit_status: object = "NOT_SET",
    take_profit_price: float | None = None,
    stop_loss_status: object = "NOT_SET",
    stop_loss_price: float | None = None,
) -> ExitPositionStateSnapshot:
    ordered = tuple(
        sorted(rows, key=lambda row: int(row["open_time_utc_ms"]))
    )
    if not ordered:
        raise ValueError("持仓状态缺少开仓后已完整收盘的决策周期 K 线。")
    normalized_direction = str(direction or "").upper()
    if normalized_direction not in {"LONG", "SHORT"}:
        raise ValueError("持仓方向必须是 LONG 或 SHORT。")
    entry_price = _finite(actual_entry_price, "actual_entry_price")
    entry_atr = _finite(entry_atr20, "entry_atr20")
    if (
        not math.isfinite(entry_price)
        or entry_price <= 0.0
        or not math.isfinite(entry_atr)
        or entry_atr <= 0.0
    ):
        raise ValueError("持仓状态缺少有效的实际开仓价或冻结 entry ATR20。")

    sign = 1.0 if normalized_direction == "LONG" else -1.0
    favorable: list[float] = []
    adverse: list[float] = []
    for row in ordered:
        high = _finite(row.get("high"), "high")
        low = _finite(row.get("low"), "low")
        if normalized_direction == "LONG":
            favorable.append((high - entry_price) / entry_atr)
            adverse.append((low - entry_price) / entry_atr)
        else:
            favorable.append((entry_price - low) / entry_atr)
            adverse.append((entry_price - high) / entry_atr)
    current_close = _finite(ordered[-1].get("close"), "close")
    unrealized = sign * (current_close - entry_price) / entry_atr
    mfe = max(0.0, max(favorable))
    mae = min(0.0, min(adverse))
    spread = mfe - mae
    range_position = (
        None
        if math.isclose(spread, 0.0, abs_tol=1e-15)
        else min(1.0, max(0.0, (unrealized - mae) / spread))
    )
    mfe_index = max(
        index
        for index, value in enumerate(favorable)
        if math.isclose(value, max(favorable), rel_tol=0.0, abs_tol=1e-12)
    )
    mae_index = max(
        index
        for index, value in enumerate(adverse)
        if math.isclose(value, min(adverse), rel_tol=0.0, abs_tol=1e-12)
    )
    last_index = len(ordered) - 1
    return ExitPositionStateSnapshot(
        unrealized_atr=unrealized,
        mfe_atr=mfe,
        mae_atr=mae,
        giveback_atr=mfe - unrealized,
        range_position=range_position,
        holding_bars=len(ordered),
        bars_since_mfe=last_index - mfe_index,
        bars_since_mae=last_index - mae_index,
        take_profit_status=_risk_status(take_profit_status),
        take_profit_distance_atr=_risk_distance_atr(
            status=take_profit_status,
            price=take_profit_price,
            current_close=current_close,
            entry_atr=entry_atr,
            direction_sign=sign,
            is_take_profit=True,
        ),
        stop_loss_status=_risk_status(stop_loss_status),
        stop_loss_distance_atr=_risk_distance_atr(
            status=stop_loss_status,
            price=stop_loss_price,
            current_close=current_close,
            entry_atr=entry_atr,
            direction_sign=sign,
            is_take_profit=False,
        ),
    )


def extract_exit_behavior_features(
    market_snapshots: Sequence[EntryStructuralFeatureSnapshot],
    position_state: ExitPositionStateSnapshot,
) -> tuple[BehaviorFeatureValue, ...]:
    snapshots = tuple(market_snapshots)
    if len(snapshots) != 3:
        raise ValueError("平仓行为指标需要三个周期的市场结构。")
    position_values = position_state.compact_values()
    result: list[BehaviorFeatureValue] = []
    missing: list[str] = []
    for definition in EXIT_BEHAVIOR_FEATURES:
        if definition.timeframe_index >= 0:
            source = (
                snapshots[definition.timeframe_index]
                .group(definition.group_name)
                .feature(definition.source_name)
            )
            if not source.available or len(source.values) != 1:
                missing.append(definition.feature_id)
                continue
            value = float(source.values[0])
        else:
            raw_value = position_values[definition.source_name]
            if raw_value is None:
                missing.append(definition.feature_id)
                continue
            value = float(raw_value)
        if not math.isfinite(value):
            missing.append(definition.feature_id)
            continue
        result.append(
            BehaviorFeatureValue(
                feature_id=definition.feature_id,
                name_zh=definition.name_zh,
                value=value,
            )
        )
    if missing:
        raise ValueError("平仓行为指标不可计算：" + "；".join(missing))
    return tuple(result)


def exit_position_state_distance(
    left: ExitPositionStateSnapshot,
    right: ExitPositionStateSnapshot,
) -> float:
    """Compatibility adapter to the authoritative audited exit formula."""

    from .exit_similarity import compare_exit_position_states

    comparison = compare_exit_position_states(left, right)
    if comparison.distance is None:
        raise ValueError("持仓状态可比指标低于 80%。")
    return comparison.distance


def _finite(value: object, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"持仓状态字段 {field_name} 缺失。") from exc
    if not math.isfinite(number):
        raise ValueError(f"持仓状态字段 {field_name} 非有限。")
    return number


def _path_count(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        number = int(value)
        exact = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if number < 0 or not math.isfinite(exact) or exact != number:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return number


def _risk_status(value: object) -> str:
    status = str(getattr(value, "value", value) or "").upper()
    if status not in {"SET", "NOT_SET", "MISSING"}:
        raise ValueError("止盈止损状态必须是 SET、NOT_SET 或 MISSING。")
    return status


def _risk_distance_atr(
    *,
    status: object,
    price: float | None,
    current_close: float,
    entry_atr: float,
    direction_sign: float,
    is_take_profit: bool,
) -> float | None:
    normalized = _risk_status(status)
    if normalized != "SET":
        return None
    level = _finite(price, "risk_level_price")
    if level <= 0.0:
        raise ValueError("止盈止损价格必须大于 0。")
    signed_gap = (
        direction_sign * (level - current_close)
        if is_take_profit
        else direction_sign * (current_close - level)
    )
    return signed_gap / entry_atr


__all__ = [
    "EXIT_POSITION_STATE_FEATURE_VERSION",
    "ExitPositionStateSnapshot",
    "build_exit_position_state",
    "exit_position_state_distance",
    "extract_exit_behavior_features",
]
