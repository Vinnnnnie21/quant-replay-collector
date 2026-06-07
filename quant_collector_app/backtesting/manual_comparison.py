from __future__ import annotations

import math
from typing import Any, Iterable

import pandas as pd


def compare_manual_vs_rule(
    manual_trades: pd.DataFrame | list[dict[str, Any]],
    rule_trades: pd.DataFrame | list[dict[str, Any]],
    *,
    symbol: str | None = None,
    interval: str | None = None,
    valid_entry_bars: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Compare observed manual entries with simulated rule entries.

    This descriptive comparison runs after the rule simulation. Manual outcomes
    are never accepted as strategy inputs.
    """
    manual = _filter_manual(_frame(manual_trades), symbol, interval, valid_entry_bars)
    rule = _with_entry_bars(_frame(rule_trades))
    manual_bars = set(_entry_bars(manual))
    rule_bars = set(_entry_bars(rule))
    overlap = sorted(manual_bars & rule_bars)
    manual_only = sorted(manual_bars - rule_bars)
    rule_only = sorted(rule_bars - manual_bars)
    union = manual_bars | rule_bars
    manual_returns = _returns(manual)
    rule_returns = _returns(rule)
    return {
        "manual_trade_count": int(len(manual)),
        "rule_trade_count": int(len(rule)),
        "overlap_entry_bars": overlap,
        "manual_only_bars": manual_only,
        "rule_only_bars": rule_only,
        "manual_avg_return": _mean(manual_returns),
        "rule_avg_return": _mean(rule_returns),
        "manual_win_rate": _win_rate(manual_returns),
        "rule_win_rate": _win_rate(rule_returns),
        "overlap_ratio": (len(overlap) / len(union)) if union else None,
        "matched_baseline_status": "not_integrated",
        "warnings": [
            "Manual-vs-rule comparison is descriptive and subject to manual-trade selection bias."
        ],
    }


def _filter_manual(
    manual: pd.DataFrame,
    symbol: str | None,
    interval: str | None,
    valid_entry_bars: Iterable[int] | None,
) -> pd.DataFrame:
    manual = _with_entry_bars(manual)
    if manual.empty:
        return manual
    if symbol and "symbol" in manual.columns:
        manual = manual[manual["symbol"].astype(str).str.upper().eq(str(symbol).upper())]
    if interval and "interval" in manual.columns:
        manual = manual[manual["interval"].astype(str).eq(str(interval))]
    if valid_entry_bars is not None:
        allowed = {int(value) for value in valid_entry_bars}
        manual = manual[manual["entry_bar_index"].isin(allowed)]
    return manual.reset_index(drop=True)


def _with_entry_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "entry_bar_index" not in frame.columns:
        columns = list(frame.columns)
        if "entry_bar_index" not in columns:
            columns.append("entry_bar_index")
        return pd.DataFrame(columns=columns)
    out = frame.copy()
    out["entry_bar_index"] = pd.to_numeric(out["entry_bar_index"], errors="coerce")
    return out[out["entry_bar_index"].notna()].copy()


def _entry_bars(frame: pd.DataFrame) -> list[int]:
    if frame.empty:
        return []
    return [int(value) for value in frame["entry_bar_index"].tolist()]


def _returns(frame: pd.DataFrame) -> list[float]:
    if frame.empty:
        return []
    if "status" in frame.columns:
        frame = frame[frame["status"].astype(str).str.upper().eq("CLOSED")]
    for column in ("return_pct", "net_return_pct", "final_return_pct"):
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce").dropna().astype(float)
            return [float(value) for value in values if math.isfinite(float(value))]
    return []


def _mean(values: list[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


def _win_rate(values: list[float]) -> float | None:
    return float(sum(value > 0 for value in values) / len(values) * 100.0) if values else None


def _frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame(value or [])


__all__ = ["compare_manual_vs_rule"]
