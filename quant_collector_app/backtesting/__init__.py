from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "BacktestConfig": (".types", "BacktestConfig"),
    "BacktestResult": (".types", "BacktestResult"),
    "Signal": (".types", "Signal"),
    "run_backtest": (".engine", "run_backtest"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(import_module(module_name, __name__), attribute)


__all__ = list(_EXPORTS)
