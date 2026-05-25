from __future__ import annotations

import math


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
