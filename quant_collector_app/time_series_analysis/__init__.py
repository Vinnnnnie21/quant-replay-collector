from __future__ import annotations

from .baseline import build_random_bar_baseline, build_random_event_baseline, compare_events_to_baseline
from .diagnostics import descriptive_stats, jarque_bera_test
from .factor_model import correlation_matrix, pca_factor_model, rolling_correlation
from .microstructure import microstructure_diagnostics
from .regime import build_regime_features, summarize_regime_distribution
from .report import build_time_series_report, write_time_series_report
from .returns import (
    annualized_log_return,
    annualized_return,
    build_event_window_return_series,
    build_return_series,
    cumulative_log_return,
    log_return,
    simple_return,
    summarize_return_distribution,
)
from .risk import risk_summary
from .volatility import volatility_diagnostics

__all__ = [
    "build_random_event_baseline",
    "build_random_bar_baseline",
    "descriptive_stats",
    "jarque_bera_test",
    "build_regime_features",
    "build_return_series",
    "build_event_window_return_series",
    "build_time_series_report",
    "compare_events_to_baseline",
    "summarize_regime_distribution",
    "summarize_return_distribution",
    "write_time_series_report",
    "simple_return",
    "log_return",
    "cumulative_log_return",
    "annualized_return",
    "annualized_log_return",
    "volatility_diagnostics",
    "risk_summary",
    "microstructure_diagnostics",
    "correlation_matrix",
    "rolling_correlation",
    "pca_factor_model",
]
