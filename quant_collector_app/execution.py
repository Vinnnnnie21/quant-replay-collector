from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


FILL_MODES = ("MID", "CLOSE", "OPEN")


@dataclass(frozen=True)
class ExecutionSettings:
    fill_mode: str
    fee_bps: float
    slippage_bps: float
    notional_quote: float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def normalize_fill_mode(value: str | None) -> str:
    mode = str(value or "MID").strip().upper()
    return mode if mode in FILL_MODES else "MID"


def raw_fill_price(row: Any, fill_mode: str) -> float:
    mode = normalize_fill_mode(fill_mode)
    if mode == "OPEN":
        return _safe_float(row["open"])
    if mode == "CLOSE":
        return _safe_float(row["close"])
    return (_safe_float(row["high"]) + _safe_float(row["low"])) / 2.0


def order_action(side: str, event_type: str) -> str:
    side = str(side or "").upper()
    event_type = str(event_type or "").upper()
    if (event_type == "OPEN" and side == "LONG") or (event_type == "CLOSE" and side == "SHORT"):
        return "BUY"
    if (event_type == "OPEN" and side == "SHORT") or (event_type == "CLOSE" and side == "LONG"):
        return "SELL"
    raise ValueError(f"Unsupported side/event_type: {side}/{event_type}")


def apply_slippage(raw_price: float, action: str, slippage_bps: float) -> float:
    price = _safe_float(raw_price)
    slip = max(0.0, _safe_float(slippage_bps)) / 10_000.0
    if action == "BUY":
        return price * (1.0 + slip)
    if action == "SELL":
        return price * (1.0 - slip)
    raise ValueError(f"Unsupported order action: {action}")


def fill_price(row: Any, side: str, event_type: str, settings: ExecutionSettings) -> tuple[float, float]:
    raw = raw_fill_price(row, settings.fill_mode)
    filled = apply_slippage(raw, order_action(side, event_type), settings.slippage_bps)
    return raw, filled


def trade_outcome(
    side: str,
    entry_fill_price: float,
    exit_fill_price: float,
    settings: ExecutionSettings,
    entry_fee_bps: float | None = None,
    exit_fee_bps: float | None = None,
) -> dict[str, float]:
    entry = _safe_float(entry_fill_price)
    exit_ = _safe_float(exit_fill_price)
    notional = max(0.0, _safe_float(settings.notional_quote))
    entry_fee_rate = max(0.0, _safe_float(settings.fee_bps if entry_fee_bps is None else entry_fee_bps)) / 10_000.0
    exit_fee_rate = max(0.0, _safe_float(settings.fee_bps if exit_fee_bps is None else exit_fee_bps)) / 10_000.0
    if entry <= 0 or exit_ <= 0 or notional <= 0:
        return {
            "quantity": 0.0,
            "entry_fee_quote": 0.0,
            "exit_fee_quote": 0.0,
            "gross_pnl_quote": 0.0,
            "net_pnl_quote": 0.0,
            "gross_return_pct": 0.0,
            "net_return_pct": 0.0,
            "fee_return_pct": 0.0,
        }

    qty = notional / entry
    exit_notional = qty * exit_
    direction = 1.0 if str(side).upper() == "LONG" else -1.0
    gross_pnl = (exit_ - entry) * qty * direction
    entry_fee = notional * entry_fee_rate
    exit_fee = exit_notional * exit_fee_rate
    total_fee = entry_fee + exit_fee
    net_pnl = gross_pnl - total_fee
    return {
        "quantity": qty,
        "entry_fee_quote": entry_fee,
        "exit_fee_quote": exit_fee,
        "gross_pnl_quote": gross_pnl,
        "net_pnl_quote": net_pnl,
        "gross_return_pct": gross_pnl / notional * 100.0,
        "net_return_pct": net_pnl / notional * 100.0,
        "fee_return_pct": total_fee / notional * 100.0,
    }
