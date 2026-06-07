from __future__ import annotations

import math
from typing import Any

import pandas as pd

try:
    from ..analytics.metrics import expectancy, max_drawdown, profit_factor, safe_mean
except ImportError:  # Compatibility with the project's legacy top-level imports.
    from analytics.metrics import expectancy, max_drawdown, profit_factor, safe_mean


def summarize_backtest_result(
    trades: pd.DataFrame | list[dict[str, Any]],
    equity_curve: pd.DataFrame | list[dict[str, Any]] | None = None,
    *,
    initial_equity: float | None = None,
) -> dict[str, Any]:
    """Summarize historical simulation records without producing a signal."""
    trade_df = _frame(trades)
    equity_df = _frame(equity_curve)
    closed = _closed_trades(trade_df)
    returns = _numeric_values(closed, "net_return_pct")
    if not returns:
        returns = _numeric_values(closed, "final_return_pct")
    holding_bars = _numeric_values(closed, "holding_bars")
    wins = [value for value in returns if value > 0]

    equity_values = _equity_values(equity_df)
    total_return = None
    if initial_equity is not None and equity_values and float(initial_equity) != 0:
        total_return = (equity_values[-1] / float(initial_equity) - 1.0) * 100.0
    elif returns:
        total_return = float(sum(returns))
    drawdown = max_drawdown(equity_values)

    return {
        "total_trades": int(len(trade_df)),
        "closed_trades": int(len(closed)),
        "win_rate": (len(wins) / len(returns) * 100.0) if returns else None,
        "avg_return": safe_mean(returns),
        "median_return": float(pd.Series(returns).median()) if returns else None,
        "total_return": total_return,
        "max_drawdown": drawdown.get("max_drawdown_pct"),
        "profit_factor": profit_factor(returns),
        "expectancy": expectancy(returns),
        "avg_holding_bars": safe_mean(holding_bars),
        "max_holding_bars": int(max(holding_bars)) if holding_bars else None,
        "fee_total": _fee_total(closed),
        "slippage_total": _slippage_total(closed),
        "hit_tp_count": _exit_reason_count(closed, "take_profit"),
        "hit_sl_count": _exit_reason_count(closed, "stop_loss"),
        "timeout_exit_count": _exit_reason_count(closed, "max_bars_hold"),
        "warnings": [
            "Historical backtest summary is a rule-hypothesis diagnostic, not a trading signal or future-return forecast."
        ],
    }


def _exit_reason_count(closed: pd.DataFrame, reason: str) -> int:
    if closed.empty or "exit_reason" not in closed.columns:
        return 0
    return int(closed["exit_reason"].astype(str).str.lower().eq(reason).sum())


def _frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.DataFrame(value or [])


def _closed_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    if "status" not in trades.columns:
        return trades.copy()
    return trades[trades["status"].astype(str).str.upper().eq("CLOSED")].copy()


def _numeric_values(frame: pd.DataFrame, column: str) -> list[float]:
    if frame.empty or column not in frame.columns:
        return []
    values = pd.to_numeric(frame[column], errors="coerce").dropna().astype(float)
    return [float(value) for value in values if math.isfinite(float(value))]


def _equity_values(equity_curve: pd.DataFrame) -> list[float]:
    for column in ("equity_after", "equity", "close_equity"):
        values = _numeric_values(equity_curve, column)
        if values:
            return values
    return []


def _fee_total(closed: pd.DataFrame) -> float:
    if closed.empty:
        return 0.0
    if "fee_total" in closed.columns:
        return float(sum(_numeric_values(closed, "fee_total")))
    return float(
        sum(_numeric_values(closed, "entry_fee_quote"))
        + sum(_numeric_values(closed, "exit_fee_quote"))
    )


def _slippage_total(closed: pd.DataFrame) -> float:
    if closed.empty:
        return 0.0
    if "slippage_quote" in closed.columns:
        return float(sum(_numeric_values(closed, "slippage_quote")))
    required = {
        "quantity",
        "entry_price_raw",
        "entry_fill_price",
        "exit_price_raw",
        "exit_fill_price",
    }
    if not required <= set(closed.columns):
        return 0.0
    total = 0.0
    for _, row in closed.iterrows():
        values = [_finite(row.get(column)) for column in required]
        if any(value is None for value in values):
            continue
        quantity = _finite(row.get("quantity"))
        if quantity is None:
            continue
        total += abs(float(row["entry_fill_price"]) - float(row["entry_price_raw"])) * quantity
        total += abs(float(row["exit_price_raw"]) - float(row["exit_fill_price"])) * quantity
    return float(total)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = ["summarize_backtest_result"]
