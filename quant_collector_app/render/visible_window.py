from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RebuildPlan:
    start: int
    end: int
    rebuild_key: tuple[int | None, int, int]


def visible_bar_bounds(
    available_bars: int,
    visible_range: tuple[float, float] | None,
    large_dataset_threshold: int = 2000,
    margin: int = 100,
) -> tuple[int, int]:
    available = max(0, int(available_bars))
    if available <= large_dataset_threshold:
        return 0, available
    if visible_range is None:
        return max(0, available - 1000), available
    left, right = visible_range
    start = max(0, int(math.floor(left)) - margin)
    end = min(available, int(math.ceil(right)) + margin)
    if end <= start:
        return max(0, available - 1000), available
    return start, end


def build_rebuild_plan(
    available_bars: int,
    visible_range: tuple[float, float] | None,
    large_dataset_threshold: int = 2000,
    margin: int = 100,
) -> RebuildPlan:
    available = max(0, int(available_bars))
    start, end = visible_bar_bounds(
        available,
        visible_range,
        large_dataset_threshold=large_dataset_threshold,
        margin=margin,
    )
    contains_latest = end >= available
    return RebuildPlan(
        start=start,
        end=end,
        rebuild_key=(available if contains_latest else None, start, end),
    )


__all__ = ["RebuildPlan", "build_rebuild_plan", "visible_bar_bounds"]
