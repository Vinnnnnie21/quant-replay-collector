from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from typing import Any


DEFERRED_OPTIONAL_MODULES = (
    "api_server",
    "exporter",
    "analysis_workspace",
    "backtest_panel",
    "strategy_consistency_panel",
    "research.dataset",
    "time_series_analysis.report",
)


@lru_cache(maxsize=None)
def get_optional_module(module_name: str) -> Any:
    return import_module(module_name)


def lazy_import(module_name: str) -> Any:
    return get_optional_module(module_name)


def deferred_module_names() -> tuple[str, ...]:
    return DEFERRED_OPTIONAL_MODULES


__all__ = ["DEFERRED_OPTIONAL_MODULES", "deferred_module_names", "get_optional_module", "lazy_import"]
