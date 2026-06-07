from __future__ import annotations

from importlib import import_module


def __getattr__(name: str):
    if name == "analyze_trades":
        return getattr(import_module(".trade_analysis", __name__), name)
    raise AttributeError(name)


__all__ = ["analyze_trades"]
