from __future__ import annotations

import math
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _closed_sort_key(trade: dict[str, Any]) -> tuple[str, str]:
    return (
        str(trade.get("updated_at") or trade.get("exit_real_time_bjt") or trade.get("exit_bar_time_bjt") or ""),
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
                "created_at": trade.get("updated_at") or trade.get("exit_real_time_bjt") or trade.get("exit_bar_time_bjt"),
            }
        )
    return rows
