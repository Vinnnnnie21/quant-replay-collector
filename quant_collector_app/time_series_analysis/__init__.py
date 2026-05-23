from __future__ import annotations

from .baseline import build_random_bar_baseline, build_random_event_baseline, compare_events_to_baseline
from .regime import build_regime_features, summarize_regime_distribution
from .report import build_time_series_report, write_time_series_report
from .returns import build_event_window_return_series, build_return_series, summarize_return_distribution

__all__ = [
    "build_random_event_baseline",
    "build_random_bar_baseline",
    "build_regime_features",
    "build_return_series",
    "build_event_window_return_series",
    "build_time_series_report",
    "compare_events_to_baseline",
    "summarize_regime_distribution",
    "summarize_return_distribution",
    "write_time_series_report",
]
