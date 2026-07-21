from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter

import pytest

from research.market_episodes import (
    MarketEpisodeService,
    ResearchSampleWindow,
    TimeRange,
)
from storage import StorageManager


def _overlapping_samples(count: int) -> tuple[ResearchSampleWindow, ...]:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    feature_end = start + timedelta(minutes=100)
    outcome_end = start + timedelta(minutes=200)
    return tuple(
        ResearchSampleWindow(
            sample_id=f"sample_{index:06d}",
            symbol=f"SYMBOL_{index % 37}",
            timeframe=("1m", "5m", "15m")[index % 3],
            feature_window=TimeRange(start, feature_end),
            outcome_window=TimeRange(feature_end, outcome_end),
        )
        for index in range(count)
    )


def _measure(tmp_path, count: int) -> float:
    service = MarketEpisodeService(
        StorageManager(tmp_path / f"episodes_{count}.db")
    )
    samples = _overlapping_samples(count)
    started = perf_counter()
    grouping = service.create_automatic_grouping(
        samples,
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    elapsed = perf_counter() - started
    assert len(grouping.episodes) == 1
    assert len(grouping.episodes[0].members) == count
    return elapsed


@pytest.mark.performance
def test_market_episode_sorting_scan_scales_below_quadratic(tmp_path):
    small_elapsed = _measure(tmp_path, 3_000)
    large_elapsed = _measure(tmp_path, 6_000)

    assert large_elapsed < 12.0
    assert large_elapsed / max(small_elapsed, 0.001) < 3.6
