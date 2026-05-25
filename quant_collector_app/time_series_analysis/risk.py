from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

from .volatility import ewma_volatility


def _clean(values) -> pd.Series:
    return pd.to_numeric(pd.Series(values), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def historical_var(log_ret, confidence: float = 0.95) -> float | None:
    losses = -_clean(log_ret)
    return float(losses.quantile(confidence)) if not losses.empty else None


def historical_expected_shortfall(log_ret, confidence: float = 0.95) -> float | None:
    losses = -_clean(log_ret)
    if losses.empty:
        return None
    threshold = losses.quantile(confidence)
    tail = losses[losses >= threshold]
    return float(tail.mean()) if not tail.empty else float(threshold)


def normal_var(log_ret, confidence: float = 0.95) -> float | None:
    returns = _clean(log_ret)
    if returns.empty:
        return None
    mean_loss = -float(returns.mean())
    sigma = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    return mean_loss + sigma * NormalDist().inv_cdf(confidence)


def normal_expected_shortfall(log_ret, confidence: float = 0.95) -> float | None:
    returns = _clean(log_ret)
    if returns.empty:
        return None
    mean_loss = -float(returns.mean())
    sigma = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    z_value = NormalDist().inv_cdf(confidence)
    density = math.exp(-(z_value**2) / 2.0) / math.sqrt(2.0 * math.pi)
    return mean_loss + sigma * density / (1.0 - confidence)


def ewma_var(log_ret, confidence: float = 0.95, lambda_: float = 0.94) -> float | None:
    returns = _clean(log_ret)
    volatility = ewma_volatility(returns, lambda_).dropna()
    if returns.empty or volatility.empty:
        return None
    return -float(returns.mean()) + float(volatility.iloc[-1]) * NormalDist().inv_cdf(confidence)


def ewma_expected_shortfall(log_ret, confidence: float = 0.95, lambda_: float = 0.94) -> float | None:
    returns = _clean(log_ret)
    volatility = ewma_volatility(returns, lambda_).dropna()
    if returns.empty or volatility.empty:
        return None
    z_value = NormalDist().inv_cdf(confidence)
    density = math.exp(-(z_value**2) / 2.0) / math.sqrt(2.0 * math.pi)
    return -float(returns.mean()) + float(volatility.iloc[-1]) * density / (1.0 - confidence)


def drawdown(log_ret) -> pd.Series:
    cumulative = _clean(log_ret).cumsum()
    wealth = np.exp(cumulative)
    return wealth / wealth.cummax() - 1.0


def max_drawdown(log_ret) -> float | None:
    values = drawdown(log_ret)
    return float(values.min()) if not values.empty else None


def tail_loss_ratio(log_ret) -> float | None:
    var95 = historical_var(log_ret, 0.95)
    es95 = historical_expected_shortfall(log_ret, 0.95)
    if var95 is None or es95 is None or var95 <= 0:
        return None
    return float(es95 / var95)


def risk_summary(log_ret) -> dict:
    return {
        "loss_convention": "positive values represent losses",
        "historical_var_95": historical_var(log_ret, 0.95),
        "historical_es_95": historical_expected_shortfall(log_ret, 0.95),
        "historical_var_99": historical_var(log_ret, 0.99),
        "historical_es_99": historical_expected_shortfall(log_ret, 0.99),
        "normal_var_95": normal_var(log_ret, 0.95),
        "normal_es_95": normal_expected_shortfall(log_ret, 0.95),
        "ewma_var_95": ewma_var(log_ret, 0.95),
        "ewma_es_95": ewma_expected_shortfall(log_ret, 0.95),
        "max_drawdown": max_drawdown(log_ret),
        "tail_loss_ratio": tail_loss_ratio(log_ret),
        "warning": "VaR may understate losses beyond its threshold; ES complements tail-loss review.",
    }
