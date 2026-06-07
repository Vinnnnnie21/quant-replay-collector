"""Controller package with lazy imports for optional Qt dependencies."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "AnalysisRefreshController": (".analysis_controller", "AnalysisRefreshController"),
    "BacktestController": (".backtest_controller", "BacktestController"),
    "ExportTaskController": (".export_task_controller", "ExportTaskController"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(import_module(module_name, __name__), attribute)


__all__ = list(_EXPORTS)
