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
    cache_window: int | None = None,
) -> tuple[int, int]:
    available = max(0, int(available_bars))
    if available <= large_dataset_threshold:
        return 0, available
    if visible_range is None:
        return max(0, available - 1000), available
    left, right = visible_range
    visible_start = int(math.floor(left))
    visible_end = int(math.ceil(right))
    effective_margin = int(margin)
    if cache_window is not None:
        visible_count = max(1, visible_end - visible_start)
        effective_margin = max(effective_margin, int(math.ceil((int(cache_window) - visible_count) / 2.0)))
    start = max(0, visible_start - effective_margin)
    end = min(available, visible_end + effective_margin)
    target = min(available, max(0, int(cache_window or 0)))
    if target and end - start < target:
        if start == 0:
            end = min(available, target)
        elif end == available:
            start = max(0, end - target)
    if end <= start:
        return max(0, available - 1000), available
    return start, end


def build_rebuild_plan(
    available_bars: int,
    visible_range: tuple[float, float] | None,
    large_dataset_threshold: int = 2000,
    margin: int = 100,
    cache_window: int | None = None,
) -> RebuildPlan:
    available = max(0, int(available_bars))
    start, end = visible_bar_bounds(
        available,
        visible_range,
        large_dataset_threshold=large_dataset_threshold,
        margin=margin,
        cache_window=cache_window,
    )
    contains_latest = end >= available
    return RebuildPlan(
        start=start,
        end=end,
        rebuild_key=(available if contains_latest else None, start, end),
    )


__all__ = ["RebuildPlan", "build_rebuild_plan", "visible_bar_bounds"]
