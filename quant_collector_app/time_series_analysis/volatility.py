from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .autocorrelation import acf, ljung_box_test


def _clean(values) -> pd.Series:
    return pd.to_numeric(pd.Series(values), errors="coerce").replace([np.inf, -np.inf], np.nan)


def rolling_volatility(log_ret, window: int = 20) -> pd.Series:
    return _clean(log_ret).rolling(max(2, int(window)), min_periods=2).std()


def realized_volatility(log_ret, window: int = 20) -> pd.Series:
    return np.sqrt(_clean(log_ret).pow(2).rolling(max(2, int(window)), min_periods=2).sum())


def ewma_volatility(log_ret, lambda_: float = 0.94) -> pd.Series:
    values = _clean(log_ret)
    variance: list[float] = []
    current = math.nan
    for value in values:
        if pd.isna(value):
            variance.append(current)
            continue
        if math.isnan(current):
            current = float(value) ** 2
        else:
            current = float(lambda_) * current + (1.0 - float(lambda_)) * float(value) ** 2
        variance.append(current)
    return pd.Series(np.sqrt(variance), index=values.index)


def volatility_regime(volatility_values) -> dict:
    values = _clean(volatility_values).dropna()
    if values.empty:
        return {"current_volatility": None, "volatility_percentile": None, "regime": "UNKNOWN"}
    current = float(values.iloc[-1])
    percentile = float((values <= current).mean() * 100.0)
    regime = "LOW" if percentile <= 25 else "MID" if percentile <= 75 else "HIGH" if percentile <= 95 else "EXTREME"
    return {"current_volatility": current, "volatility_percentile": percentile, "regime": regime}


def volatility_clustering_score(log_ret, max_lag: int = 10) -> dict:
    squared = _clean(log_ret).dropna().pow(2)
    correlations = acf(squared, max_lag)
    nonzero = correlations[correlations["lag"] > 0]["acf"].dropna()
    score = float(nonzero.abs().mean()) if not nonzero.empty else None
    test = ljung_box_test(squared, max_lag)
    warning = bool(not test.empty and test["significant"].any())
    return {"score": score, "squared_return_acf": correlations.to_dict("records"), "warning": warning}


def arch_effect_proxy(log_ret, lags: int = 10) -> dict:
    test = ljung_box_test(_clean(log_ret).dropna().pow(2), lags)
    significant = bool(not test.empty and test["significant"].any())
    return {
        "test": test.to_dict("records"),
        "arch_proxy_warning": significant,
        "note": "This is a squared-return dependence proxy, not a fitted ARCH/GARCH model.",
    }


def volatility_diagnostics(log_ret, window: int = 20) -> dict:
    rolling = rolling_volatility(log_ret, window)
    realized = realized_volatility(log_ret, window)
    ewma = ewma_volatility(log_ret)
    return {
        "rolling_volatility_current": float(rolling.dropna().iloc[-1]) if rolling.notna().any() else None,
        "realized_volatility_current": float(realized.dropna().iloc[-1]) if realized.notna().any() else None,
        "ewma_volatility_current": float(ewma.dropna().iloc[-1]) if ewma.notna().any() else None,
        **volatility_regime(ewma),
        "clustering": volatility_clustering_score(log_ret),
        "arch_effect_proxy": arch_effect_proxy(log_ret),
    }
