from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from .entry_context_features import (
    ENTRY_STRUCTURAL_FEATURE_VERSION,
    EntryStructuralFeatureSnapshot,
)
from .entry_similarity import (
    TIMEFRAME_WEIGHTS,
    CalendarDistanceBreakdown,
    TimeframeDistanceBreakdown,
    compare_entry_structural_snapshot_sets,
)
from .exit_behavior_features import (
    EXIT_POSITION_STATE_FEATURE_VERSION,
    ExitPositionStateSnapshot,
)


EXIT_SIMILARITY_FORMULA_VERSION = "decision-research-exit-v1.6"
EXIT_STRUCTURAL_FEATURE_VERSION = (
    f"{ENTRY_STRUCTURAL_FEATURE_VERSION}+{EXIT_POSITION_STATE_FEATURE_VERSION}"
)
MARKET_WEIGHT = 0.50
POSITION_WEIGHT = 0.40
CALENDAR_WEIGHT = 0.10


@dataclass(frozen=True, slots=True)
class ExitSimilarityAggregate:
    market_distance: float
    position_distance: float
    calendar_distance: float
    total_distance: float
    similarity: float


@dataclass(frozen=True, slots=True)
class ExitStructuralComparison:
    calendar: CalendarDistanceBreakdown
    timeframes: tuple[TimeframeDistanceBreakdown, ...]
    position: "ExitPositionDistanceBreakdown"
    aggregate: ExitSimilarityAggregate | None

    @property
    def position_distance(self) -> float | None:
        return self.position.distance


@dataclass(frozen=True, slots=True)
class ExitPositionFeatureDistance:
    name: str
    distance: float | None
    unavailable_reason: str | None = None
    applicable: bool = True


@dataclass(frozen=True, slots=True)
class ExitPositionDistanceBreakdown:
    distance: float | None
    comparable_count: int
    total_count: int
    completeness_ratio: float
    features: tuple[ExitPositionFeatureDistance, ...]
    unavailable_reason: str | None = None

    def feature(self, name: str) -> ExitPositionFeatureDistance:
        return next(item for item in self.features if item.name == name)


def compare_exit_position_states(
    left: ExitPositionStateSnapshot,
    right: ExitPositionStateSnapshot,
) -> ExitPositionDistanceBreakdown:
    features = []
    for name in ("unrealized_atr", "mfe_atr", "mae_atr", "giveback_atr"):
        features.append(
            ExitPositionFeatureDistance(
                name,
                min(
                    abs(float(getattr(left, name)) - float(getattr(right, name)))
                    / 4.0,
                    1.0,
                ),
            )
        )
    if left.range_position is None or right.range_position is None:
        side = (
            "both"
            if left.range_position is None and right.range_position is None
            else "left" if left.range_position is None else "right"
        )
        features.append(
            ExitPositionFeatureDistance(
                "range_position",
                None,
                f"{side}:zero_favorable_adverse_span",
            )
        )
    else:
        features.append(
            ExitPositionFeatureDistance(
                "range_position",
                abs(left.range_position - right.range_position),
            )
        )
    for name in ("holding_bars", "bars_since_mfe", "bars_since_mae"):
        left_value = math.log1p(int(getattr(left, name)))
        right_value = math.log1p(int(getattr(right, name)))
        features.append(
            ExitPositionFeatureDistance(
                name,
                min(abs(left_value - right_value) / math.log(4.0), 1.0),
            )
        )
    for name in ("take_profit", "stop_loss"):
        features.append(_compare_risk_level(left, right, name))
    comparable = tuple(
        item.distance
        for item in features
        if item.applicable and item.distance is not None
    )
    total = sum(item.applicable for item in features)
    ratio = len(comparable) / total
    ready = ratio >= 0.80
    return ExitPositionDistanceBreakdown(
        distance=(math.fsum(comparable) / len(comparable) if ready else None),
        comparable_count=len(comparable),
        total_count=total,
        completeness_ratio=ratio,
        features=tuple(features),
        unavailable_reason=(
            None if ready else "position_completeness_below_80_percent"
        ),
    )


def _compare_risk_level(
    left: ExitPositionStateSnapshot,
    right: ExitPositionStateSnapshot,
    name: str,
) -> ExitPositionFeatureDistance:
    feature_name = f"{name}_distance_atr"
    left_status = getattr(left, f"{name}_status")
    right_status = getattr(right, f"{name}_status")
    if left_status == right_status == "NOT_SET":
        return ExitPositionFeatureDistance(
            feature_name,
            None,
            "not_applicable:both_not_set",
            applicable=False,
        )
    if "MISSING" in {left_status, right_status}:
        side = (
            "both"
            if left_status == right_status == "MISSING"
            else "left" if left_status == "MISSING" else "right"
        )
        return ExitPositionFeatureDistance(
            feature_name,
            None,
            f"{side}:expected_value_missing",
        )
    if left_status != right_status:
        return ExitPositionFeatureDistance(feature_name, 1.0)
    left_distance = float(getattr(left, feature_name))
    right_distance = float(getattr(right, feature_name))
    return ExitPositionFeatureDistance(
        feature_name,
        min(abs(left_distance - right_distance) / 4.0, 1.0),
    )


def compare_exit_structural_snapshot_sets(
    left_market: Sequence[EntryStructuralFeatureSnapshot],
    right_market: Sequence[EntryStructuralFeatureSnapshot],
    *,
    left_position: ExitPositionStateSnapshot,
    right_position: ExitPositionStateSnapshot,
    left_cutoff_utc_ms: int,
    right_cutoff_utc_ms: int,
) -> ExitStructuralComparison:
    """Compare the canonical market, holding-path, and BJT calendar states."""

    market = compare_entry_structural_snapshot_sets(
        left_market,
        right_market,
        left_cutoff_utc_ms=left_cutoff_utc_ms,
        right_cutoff_utc_ms=right_cutoff_utc_ms,
    )
    timeframe_distances = tuple(item.distance for item in market.timeframes)
    if any(value is None for value in timeframe_distances):
        return ExitStructuralComparison(
            market.calendar,
            market.timeframes,
            compare_exit_position_states(left_position, right_position),
            None,
        )
    market_distance = math.fsum(
        weight * float(distance)
        for weight, distance in zip(
            TIMEFRAME_WEIGHTS,
            timeframe_distances,
            strict=True,
        )
    )
    position = compare_exit_position_states(
        left_position,
        right_position,
    )
    if position.distance is None:
        return ExitStructuralComparison(
            market.calendar,
            market.timeframes,
            position,
            None,
        )
    position_distance = position.distance
    total = (
        MARKET_WEIGHT * market_distance
        + POSITION_WEIGHT * position_distance
        + CALENDAR_WEIGHT * market.calendar.distance
    )
    aggregate = ExitSimilarityAggregate(
        market_distance=market_distance,
        position_distance=position_distance,
        calendar_distance=market.calendar.distance,
        total_distance=total,
        similarity=100.0 * (1.0 - total),
    )
    return ExitStructuralComparison(
        market.calendar,
        market.timeframes,
        position,
        aggregate,
    )


__all__ = [
    "CALENDAR_WEIGHT",
    "EXIT_SIMILARITY_FORMULA_VERSION",
    "EXIT_STRUCTURAL_FEATURE_VERSION",
    "ExitPositionDistanceBreakdown",
    "ExitPositionFeatureDistance",
    "ExitSimilarityAggregate",
    "ExitStructuralComparison",
    "MARKET_WEIGHT",
    "POSITION_WEIGHT",
    "compare_exit_position_states",
    "compare_exit_structural_snapshot_sets",
]
