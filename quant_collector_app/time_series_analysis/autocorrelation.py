from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd


def _clean(values) -> pd.Series:
    return pd.to_numeric(pd.Series(values), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def acf(values, max_lag: int = 20) -> pd.DataFrame:
    clean = _clean(values)
    rows = []
    max_lag = max(0, min(int(max_lag), max(0, len(clean) - 1)))
    for lag in range(max_lag + 1):
        if lag == 0:
            correlation = 1.0 if len(clean) else math.nan
        elif clean.iloc[:-lag].nunique() < 2 or clean.iloc[lag:].nunique() < 2:
            correlation = math.nan
        else:
            correlation = float(clean.autocorr(lag=lag))
        rows.append({"lag": lag, "acf": correlation, "sample_count": int(len(clean) - lag)})
    return pd.DataFrame(rows)


def pacf(values, max_lag: int = 20) -> dict:
    clean = _clean(values)
    try:
        from statsmodels.tsa.stattools import pacf as statsmodels_pacf
    except ImportError:
        return {"available": False, "values": [], "warning": "statsmodels unavailable; PACF skipped"}
    if len(clean) <= 2:
        return {"available": False, "values": [], "warning": "insufficient sample for PACF"}
    lags = min(int(max_lag), max(1, len(clean) // 2 - 1))
    return {"available": True, "values": list(map(float, statsmodels_pacf(clean.to_numpy(), nlags=lags))), "warning": None}


def _chi_square_survival(statistic: float, df: int) -> tuple[float, str]:
    try:
        from scipy.stats import chi2
    except ImportError:
        chi2 = None
    if statistic <= 0:
        return 1.0, "scipy_chi2_sf" if chi2 is not None else "normal_approximation"
    if chi2 is not None:
        return float(chi2.sf(statistic, df)), "scipy_chi2_sf"
    if df == 2:
        return math.exp(-statistic / 2.0), "normal_approximation"
    # Wilson-Hilferty transform provides a stable diagnostic fallback without scipy.
    z = ((statistic / df) ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * df))) / math.sqrt(2.0 / (9.0 * df))
    return max(0.0, min(1.0, 1.0 - NormalDist().cdf(z))), "normal_approximation"


def ljung_box_test(values, lags: int | list[int] = 10) -> pd.DataFrame:
    clean = _clean(values)
    requests = [int(lags)] if isinstance(lags, int) else sorted({int(lag) for lag in lags})
    rows = []
    for requested_lag in requests:
        lag = max(1, min(requested_lag, max(1, len(clean) - 1)))
        correlations = acf(clean, lag)
        terms = correlations[correlations["lag"] > 0].dropna(subset=["acf"])
        if len(clean) <= lag or terms.empty:
            rows.append({"lag": requested_lag, "statistic": math.nan, "p_value": math.nan, "p_value_method": "unavailable", "significant": False, "warning": "insufficient sample"})
            continue
        statistic = float(len(clean) * (len(clean) + 2) * ((terms["acf"] ** 2) / (len(clean) - terms["lag"])).sum())
        p_value, method = _chi_square_survival(statistic, lag)
        warning = "scipy unavailable; Ljung-Box p-value uses a diagnostic approximation" if method == "normal_approximation" else None
        rows.append({"lag": requested_lag, "statistic": statistic, "p_value": p_value, "p_value_method": method, "significant": bool(p_value < 0.05), "warning": warning})
    return pd.DataFrame(rows)


def white_noise_diagnostic(values, lags: int = 10) -> dict:
    clean = _clean(values)
    returns_test = ljung_box_test(clean, lags)
    squared_test = ljung_box_test(clean.pow(2), lags)
    absolute_test = ljung_box_test(clean.abs(), lags)
    returns_significant = bool(returns_test["significant"].any()) if not returns_test.empty else False
    volatility_significant = bool(squared_test["significant"].any() or absolute_test["significant"].any()) if not squared_test.empty else False
    warnings = []
    if returns_significant:
        warnings.append("returns exhibit serial dependence under the Ljung-Box diagnostic")
    if volatility_significant:
        warnings.append("squared or absolute returns indicate volatility clustering")
    return {
        "sample_count": int(len(clean)),
        "return_ljung_box": returns_test.to_dict("records"),
        "squared_return_ljung_box": squared_test.to_dict("records"),
        "absolute_return_ljung_box": absolute_test.to_dict("records"),
        "return_white_noise_rejected": returns_significant,
        "volatility_clustering_warning": volatility_significant,
        "warnings": warnings,
    }
