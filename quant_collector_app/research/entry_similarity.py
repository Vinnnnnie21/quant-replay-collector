from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
import math
from typing import Sequence
from zoneinfo import ZoneInfo

from .entry_context_features import (
    EntryStructuralFeatureSnapshot,
    StructuralFeatureValue,
)


ENTRY_SIMILARITY_FORMULA_VERSION = "decision-research-v1.6"
TIMEFRAME_WEIGHTS = (0.60, 0.25, 0.15)
MARKET_WEIGHT = 0.90
CALENDAR_WEIGHT = 0.10
_BJT = ZoneInfo("Asia/Shanghai")
GROUP_COMPLETENESS_THRESHOLD = 0.80

_NATURAL_RANGES = {
    "body_direction": (-1.0, 1.0),
    "upper_wick_ratio": (0.0, 1.0),
    "lower_wick_ratio": (0.0, 1.0),
    "bullish_ratio_5": (0.0, 1.0),
    "body_net_5": (-1.0, 1.0),
    "max_upper_wick_5": (0.0, 1.0),
    "max_lower_wick_5": (0.0, 1.0),
    "range_position_20": (0.0, 1.0),
    "range_position_60": (0.0, 1.0),
    "direction_efficiency_20": (-1.0, 1.0),
    "direction_efficiency_60": (-1.0, 1.0),
    "aggressor_current": (-1.0, 1.0),
    "aggressor_5": (-1.0, 1.0),
    "aggressor_20": (-1.0, 1.0),
    "aggressor_delta": (-2.0, 2.0),
}
_ATR_SCALE_FEATURES = {
    "amplitude_atr_20",
    "adjusted_slope_20",
    "adjusted_slope_60",
    "ema_distance_20",
    "ema_distance_60",
}
_POSITIVE_RATIO_FEATURES = {
    "volatility_level",
    "volatility_shock",
    "volatility_regime",
}
_LOG_MULTIPLE_FEATURES = {
    "quote_activity_20",
    "quote_activity_60",
    "trade_count_activity_20",
    "trade_count_activity_60",
    "average_trade_size_activity_20",
}


@dataclass(frozen=True, slots=True)
class EntrySimilarityAggregate:
    market_distance: float
    calendar_distance: float
    total_distance: float
    similarity: float


@dataclass(frozen=True, slots=True)
class EntryStructuralComparison:
    calendar: "CalendarDistanceBreakdown"
    timeframes: tuple["TimeframeDistanceBreakdown", ...]
    aggregate: EntrySimilarityAggregate | None


@dataclass(frozen=True, slots=True)
class FeatureDistanceBreakdown:
    name: str
    left_values: tuple[float, ...]
    right_values: tuple[float, ...]
    distance: float | None
    unavailable_reason: str | None = None

    @property
    def comparable(self) -> bool:
        return self.distance is not None


@dataclass(frozen=True, slots=True)
class GroupDistanceBreakdown:
    name: str
    distance: float | None
    comparable_count: int
    total_count: int
    completeness_ratio: float
    features: tuple[FeatureDistanceBreakdown, ...]
    unavailable_reason: str | None = None

    def feature(self, name: str) -> FeatureDistanceBreakdown:
        return next(item for item in self.features if item.name == name)


@dataclass(frozen=True, slots=True)
class TimeframeDistanceBreakdown:
    interval: str
    distance: float | None
    groups: tuple[GroupDistanceBreakdown, ...]
    unavailable_reasons: tuple[str, ...] = ()
    role: str = ""
    weight: float | None = None

    def group(self, name: str) -> GroupDistanceBreakdown:
        return next(item for item in self.groups if item.name == name)


class SimilarityStatus(StrEnum):
    COMPUTED = "COMPUTED"
    NOT_COMPUTABLE = "NOT_COMPUTABLE"


class SimilarityUsage(StrEnum):
    FREE_BROWSE = "FREE_BROWSE"


@dataclass(frozen=True, slots=True)
class CalendarDistanceBreakdown:
    day_distance: float
    week_distance: float
    weekend_distance: float
    distance: float


@dataclass(frozen=True, slots=True)
class EntrySimilarityResult:
    result_id: str
    left_decision_event_id: str
    right_decision_event_id: str
    setup_version_id: str
    direction: str
    formula_version: str
    feature_version: str
    left_feature_fingerprint: str
    right_feature_fingerprint: str
    status: SimilarityStatus
    similarity: float | None
    total_distance: float | None
    market_distance: float | None
    calendar: CalendarDistanceBreakdown
    timeframes: tuple[TimeframeDistanceBreakdown, ...]
    unavailable_reasons: tuple[str, ...]
    usage: SimilarityUsage
    eligible_for_formal_evidence: bool
    created_at: str

    def require_compatible_version(
        self,
        other: "EntrySimilarityResult",
    ) -> None:
        if (
            self.formula_version != other.formula_version
            or self.feature_version != other.feature_version
        ):
            raise ValueError(
                "entry similarity versions are not directly comparable"
            )


def calendar_distance_bjt(
    left_cutoff_ms: int,
    right_cutoff_ms: int,
) -> CalendarDistanceBreakdown:
    left = datetime.fromtimestamp(left_cutoff_ms / 1_000, UTC).astimezone(_BJT)
    right = datetime.fromtimestamp(right_cutoff_ms / 1_000, UTC).astimezone(_BJT)
    left_minute = left.hour * 60 + left.minute
    right_minute = right.hour * 60 + right.minute
    minute_gap = abs(left_minute - right_minute)
    day = min(minute_gap, 1440 - minute_gap) / 720.0
    week_gap = abs(left.weekday() - right.weekday())
    week = min(week_gap, 7 - week_gap) / 3.0
    weekend = float((left.weekday() >= 5) != (right.weekday() >= 5))
    distance = 0.60 * day + 0.20 * week + 0.20 * weekend
    return CalendarDistanceBreakdown(day, week, weekend, distance)


def compare_timeframe_structural_features(
    left: EntryStructuralFeatureSnapshot,
    right: EntryStructuralFeatureSnapshot,
) -> TimeframeDistanceBreakdown:
    if left.feature_version != right.feature_version:
        raise ValueError("structural feature versions are not directly comparable")
    if left.interval != right.interval:
        raise ValueError("structural feature timeframes must match")
    right_groups = {group.name: group for group in right.groups}
    groups: list[GroupDistanceBreakdown] = []
    for left_group in left.groups:
        right_group = right_groups.get(left_group.name)
        right_features = {
            feature.name: feature
            for feature in (() if right_group is None else right_group.features)
        }
        features = tuple(
            _compare_feature(
                left_feature,
                right_features.get(left_feature.name),
            )
            for left_feature in left_group.features
        )
        comparable = tuple(
            feature.distance
            for feature in features
            if feature.distance is not None
        )
        total = len(features)
        ratio = len(comparable) / total if total else 0.0
        group_ready = total > 0 and ratio >= GROUP_COMPLETENESS_THRESHOLD
        groups.append(
            GroupDistanceBreakdown(
                name=left_group.name,
                distance=(
                    math.fsum(comparable) / len(comparable)
                    if group_ready and comparable
                    else None
                ),
                comparable_count=len(comparable),
                total_count=total,
                completeness_ratio=ratio,
                features=features,
                unavailable_reason=(
                    None
                    if group_ready
                    else "group_completeness_below_80_percent"
                ),
            )
        )
    missing = tuple(
        group.name for group in groups if group.distance is None
    )
    comparable_group_distances = tuple(
        group.distance for group in groups if group.distance is not None
    )
    return TimeframeDistanceBreakdown(
        interval=left.interval,
        distance=(
            math.fsum(comparable_group_distances) / len(groups)
            if groups and len(comparable_group_distances) == len(groups)
            else None
        ),
        groups=tuple(groups),
        unavailable_reasons=tuple(
            f"{name}:group_completeness_below_80_percent"
            for name in missing
        ),
    )


def compare_entry_structural_snapshot_sets(
    left: Sequence[EntryStructuralFeatureSnapshot],
    right: Sequence[EntryStructuralFeatureSnapshot],
    *,
    left_cutoff_utc_ms: int,
    right_cutoff_utc_ms: int,
) -> EntryStructuralComparison:
    """Apply the single versioned three-timeframe aggregation formula."""

    left_snapshots = tuple(left)
    right_snapshots = tuple(right)
    if len(left_snapshots) != 3 or len(right_snapshots) != 3:
        raise ValueError("entry similarity requires exactly three snapshots per side")
    timeframes = tuple(
        replace(
            compare_timeframe_structural_features(left_item, right_item),
            role=role,
            weight=weight,
        )
        for left_item, right_item, role, weight in zip(
            left_snapshots,
            right_snapshots,
            ("decision", "context_one", "context_two"),
            TIMEFRAME_WEIGHTS,
            strict=True,
        )
    )
    calendar = calendar_distance_bjt(
        int(left_cutoff_utc_ms),
        int(right_cutoff_utc_ms),
    )
    distances = tuple(item.distance for item in timeframes)
    aggregate = (
        aggregate_entry_similarity(
            timeframe_distances=tuple(float(value) for value in distances),
            calendar_distance=calendar.distance,
        )
        if all(value is not None for value in distances)
        else None
    )
    return EntryStructuralComparison(calendar, timeframes, aggregate)


def structural_snapshot_set_is_complete(
    snapshots: Sequence[EntryStructuralFeatureSnapshot],
) -> bool:
    values = tuple(snapshots)
    if len(values) != 3:
        return False
    return compare_entry_structural_snapshot_sets(
        values,
        values,
        left_cutoff_utc_ms=0,
        right_cutoff_utc_ms=0,
    ).aggregate is not None


def _compare_feature(
    left: StructuralFeatureValue,
    right: StructuralFeatureValue | None,
) -> FeatureDistanceBreakdown:
    if not left.available or right is None or not right.available:
        reasons = [
            reason
            for reason in (
                f"left:{left.unavailable_reason}" if not left.available else None,
                "right:feature_missing" if right is None else None,
                (
                    f"right:{right.unavailable_reason}"
                    if right is not None and not right.available
                    else None
                ),
            )
            if reason is not None
        ]
        return FeatureDistanceBreakdown(
            name=left.name,
            left_values=left.values,
            right_values=() if right is None else right.values,
            distance=None,
            unavailable_reason=";".join(reasons),
        )
    assert right is not None
    if len(left.values) != len(right.values) or not left.values:
        return FeatureDistanceBreakdown(
            name=left.name,
            left_values=left.values,
            right_values=right.values,
            distance=None,
            unavailable_reason="feature_shape_mismatch",
        )
    distance = _fixed_feature_distance(
        left.name,
        left.values,
        right.values,
    )
    return FeatureDistanceBreakdown(
        name=left.name,
        left_values=left.values,
        right_values=right.values,
        distance=distance,
        unavailable_reason=(
            None if distance is not None else "feature_value_not_comparable"
        ),
    )


def _fixed_feature_distance(
    name: str,
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> float | None:
    if not all(math.isfinite(value) for value in (*left, *right)):
        return None
    if name.startswith("path_"):
        return math.fsum(
            min(abs(a - b) / 4.0, 1.0)
            for a, b in zip(left, right, strict=True)
        ) / len(left)
    a, b = left[0], right[0]
    if name in _NATURAL_RANGES:
        low, high = _NATURAL_RANGES[name]
        return min(abs(a - b) / (high - low), 1.0)
    if name in _ATR_SCALE_FEATURES:
        return min(abs(a - b) / 4.0, 1.0)
    if name in _POSITIVE_RATIO_FEATURES:
        if a <= 0 or b <= 0:
            return None
        return min(abs(math.log(a / b)) / math.log(4.0), 1.0)
    if name in _LOG_MULTIPLE_FEATURES:
        return min(abs(a - b) / math.log(4.0), 1.0)
    raise ValueError(f"unknown structural feature distance: {name}")


def entry_similarity_result_from_dict(value: dict) -> EntrySimilarityResult:
    calendar_value = value["calendar"]
    timeframes = []
    for timeframe_value in value["timeframes"]:
        groups = []
        for group_value in timeframe_value["groups"]:
            features = tuple(
                FeatureDistanceBreakdown(
                    name=item["name"],
                    left_values=tuple(item["left_values"]),
                    right_values=tuple(item["right_values"]),
                    distance=item.get("distance"),
                    unavailable_reason=item.get("unavailable_reason"),
                )
                for item in group_value["features"]
            )
            groups.append(
                GroupDistanceBreakdown(
                    name=group_value["name"],
                    distance=group_value.get("distance"),
                    comparable_count=int(group_value["comparable_count"]),
                    total_count=int(group_value["total_count"]),
                    completeness_ratio=float(group_value["completeness_ratio"]),
                    features=features,
                    unavailable_reason=group_value.get("unavailable_reason"),
                )
            )
        timeframes.append(
            TimeframeDistanceBreakdown(
                interval=timeframe_value["interval"],
                distance=timeframe_value.get("distance"),
                groups=tuple(groups),
                unavailable_reasons=tuple(
                    timeframe_value.get("unavailable_reasons", ())
                ),
                role=timeframe_value.get("role", ""),
                weight=timeframe_value.get("weight"),
            )
        )
    return EntrySimilarityResult(
        result_id=value["result_id"],
        left_decision_event_id=value["left_decision_event_id"],
        right_decision_event_id=value["right_decision_event_id"],
        setup_version_id=value["setup_version_id"],
        direction=value["direction"],
        formula_version=value["formula_version"],
        feature_version=value["feature_version"],
        left_feature_fingerprint=value["left_feature_fingerprint"],
        right_feature_fingerprint=value["right_feature_fingerprint"],
        status=SimilarityStatus(value["status"]),
        similarity=value.get("similarity"),
        total_distance=value.get("total_distance"),
        market_distance=value.get("market_distance"),
        calendar=CalendarDistanceBreakdown(
            day_distance=float(calendar_value["day_distance"]),
            week_distance=float(calendar_value["week_distance"]),
            weekend_distance=float(calendar_value["weekend_distance"]),
            distance=float(calendar_value["distance"]),
        ),
        timeframes=tuple(timeframes),
        unavailable_reasons=tuple(value.get("unavailable_reasons", ())),
        usage=SimilarityUsage(value["usage"]),
        eligible_for_formal_evidence=bool(
            value["eligible_for_formal_evidence"]
        ),
        created_at=value["created_at"],
    )


def aggregate_entry_similarity(
    *,
    timeframe_distances: Sequence[float],
    calendar_distance: float,
) -> EntrySimilarityAggregate:
    distances = tuple(float(value) for value in timeframe_distances)
    if len(distances) != len(TIMEFRAME_WEIGHTS):
        raise ValueError("entry similarity requires exactly three timeframes")
    calendar = _unit_distance(calendar_distance, "calendar_distance")
    normalized = tuple(
        _unit_distance(value, "timeframe_distance") for value in distances
    )
    market = math.fsum(
        weight * value
        for weight, value in zip(
            TIMEFRAME_WEIGHTS,
            normalized,
            strict=True,
        )
    )
    total = MARKET_WEIGHT * market + CALENDAR_WEIGHT * calendar
    return EntrySimilarityAggregate(
        market_distance=market,
        calendar_distance=calendar,
        total_distance=total,
        similarity=100.0 * (1.0 - total),
    )


def _unit_distance(value: float, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")
    return number


__all__ = [
    "CalendarDistanceBreakdown",
    "ENTRY_SIMILARITY_FORMULA_VERSION",
    "EntrySimilarityAggregate",
    "EntrySimilarityResult",
    "EntryStructuralComparison",
    "FeatureDistanceBreakdown",
    "GROUP_COMPLETENESS_THRESHOLD",
    "GroupDistanceBreakdown",
    "SimilarityStatus",
    "SimilarityUsage",
    "TimeframeDistanceBreakdown",
    "aggregate_entry_similarity",
    "calendar_distance_bjt",
    "compare_timeframe_structural_features",
    "compare_entry_structural_snapshot_sets",
    "entry_similarity_result_from_dict",
    "structural_snapshot_set_is_complete",
]
