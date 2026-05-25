from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


RETURN_COLUMNS = [
    "source",
    "segment_id",
    "event_id",
    "is_segment_start",
    "bar_index",
    "open_time_bjt",
    "close",
    "simple_return",
    "log_return",
    "abs_return",
    "squared_return",
    "rolling_return_5",
    "rolling_return_10",
    "rolling_return_20",
    "rolling_volatility_20",
    "rolling_volatility_50",
    "realized_volatility_20",
    "downside_volatility_20",
    "high_low_range_pct",
    "close_position",
    "volume_zscore_20",
    "return_zscore_20",
]


def simple_return(close: pd.Series) -> pd.Series:
    prices = pd.to_numeric(close, errors="coerce")
    return prices.pct_change()


def log_return(close: pd.Series) -> pd.Series:
    prices = pd.to_numeric(close, errors="coerce")
    return np.log(prices / prices.shift(1)).replace([np.inf, -np.inf], np.nan)


def cumulative_log_return(log_ret: pd.Series) -> pd.Series:
    return pd.to_numeric(log_ret, errors="coerce").fillna(0.0).cumsum()


def annualized_log_return(log_ret: pd.Series, periods_per_year: int = 365 * 24 * 60) -> float | None:
    clean = pd.to_numeric(log_ret, errors="coerce").dropna()
    if clean.empty:
        return None
    return _finite_float(float(clean.mean()) * int(periods_per_year))


def annualized_return(log_ret: pd.Series, periods_per_year: int = 365 * 24 * 60) -> float | None:
    annual_log_return = annualized_log_return(log_ret, periods_per_year)
    if annual_log_return is None:
        return None
    try:
        return _finite_float(math.expm1(annual_log_return))
    except OverflowError:
        return None


def rolling_return(log_ret: pd.Series, window: int) -> pd.Series:
    return pd.to_numeric(log_ret, errors="coerce").rolling(max(1, int(window)), min_periods=1).sum()


def excess_return(log_ret: pd.Series, benchmark_log_ret: pd.Series | None = None) -> pd.Series:
    values = pd.to_numeric(log_ret, errors="coerce")
    if benchmark_log_ret is None:
        return values
    return values - pd.to_numeric(benchmark_log_ret, errors="coerce")


def _empty_returns() -> pd.DataFrame:
    return pd.DataFrame(columns=RETURN_COLUMNS)


def _safe_zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=2).mean()
    std = series.rolling(window, min_periods=2).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def _add_return_columns(out: pd.DataFrame, group_key: str | None = None) -> pd.DataFrame:
    close = out["close"]
    high_low = (out["high"] - out["low"]).replace(0, np.nan)
    if group_key:
        grouped_close = out.groupby(group_key, sort=False)["close"]
        simple_ret = grouped_close.pct_change()
        log_ret = np.log(close / grouped_close.shift(1)).replace([np.inf, -np.inf], np.nan)
        out["rolling_return_5"] = close / grouped_close.shift(5) - 1.0
        out["rolling_return_10"] = close / grouped_close.shift(10) - 1.0
        out["rolling_return_20"] = close / grouped_close.shift(20) - 1.0
        out["rolling_volatility_20"] = out.groupby(group_key, sort=False)["simple_return"].transform(
            lambda s: s.rolling(20, min_periods=2).std()
        ) if "simple_return" in out.columns else np.nan
    else:
        simple_ret = simple_return(close)
        log_ret = log_return(close)
        out["rolling_return_5"] = close / close.shift(5) - 1.0
        out["rolling_return_10"] = close / close.shift(10) - 1.0
        out["rolling_return_20"] = close / close.shift(20) - 1.0

    out["simple_return"] = simple_ret
    out["log_return"] = log_ret
    out["abs_return"] = log_ret.abs()
    out["squared_return"] = log_ret.pow(2)

    if group_key:
        out["rolling_volatility_20"] = out.groupby(group_key, sort=False)["log_return"].transform(
            lambda s: s.rolling(20, min_periods=2).std()
        )
        out["rolling_volatility_50"] = out.groupby(group_key, sort=False)["log_return"].transform(
            lambda s: s.rolling(50, min_periods=2).std()
        )
        out["realized_volatility_20"] = out.groupby(group_key, sort=False)["squared_return"].transform(
            lambda s: np.sqrt(s.rolling(20, min_periods=2).sum())
        )
        downside = out["log_return"].where(out["log_return"] < 0)
        out["downside_volatility_20"] = downside.groupby(out[group_key], sort=False).transform(
            lambda s: s.rolling(20, min_periods=2).std()
        )
        out["volume_zscore_20"] = out.groupby(group_key, sort=False)["volume"].transform(lambda s: _safe_zscore(s, 20))
        out["return_zscore_20"] = out.groupby(group_key, sort=False)["log_return"].transform(lambda s: _safe_zscore(s, 20))
    else:
        out["rolling_volatility_20"] = log_ret.rolling(20, min_periods=2).std()
        out["rolling_volatility_50"] = log_ret.rolling(50, min_periods=2).std()
        out["realized_volatility_20"] = np.sqrt(out["squared_return"].rolling(20, min_periods=2).sum())
        downside = log_ret.where(log_ret < 0)
        out["downside_volatility_20"] = downside.rolling(20, min_periods=2).std()
        out["volume_zscore_20"] = _safe_zscore(out["volume"], 20)
        out["return_zscore_20"] = _safe_zscore(log_ret, 20)

    out["high_low_range_pct"] = (out["high"] - out["low"]) / close.replace(0, np.nan)
    out["close_position"] = (out["close"] - out["low"]) / high_low
    return out


def build_return_series(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_returns()
    required = ["bar_index", "open_time_bjt", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return _empty_returns()

    out = df[required].copy()
    out = out.sort_values("bar_index").drop_duplicates("bar_index").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out.insert(0, "source", "full_session_klines")
    out.insert(1, "segment_id", "full_session")
    out.insert(2, "event_id", pd.NA)
    out.insert(3, "is_segment_start", False)
    if len(out):
        out.loc[out.index[0], "is_segment_start"] = True
    out = _add_return_columns(out)
    return out[RETURN_COLUMNS]


def build_event_window_return_series(windows: pd.DataFrame) -> pd.DataFrame:
    if windows is None or windows.empty:
        return _empty_returns()
    required = ["bar_index", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in windows.columns]
    if missing:
        return _empty_returns()

    df = windows.copy()
    if "open_time_bjt" not in df.columns and "bar_open_time_bjt" in df.columns:
        df["open_time_bjt"] = df["bar_open_time_bjt"]
    if "open_time_bjt" not in df.columns:
        df["open_time_bjt"] = ""

    for col in ["open", "high", "low", "close", "volume", "bar_index"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "event_id" in df.columns:
        sort_cols = ["event_id"]
        sort_cols.append("offset" if "offset" in df.columns else "bar_index")
        df = df.sort_values(sort_cols).drop_duplicates(["event_id", "bar_index"]).reset_index(drop=True)
        df["segment_id"] = df["event_id"].astype(str)
    else:
        df = df.sort_values("bar_index").drop_duplicates("bar_index").reset_index(drop=True)
        breaks = df["bar_index"].diff().fillna(1).ne(1).cumsum()
        df["segment_id"] = "segment_" + breaks.astype(str)
        df["event_id"] = pd.NA

    out = df[["segment_id", "event_id", "bar_index", "open_time_bjt", "open", "high", "low", "close", "volume"]].copy()
    out.insert(0, "source", "event_windows_only")
    out.insert(3, "is_segment_start", out.groupby("segment_id", sort=False).cumcount().eq(0))
    out = _add_return_columns(out, group_key="segment_id")
    return out[RETURN_COLUMNS]


def _finite_float(value: Any) -> float | None:
    try:
        x = float(value)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def _autocorr(series: pd.Series, lag: int) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) <= lag + 1:
        return None
    if clean.iloc[:-lag].nunique() < 2 or clean.iloc[lag:].nunique() < 2:
        return None
    return _finite_float(clean.autocorr(lag=lag))


def summarize_return_distribution(returns_df: pd.DataFrame) -> dict:
    if returns_df is None or returns_df.empty or not {"simple_return", "log_return"}.intersection(returns_df.columns):
        return {
            "return_definition": "log_return",
            "sample_count": 0,
            "mean_return": None,
            "median_return": None,
            "std_return": None,
            "skewness": None,
            "kurtosis": None,
            "positive_return_pct": None,
            "negative_return_pct": None,
            "q01": None,
            "q05": None,
            "q95": None,
            "q99": None,
            "max_return": None,
            "min_return": None,
            "autocorr_lag_1": None,
            "autocorr_lag_3": None,
            "autocorr_lag_5": None,
            "squared_return_autocorr_lag_1": None,
            "squared_return_autocorr_lag_5": None,
        }
    return_column = "log_return" if "log_return" in returns_df.columns else "simple_return"
    ret = pd.to_numeric(returns_df[return_column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if ret.empty:
        return summarize_return_distribution(pd.DataFrame())
    squared = ret.pow(2)
    return {
        "return_definition": return_column,
        "sample_count": int(len(ret)),
        "mean_return": _finite_float(ret.mean()),
        "median_return": _finite_float(ret.median()),
        "std_return": _finite_float(ret.std()),
        "skewness": _finite_float(ret.skew()),
        "kurtosis": _finite_float(ret.kurt()),
        "positive_return_pct": _finite_float((ret > 0).mean() * 100.0),
        "negative_return_pct": _finite_float((ret < 0).mean() * 100.0),
        "q01": _finite_float(ret.quantile(0.01)),
        "q05": _finite_float(ret.quantile(0.05)),
        "q95": _finite_float(ret.quantile(0.95)),
        "q99": _finite_float(ret.quantile(0.99)),
        "max_return": _finite_float(ret.max()),
        "min_return": _finite_float(ret.min()),
        "autocorr_lag_1": _autocorr(ret, 1),
        "autocorr_lag_3": _autocorr(ret, 3),
        "autocorr_lag_5": _autocorr(ret, 5),
        "squared_return_autocorr_lag_1": _autocorr(squared, 1),
        "squared_return_autocorr_lag_5": _autocorr(squared, 5),
    }
