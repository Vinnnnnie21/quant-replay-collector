from __future__ import annotations

import math
from typing import Any


TAKE_PROFIT = "TAKE_PROFIT"
STOP_LOSS = "STOP_LOSS"
MANUAL = "MANUAL"
SESSION_END = "SESSION_END"


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def risk_prices_for_trade(
    side: str,
    entry_price: float,
    *,
    take_profit_pct: float | None,
    stop_loss_pct: float | None,
) -> dict[str, float | None]:
    entry = _num(entry_price)
    if entry is None or entry <= 0:
        return {"take_profit_price": None, "stop_loss_price": None}
    side = str(side or "").upper()
    tp = _num(take_profit_pct)
    sl = _num(stop_loss_pct)
    if side == "LONG":
        return {
            "take_profit_price": entry * (1.0 + tp / 100.0) if tp and tp > 0 else None,
            "stop_loss_price": entry * (1.0 - sl / 100.0) if sl and sl > 0 else None,
        }
    if side == "SHORT":
        return {
            "take_profit_price": entry * (1.0 - tp / 100.0) if tp and tp > 0 else None,
            "stop_loss_price": entry * (1.0 + sl / 100.0) if sl and sl > 0 else None,
        }
    return {"take_profit_price": None, "stop_loss_price": None}


def _bar_index(row: dict[str, Any]) -> int:
    return int(row.get("bar_index", 0))


def _entry_sort_key(trade: dict[str, Any]) -> tuple[int, str, str]:
    try:
        entry_index = int(trade.get("entry_bar_index", 0))
    except (TypeError, ValueError):
        entry_index = 0
    return (entry_index, str(trade.get("created_at") or ""), str(trade.get("trade_id") or ""))


def _trigger_for_bar(trade: dict[str, Any], bar: dict[str, Any]) -> dict[str, Any] | None:
    side = str(trade.get("side") or "").upper()
    high = _num(bar.get("high"))
    low = _num(bar.get("low"))
    tp_price = _num(trade.get("take_profit_price"))
    sl_price = _num(trade.get("stop_loss_price"))
    if high is None or low is None:
        return None
    hit_tp = False
    hit_sl = False
    if side == "LONG":
        hit_tp = tp_price is not None and high >= tp_price
        hit_sl = sl_price is not None and low <= sl_price
    elif side == "SHORT":
        hit_tp = tp_price is not None and low <= tp_price
        hit_sl = sl_price is not None and high >= sl_price
    else:
        return None
    if hit_sl:
        return {
            "trade_id": trade.get("trade_id"),
            "bar_index": _bar_index(bar),
            "exit_reason": STOP_LOSS,
            "exit_price": sl_price,
        }
    if hit_tp:
        return {
            "trade_id": trade.get("trade_id"),
            "bar_index": _bar_index(bar),
            "exit_reason": TAKE_PROFIT,
            "exit_price": tp_price,
        }
    return None


def find_tp_sl_triggers(
    bars: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    trades: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    from_bar_index: int,
    to_bar_index: int,
) -> list[dict[str, Any]]:
    if int(to_bar_index) <= int(from_bar_index):
        return []
    open_trades = [
        dict(trade)
        for trade in trades
        if str(trade.get("status") or "").upper() == "OPEN"
    ]
    open_trades.sort(key=_entry_sort_key)
    triggered_ids: set[str] = set()
    triggers: list[dict[str, Any]] = []
    visible_bars = [
        dict(bar)
        for bar in bars
        if int(from_bar_index) < _bar_index(dict(bar)) <= int(to_bar_index)
    ]
    visible_bars.sort(key=_bar_index)
    for bar in visible_bars:
        idx = _bar_index(bar)
        for trade in open_trades:
            trade_id = str(trade.get("trade_id") or "")
            if trade_id in triggered_ids:
                continue
            try:
                entry_idx = int(trade.get("entry_bar_index", 0))
            except (TypeError, ValueError):
                entry_idx = 0
            if idx <= entry_idx:
                continue
            trigger = _trigger_for_bar(trade, bar)
            if trigger is None:
                continue
            triggered_ids.add(trade_id)
            triggers.append(trigger)
    return triggers


__all__ = [
    "MANUAL",
    "SESSION_END",
    "STOP_LOSS",
    "TAKE_PROFIT",
    "find_tp_sl_triggers",
    "risk_prices_for_trade",
]
