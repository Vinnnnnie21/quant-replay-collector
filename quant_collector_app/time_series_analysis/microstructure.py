from __future__ import annotations

import numpy as np
import pandas as pd


HIGH_FREQUENCY_INTERVALS = {"1m", "3m", "5m"}
BID_ASK_BOUNCE_ACF_THRESHOLD = -0.15


def _returns(frame: pd.DataFrame) -> pd.Series:
    if "log_return" in frame.columns:
        return pd.to_numeric(frame["log_return"], errors="coerce").dropna()
    if "close" not in frame.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(frame["close"], errors="coerce")
    return np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()


def bid_ask_bounce_proxy(frame: pd.DataFrame) -> dict:
    values = _returns(frame)
    correlation = float(values.autocorr(1)) if len(values) >= 3 and values.nunique() > 1 else None
    warning = bool(correlation is not None and correlation < BID_ASK_BOUNCE_ACF_THRESHOLD)
    return {
        "lag1_return_autocorrelation": correlation,
        "diagnostic_threshold": BID_ASK_BOUNCE_ACF_THRESHOLD,
        "warning": warning,
        "interpretation": "negative lag-1 return dependence may reflect bid-ask bounce or high-frequency noise proxy; this is not a measured bid-ask spread",
    }


def zero_return_ratio(frame: pd.DataFrame) -> float | None:
    values = _returns(frame)
    return float((values == 0).mean()) if not values.empty else None


def high_low_range_ratio(frame: pd.DataFrame) -> float | None:
    if not {"high", "low", "close"}.issubset(frame.columns):
        return None
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce").replace(0, np.nan)
    values = ((high - low) / close).dropna()
    return float(values.mean()) if not values.empty else None


def volume_concentration(frame: pd.DataFrame) -> float | None:
    if "volume" not in frame.columns:
        return None
    values = pd.to_numeric(frame["volume"], errors="coerce").dropna().clip(lower=0)
    if values.empty or values.sum() <= 0:
        return None
    top_count = max(1, int(np.ceil(len(values) * 0.05)))
    return float(values.nlargest(top_count).sum() / values.sum())


def intraday_session_summary(frame: pd.DataFrame) -> list[dict]:
    time_column = "open_time_bjt" if "open_time_bjt" in frame.columns else "bar_open_time_bjt" if "bar_open_time_bjt" in frame.columns else None
    if not time_column:
        return []
    hours = pd.to_datetime(frame[time_column], format="mixed", errors="coerce").dt.hour
    values = _returns(frame)
    aligned = pd.DataFrame({"hour": hours, "return": values.reindex(frame.index)})
    aligned["session"] = pd.cut(aligned["hour"], [-1, 7, 15, 23], labels=["00-07", "08-15", "16-23"])
    summary = aligned.dropna(subset=["return"]).groupby("session", observed=False)["return"].agg(["count", "mean", "std"]).reset_index()
    return summary.to_dict("records")


def microstructure_diagnostics(frame: pd.DataFrame, interval: str | None = None) -> dict:
    high_frequency = str(interval or "") in HIGH_FREQUENCY_INTERVALS
    zero_ratio = zero_return_ratio(frame)
    bounce = bid_ask_bounce_proxy(frame)
    warnings: list[str] = []
    if high_frequency:
        warnings.append("short-interval K-lines are not tick or order-book observations")
    if bounce["warning"]:
        warnings.append("possible bid-ask bounce or high-frequency noise proxy detected; this is not a spread estimate")
    if zero_ratio is not None and zero_ratio > 0.25:
        warnings.append("high zero-return ratio may indicate sparse movement or aggregation effects")
    return {
        "interval": interval,
        "is_high_frequency_kline": high_frequency,
        "bid_ask_bounce_proxy": bounce,
        "zero_return_ratio": zero_ratio,
        "high_low_range_ratio": high_low_range_ratio(frame),
        "volume_concentration": volume_concentration(frame),
        "intraday_session_summary": intraday_session_summary(frame),
        "warnings": warnings,
        "limitation": "Without trade-level bid/ask or order-book data this module reports proxies only, not true spread.",
    }
