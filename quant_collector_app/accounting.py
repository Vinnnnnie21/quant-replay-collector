from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any


class EquityCurveCancelled(Exception):
    pass


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _closed_sort_key(trade: dict[str, Any]) -> tuple[str, str]:
    return (
        str(
            trade.get("exit_bar_time_bjt")
            or trade.get("exit_real_time_bjt")
            or trade.get("updated_at")
            or ""
        ),
        str(trade.get("trade_id") or ""),
    )


def realized_net_pnl(trade: dict[str, Any], default_notional: float) -> float:
    if trade.get("net_pnl_quote") is not None:
        return _safe_float(trade.get("net_pnl_quote"))
    notional = _safe_float(trade.get("notional_quote"), default_notional)
    return _safe_float(trade.get("final_return_pct")) / 100.0 * notional


def realized_gross_pnl(trade: dict[str, Any], default_notional: float) -> float:
    if trade.get("gross_pnl_quote") is not None:
        return _safe_float(trade.get("gross_pnl_quote"))
    notional = _safe_float(trade.get("notional_quote"), default_notional)
    value = trade.get("gross_return_pct")
    if value is None:
        value = trade.get("final_return_pct")
    return _safe_float(value) / 100.0 * notional


def _bar_index(row: dict[str, Any], fallback: int) -> int:
    try:
        return int(row.get("bar_index", fallback))
    except (TypeError, ValueError):
        return fallback


def _trade_entry_index(trade: dict[str, Any]) -> int:
    try:
        return int(trade.get("entry_bar_index", 0))
    except (TypeError, ValueError):
        return 0


def _trade_exit_index(trade: dict[str, Any]) -> int | None:
    value = trade.get("exit_bar_index")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _entry_price(trade: dict[str, Any]) -> float:
    value = trade.get("entry_fill_price")
    if value is None:
        value = trade.get("entry_price_proxy")
    return _safe_float(value, default=float("nan"))


def unrealized_pnl_at_price(trade: dict[str, Any], price: float, default_notional: float) -> float:
    entry = _entry_price(trade)
    notional = _safe_float(trade.get("notional_quote"), default_notional)
    if not math.isfinite(entry) or entry <= 0 or notional <= 0 or not math.isfinite(price):
        return 0.0
    quantity = notional / entry
    direction = 1.0 if str(trade.get("side") or "").upper() == "LONG" else -1.0
    return (price - entry) * quantity * direction


def build_continuous_equity_curve(
    bars: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    trades: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    session_id: str,
    initial_equity: float,
    default_notional: float,
    cancelled: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    base_equity = max(0.0, _safe_float(initial_equity, 10_000.0))
    notional = max(1.0, _safe_float(default_notional, 1_000.0))
    trade_rows = [dict(trade) for trade in trades]
    peak = base_equity
    rows: list[dict[str, Any]] = []
    for sequence_no, bar in enumerate(bars, start=1):
        if cancelled is not None and cancelled():
            raise EquityCurveCancelled()
        bar_row = dict(bar)
        idx = _bar_index(bar_row, sequence_no - 1)
        price = _safe_float(bar_row.get("close"), default=float("nan"))
        realized = 0.0
        unrealized = 0.0
        open_count = 0
        for trade in trade_rows:
            entry_idx = _trade_entry_index(trade)
            if idx < entry_idx:
                continue
            exit_idx = _trade_exit_index(trade)
            status = str(trade.get("status") or "").upper()
            if status == "CLOSED" and exit_idx is not None and idx >= exit_idx:
                realized += realized_net_pnl(trade, notional)
                continue
            if status == "OPEN" or (exit_idx is not None and idx < exit_idx):
                unrealized += unrealized_pnl_at_price(trade, price, notional)
                open_count += 1
        current_equity = base_equity + realized + unrealized
        peak = max(peak, current_equity)
        drawdown_pct = ((current_equity / peak) - 1.0) * 100.0 if peak else 0.0
        total_return_pct = ((current_equity / base_equity) - 1.0) * 100.0 if base_equity else 0.0
        rows.append(
            {
                "session_id": session_id,
                "sequence_no": sequence_no,
                "bar_index": idx,
                "time": bar_row.get("open_time_bjt") or bar_row.get("time") or bar_row.get("created_at"),
                "close": price,
                "realized_net_pnl": realized,
                "unrealized_pnl": unrealized,
                "current_equity": current_equity,
                "total_return_pct": total_return_pct,
                "drawdown_pct": drawdown_pct,
                "open_position_count": open_count,
            }
        )
    if cancelled is not None and cancelled():
        raise EquityCurveCancelled()
    return rows


def build_equity_curve(
    trades: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    session_id: str,
    initial_equity: float,
    default_notional: float,
) -> list[dict[str, Any]]:
    equity = max(0.0, _safe_float(initial_equity, 10_000.0))
    notional = max(1.0, _safe_float(default_notional, 1_000.0))
    peak = equity
    rows: list[dict[str, Any]] = []
    closed = [dict(t) for t in trades if str(t.get("status") or "").upper() == "CLOSED"]
    for seq, trade in enumerate(sorted(closed, key=_closed_sort_key), start=1):
        before = equity
        gross = realized_gross_pnl(trade, notional)
        net = realized_net_pnl(trade, notional)
        fees = _safe_float(trade.get("entry_fee_quote")) + _safe_float(trade.get("exit_fee_quote"))
        equity = before + net
        peak = max(peak, equity)
        drawdown_pct = ((equity / peak) - 1.0) * 100.0 if peak else 0.0
        rows.append(
            {
                "session_id": session_id,
                "sequence_no": seq,
                "trade_id": trade.get("trade_id"),
                "event_id": trade.get("exit_event_id"),
                "equity_before": before,
                "realized_gross_pnl": gross,
                "realized_fee": fees,
                "realized_net_pnl": net,
                "equity_after": equity,
                "equity_return_pct": (net / before * 100.0) if before else 0.0,
                "drawdown_pct": drawdown_pct,
                "created_at": (
                    trade.get("exit_bar_time_bjt")
                    or trade.get("exit_real_time_bjt")
                    or trade.get("updated_at")
                ),
            }
        )
    return rows
