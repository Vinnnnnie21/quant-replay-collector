from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np


INTERVAL_PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "3m": 365 * 24 * 20,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "30m": 365 * 24 * 2,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}


def _clean(values: Iterable[Any] | None) -> list[float]:
    if values is None:
        return []
    out: list[float] = []
    for value in values:
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(num):
            out.append(num)
    return out


def safe_mean(values) -> float | None:
    clean = _clean(values)
    return float(np.mean(clean)) if clean else None


def safe_std(values) -> float | None:
    clean = _clean(values)
    if len(clean) < 2:
        return None
    return float(np.std(clean, ddof=1))


def max_drawdown(equity_values) -> dict:
    values = _clean(equity_values)
    if not values:
        return {"max_drawdown_pct": None, "max_drawdown_start": None, "max_drawdown_end": None}
    peak = values[0]
    peak_idx = 0
    worst = 0.0
    start = 0
    end = 0
    for idx, value in enumerate(values):
        if value > peak:
            peak = value
            peak_idx = idx
        if peak > 0:
            dd = (value / peak - 1.0) * 100.0
            if dd < worst:
                worst = dd
                start = peak_idx
                end = idx
    return {"max_drawdown_pct": float(worst), "max_drawdown_start": start, "max_drawdown_end": end}


def annualization_factor(interval: str) -> float:
    key = str(interval or "").strip()
    if key not in INTERVAL_PERIODS_PER_YEAR:
        raise ValueError(f"Unsupported interval for annualization: {interval}")
    return float(INTERVAL_PERIODS_PER_YEAR[key])


def sharpe_ratio(returns, periods_per_year=None, risk_free_rate=0.0) -> float | None:
    clean = _clean(returns)
    if len(clean) < 2:
        return None
    rf = float(risk_free_rate or 0.0)
    if periods_per_year:
        rf = rf / float(periods_per_year)
    excess = [r - rf for r in clean]
    std = safe_std(excess)
    mean = safe_mean(excess)
    if std in (None, 0) or mean is None:
        return None
    ratio = mean / std
    if periods_per_year:
        ratio *= math.sqrt(float(periods_per_year))
    return float(ratio)


def sortino_ratio(returns, periods_per_year=None, risk_free_rate=0.0) -> float | None:
    clean = _clean(returns)
    if len(clean) < 2:
        return None
    rf = float(risk_free_rate or 0.0)
    if periods_per_year:
        rf = rf / float(periods_per_year)
    excess = [r - rf for r in clean]
    downside = [r for r in excess if r < 0]
    if not downside:
        return None
    downside_std = safe_std(downside) or (abs(downside[0]) if len(downside) == 1 else None)
    mean = safe_mean(excess)
    if downside_std in (None, 0) or mean is None:
        return None
    ratio = mean / downside_std
    if periods_per_year:
        ratio *= math.sqrt(float(periods_per_year))
    return float(ratio)


def calmar_ratio(total_return_pct, max_drawdown_pct, years=None) -> float | None:
    try:
        total = float(total_return_pct)
        dd = abs(float(max_drawdown_pct))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(total) or not math.isfinite(dd) or dd == 0:
        return None
    if years and years > 0:
        total = total / float(years)
    return float(total / dd)


def profit_factor(returns) -> float | None:
    clean = _clean(returns)
    wins = [r for r in clean if r > 0]
    losses = [r for r in clean if r < 0]
    if not wins or not losses:
        return None
    return float(sum(wins) / abs(sum(losses)))


def payoff_ratio(returns) -> float | None:
    clean = _clean(returns)
    wins = [r for r in clean if r > 0]
    losses = [r for r in clean if r < 0]
    avg_win = safe_mean(wins)
    avg_loss = safe_mean(losses)
    if avg_win is None or avg_loss in (None, 0):
        return None
    return float(avg_win / abs(avg_loss))


def expectancy(returns) -> float | None:
    return safe_mean(returns)


def consecutive_win_loss_stats(returns) -> dict:
    max_wins = 0
    max_losses = 0
    cur_wins = 0
    cur_losses = 0
    for value in _clean(returns):
        if value > 0:
            cur_wins += 1
            cur_losses = 0
        elif value < 0:
            cur_losses += 1
            cur_wins = 0
        else:
            cur_wins = 0
            cur_losses = 0
        max_wins = max(max_wins, cur_wins)
        max_losses = max(max_losses, cur_losses)
    return {"max_consecutive_wins": max_wins, "max_consecutive_losses": max_losses}


def value_at_risk(returns, level=0.05) -> float | None:
    clean = _clean(returns)
    if not clean:
        return None
    return float(np.quantile(clean, float(level)))


def conditional_value_at_risk(returns, level=0.05) -> float | None:
    clean = _clean(returns)
    if not clean:
        return None
    var = value_at_risk(clean, level)
    tail = [r for r in clean if var is not None and r <= var]
    return safe_mean(tail)
