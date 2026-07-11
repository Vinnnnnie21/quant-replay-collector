from __future__ import annotations

import math
from typing import Iterable

try:
    from analytics.metrics import max_drawdown, payoff_ratio, sharpe_ratio
except ImportError:  # pragma: no cover - package import path
    from .analytics.metrics import max_drawdown, payoff_ratio, sharpe_ratio


SignedSegment = tuple[str, list[tuple[float, float]]]


def performance_curve_end(trades: Iterable[dict], cursor: int, row_count: int) -> int:
    """Return the exclusive bar bound covering replay state and recorded trades."""

    last_index = max(0, int(cursor))
    for trade in trades:
        for key in ("entry_bar_index", "exit_bar_index"):
            try:
                last_index = max(last_index, int(trade.get(key)))
            except (TypeError, ValueError):
                continue
    return min(max(0, int(row_count)), last_index + 1)


def smooth_curve_values(values: Iterable[float], window: int = 5) -> list[float]:
    """Create a display-only centered moving average while preserving endpoints."""

    points = [float(value) for value in values]
    if len(points) < 3:
        return points
    size = max(1, int(window))
    if size % 2 == 0:
        size += 1
    radius = size // 2
    smoothed = []
    for index in range(len(points)):
        start = max(0, index - radius)
        end = min(len(points), index + radius + 1)
        smoothed.append(sum(points[start:end]) / (end - start))
    smoothed[0] = points[0]
    smoothed[-1] = points[-1]
    return smoothed


def _side(value: float, baseline: float) -> str | None:
    if value > baseline:
        return "positive"
    if value < baseline:
        return "negative"
    return None


def split_signed_curve(values: Iterable[float], baseline: float) -> list[SignedSegment]:
    """Split a curve at exact baseline crossings for red/green rendering."""

    points = [float(value) for value in values]
    if not points or not all(math.isfinite(value) for value in points):
        return []
    if len(points) == 1:
        return [(_side(points[0], baseline) or "positive", [(0.0, points[0])])]

    first_side = _side(points[0], baseline)
    if first_side is None:
        first_side = next((_side(value, baseline) for value in points[1:] if _side(value, baseline)), "positive")
    current_side = first_side
    current_points: list[tuple[float, float]] = [(0.0, points[0])]
    segments: list[SignedSegment] = []

    for index in range(1, len(points)):
        previous = points[index - 1]
        value = points[index]
        next_side = _side(value, baseline) or current_side
        if next_side == current_side or previous == baseline:
            current_points.append((float(index), value))
            current_side = next_side
            continue

        crossing_x = float(index - 1) + (baseline - previous) / (value - previous)
        crossing = (crossing_x, float(baseline))
        current_points.append(crossing)
        segments.append((current_side, current_points))
        current_side = next_side
        current_points = [crossing, (float(index), value)]

    segments.append((current_side, current_points))
    return segments


def _number(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _trade_pnl(trade: dict, default_notional: float) -> float:
    if trade.get("net_pnl_quote") is not None:
        return _number(trade.get("net_pnl_quote"))
    notional = _number(trade.get("notional_quote"), default_notional)
    return _number(trade.get("net_return_pct"), _number(trade.get("final_return_pct"))) / 100.0 * notional


def build_performance_snapshot(
    *,
    equity_rows: Iterable[dict],
    trades: Iterable[dict],
    initial_equity: float,
    default_notional: float,
) -> dict:
    rows = [dict(row) for row in equity_rows]
    trade_rows = [dict(trade) for trade in trades]
    initial = max(0.0, _number(initial_equity, 10_000.0))
    notional = max(1.0, _number(default_notional, 1_000.0))
    equity_values = [
        _number(row.get("current_equity"), _number(row.get("equity_after"), initial))
        for row in rows
    ]
    current_equity = equity_values[-1] if equity_values else initial
    latest = rows[-1] if rows else {}
    closed = [trade for trade in trade_rows if str(trade.get("status") or "").upper() == "CLOSED"]
    pnls = [_trade_pnl(trade, notional) for trade in closed]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    realized = _number(latest.get("realized_net_pnl"), sum(pnls))
    unrealized = _number(latest.get("unrealized_pnl"), current_equity - initial - realized)
    total_pnl = current_equity - initial
    returns = [
        (equity_values[index] / equity_values[index - 1] - 1.0)
        for index in range(1, len(equity_values))
        if equity_values[index - 1] != 0
    ]
    drawdown = max_drawdown(equity_values or [initial]).get("max_drawdown_pct")
    metrics = {
        "current_equity": current_equity,
        "total_pnl": total_pnl,
        "total_return_pct": total_pnl / initial * 100.0 if initial > 0 else float("nan"),
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "win_rate_pct": len(wins) / len(closed) * 100.0 if closed else float("nan"),
        "payoff_ratio": payoff_ratio(pnls),
        "sharpe_ratio": sharpe_ratio(returns),
        "max_drawdown_pct": drawdown,
        "trade_count": len(closed),
        "open_position_count": len(trade_rows) - len(closed),
    }
    distribution = {
        "win_count": len(wins),
        "loss_count": len(losses),
        "average_win": sum(wins) / len(wins) if wins else 0.0,
        "average_loss": sum(losses) / len(losses) if losses else 0.0,
        "largest_win": max(wins) if wins else 0.0,
        "largest_loss": min(losses) if losses else 0.0,
        "gross_profit": sum(wins),
        "gross_loss": sum(losses),
    }
    return {
        "metrics": metrics,
        "distribution": distribution,
        "equity_values": equity_values,
        "pnl_values": [value - initial for value in equity_values],
        "trades": trade_rows,
        "closed_pnls": pnls,
    }


__all__ = [
    "SignedSegment",
    "build_performance_snapshot",
    "performance_curve_end",
    "smooth_curve_values",
    "split_signed_curve",
]
