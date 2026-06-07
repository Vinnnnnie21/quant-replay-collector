from __future__ import annotations

import math
from typing import Any

import pandas as pd

try:
    from analytics.metrics import (
        annualization_factor,
        calmar_ratio,
        conditional_value_at_risk,
        consecutive_win_loss_stats,
        expectancy,
        max_drawdown,
        payoff_ratio,
        profit_factor,
        safe_mean,
        sharpe_ratio,
        sortino_ratio,
        value_at_risk,
    )
except ImportError:  # pragma: no cover - package import path
    from .metrics import (
        annualization_factor,
        calmar_ratio,
        conditional_value_at_risk,
        consecutive_win_loss_stats,
        expectancy,
        max_drawdown,
        payoff_ratio,
        profit_factor,
        safe_mean,
        sharpe_ratio,
        sortino_ratio,
        value_at_risk,
    )


def _df(data) -> pd.DataFrame:
    if isinstance(data, pd.DataFrame):
        return data.copy()
    return pd.DataFrame(data or [])


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _trade_return(row: pd.Series) -> float | None:
    net = _num(row.get("net_return_pct"))
    if net is not None:
        return net
    return _num(row.get("final_return_pct"))


def _status(row: pd.Series) -> str:
    return str(row.get("status") or "").upper()


def _side(row: pd.Series) -> str:
    return str(row.get("side") or "").upper()


def _stats_for_side(df: pd.DataFrame, side: str) -> dict[str, Any]:
    part = df[df.apply(lambda r: _side(r) == side and _status(r) == "CLOSED", axis=1)] if not df.empty else pd.DataFrame()
    returns = [_trade_return(row) for _, row in part.iterrows()]
    returns = [r for r in returns if r is not None]
    wins = [r for r in returns if r > 0]
    return {
        f"{side.lower()}_total_trades": int(len(part)),
        f"{side.lower()}_win_rate_pct": (len(wins) / len(returns) * 100.0) if returns else None,
        f"{side.lower()}_average_return_pct": safe_mean(returns),
        f"{side.lower()}_profit_factor": profit_factor(returns),
    }


def _equity_values(equity_curve: pd.DataFrame, initial_equity: float | None) -> list[float]:
    if equity_curve.empty:
        return []
    for col in ("equity_after", "equity", "close_equity"):
        if col in equity_curve.columns:
            values = pd.to_numeric(equity_curve[col], errors="coerce").dropna().astype(float).tolist()
            if values:
                start = _num(initial_equity)
                return ([start] if start is not None and (not values or values[0] != start) else []) + values
    return []


def _time_returns_from_equity(values: list[float]) -> list[float]:
    returns = []
    for prev, cur in zip(values, values[1:]):
        if prev:
            returns.append((cur / prev - 1.0) * 100.0)
    return returns


def _basis(trades: pd.DataFrame) -> str:
    if not trades.empty:
        if "source" in trades.columns and trades["source"].astype(str).str.lower().eq("backtest").any():
            return "backtest_records"
        if "trade_id" in trades.columns and trades["trade_id"].astype(str).str.startswith("bt_").any():
            return "backtest_records"
    return "manual_replay_records"


def analyze_trades(
    trades: list[dict] | pd.DataFrame,
    equity_curve: list[dict] | pd.DataFrame | None = None,
    interval: str | None = None,
    initial_equity: float | None = None,
) -> dict:
    trade_df = _df(trades)
    equity_df = _df(equity_curve)
    if trade_df.empty:
        dd = max_drawdown(_equity_values(equity_df, initial_equity))
        return {
            "basis": "manual_replay_records",
            "total_trades": 0,
            "closed_trades": 0,
            "open_trades": 0,
            "win_rate_pct": None,
            "loss_rate_pct": None,
            "average_return_pct": None,
            "median_return_pct": None,
            "average_win_pct": None,
            "average_loss_pct": None,
            "max_profit_pct": None,
            "max_loss_pct": None,
            "profit_factor": None,
            "payoff_ratio": None,
            "expectancy_pct": None,
            "gross_profit_pct": None,
            "gross_loss_pct": None,
            "win_loss_ratio": None,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "initial_equity": initial_equity,
            "final_equity": initial_equity,
            "total_net_pnl": None,
            "total_return_pct": None,
            **dd,
            "recovery_factor": None,
            "trade_sharpe": None,
            "trade_sortino": None,
            "time_sharpe": None,
            "time_sortino": None,
            "calmar_ratio": None,
            "var_5_pct": None,
            "cvar_5_pct": None,
            **_stats_for_side(trade_df, "LONG"),
            **_stats_for_side(trade_df, "SHORT"),
        }

    closed_mask = trade_df.apply(lambda r: _status(r) == "CLOSED", axis=1)
    open_mask = trade_df.apply(lambda r: _status(r) == "OPEN", axis=1)
    closed = trade_df[closed_mask]
    returns = [_trade_return(row) for _, row in closed.iterrows()]
    returns = [r for r in returns if r is not None]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    eq_values = _equity_values(equity_df, initial_equity)
    dd = max_drawdown(eq_values)
    start_equity = _num(initial_equity)
    if start_equity is None and eq_values:
        start_equity = eq_values[0]
    final_equity = eq_values[-1] if eq_values else start_equity
    total_net_pnl = (final_equity - start_equity) if final_equity is not None and start_equity is not None else None
    total_return_pct = ((final_equity / start_equity - 1.0) * 100.0) if final_equity is not None and start_equity else None
    time_returns = _time_returns_from_equity(eq_values)
    periods = None
    if interval and time_returns:
        try:
            periods = annualization_factor(interval)
        except ValueError:
            periods = None
    cons = consecutive_win_loss_stats(returns)
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = sum(losses) if losses else 0.0
    result = {
        "basis": _basis(trade_df),
        "total_trades": int(len(trade_df)),
        "closed_trades": int(len(closed)),
        "open_trades": int(open_mask.sum()),
        "win_rate_pct": (len(wins) / len(returns) * 100.0) if returns else None,
        "loss_rate_pct": (len(losses) / len(returns) * 100.0) if returns else None,
        "average_return_pct": safe_mean(returns),
        "median_return_pct": float(pd.Series(returns).median()) if returns else None,
        "average_win_pct": safe_mean(wins),
        "average_loss_pct": safe_mean(losses),
        "max_profit_pct": max(wins) if wins else None,
        "max_loss_pct": min(losses) if losses else None,
        "profit_factor": profit_factor(returns),
        "payoff_ratio": payoff_ratio(returns),
        "expectancy_pct": expectancy(returns),
        "gross_profit_pct": gross_profit,
        "gross_loss_pct": gross_loss,
        "win_loss_ratio": (len(wins) / len(losses)) if losses else None,
        **cons,
        "initial_equity": start_equity,
        "final_equity": final_equity,
        "total_net_pnl": total_net_pnl,
        "total_return_pct": total_return_pct,
        **dd,
        "recovery_factor": (total_return_pct / abs(dd["max_drawdown_pct"])) if total_return_pct is not None and dd.get("max_drawdown_pct") not in (None, 0) else None,
        "trade_sharpe": sharpe_ratio(returns),
        "trade_sortino": sortino_ratio(returns),
        "time_sharpe": sharpe_ratio(time_returns, periods) if periods else None,
        "time_sortino": sortino_ratio(time_returns, periods) if periods else None,
        "calmar_ratio": calmar_ratio(total_return_pct, dd.get("max_drawdown_pct")),
        "var_5_pct": value_at_risk(returns, 0.05),
        "cvar_5_pct": conditional_value_at_risk(returns, 0.05),
    }
    result.update(_stats_for_side(trade_df, "LONG"))
    result.update(_stats_for_side(trade_df, "SHORT"))
    return result
