from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Any, Iterable

import numpy as np
import pandas as pd


ALLOWED_LOOKBACK_BARS = (20, 50, 100)
FORBIDDEN_CONTEXT_TOKENS = (
    "fwd",
    "post",
    "future",
    "mfe",
    "mae",
    "hit_tp",
    "hit_sl",
    "pnl",
    "exit",
    "label",
)
CONTEXT_COLUMNS = [
    "context_feature_id",
    "sample_id",
    "session_id",
    "feature_version",
    "symbol",
    "interval",
    "bar_index",
    "lookback_bars",
    "feature_name",
    "feature_value",
    "created_at",
]


def validate_context_feature_name(name: str) -> str:
    value = str(name or "").strip()
    lowered = value.lower()
    if not value or any(token in lowered for token in FORBIDDEN_CONTEXT_TOKENS):
        raise ValueError(f"Forbidden context feature name: {name}")
    return value


def _validate_lookback_bars(lookback_bars: int) -> int:
    value = int(lookback_bars)
    if value not in ALLOWED_LOOKBACK_BARS:
        raise ValueError(f"Unsupported lookback_bars: {lookback_bars}")
    return value


def build_context_feature_id(
    sample_id: str,
    feature_version: str,
    lookback_bars: int,
    feature_name: str,
) -> str:
    window = _validate_lookback_bars(lookback_bars)
    name = validate_context_feature_name(feature_name)
    payload = "|".join([str(sample_id), str(feature_version), str(window), name])
    return "ctx_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _return(first: float, last: float, logarithmic: bool = False) -> float | None:
    if not math.isfinite(first) or not math.isfinite(last) or first <= 0:
        return None
    ratio = last / first
    if ratio <= 0:
        return None
    return float(math.log(ratio)) if logarithmic else float(ratio - 1.0)


def _zscore(last: float, series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(values) < 2:
        return None
    std = float(values.std(ddof=0))
    if not math.isfinite(std) or std == 0:
        return 0.0
    return _finite((last - float(values.mean())) / std)


def _max_drawdown(close: pd.Series) -> float | None:
    values = pd.to_numeric(close, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return None
    running_max = values.cummax()
    drawdowns = values / running_max - 1.0
    return _finite(drawdowns.min())


def _feature_row(sample: dict[str, Any], feature_version: str, window: int, name: str, value: Any) -> dict[str, Any]:
    feature_name = validate_context_feature_name(name)
    return {
        "context_feature_id": build_context_feature_id(sample["sample_id"], feature_version, window, feature_name),
        "sample_id": str(sample["sample_id"]),
        "session_id": str(sample["session_id"]),
        "feature_version": str(feature_version),
        "symbol": str(sample["symbol"]).upper(),
        "interval": str(sample["interval"]),
        "bar_index": int(sample["bar_index"]),
        "lookback_bars": window,
        "feature_name": feature_name,
        "feature_value": _finite(value),
        "created_at": sample.get("created_at") or datetime.now(UTC).isoformat(timespec="seconds"),
    }


def compute_context_features_for_sample(
    klines: pd.DataFrame,
    sample: dict[str, Any],
    lookback_bars: int,
    feature_version: str = "context_v1",
) -> pd.DataFrame:
    window = _validate_lookback_bars(lookback_bars)
    required = {"bar_index", "high", "low", "close", "volume"}
    if not isinstance(klines, pd.DataFrame):
        raise ValueError(f"Missing kline columns: {sorted(required)}")
    missing = required.difference(klines.columns)
    if missing:
        raise ValueError(f"Missing kline columns: {sorted(missing)}")
    event_index = int(sample["bar_index"])
    visible = klines[pd.to_numeric(klines["bar_index"], errors="coerce") <= event_index].copy()
    visible = visible.sort_values("bar_index", kind="stable").tail(window)
    rows = [
        _feature_row(sample, feature_version, window, "available_bars", len(visible)),
        _feature_row(sample, feature_version, window, "insufficient_history", int(len(visible) < window)),
    ]
    if len(visible) < window:
        return pd.DataFrame(rows, columns=CONTEXT_COLUMNS)

    close = pd.to_numeric(visible["close"], errors="coerce")
    high = pd.to_numeric(visible["high"], errors="coerce")
    low = pd.to_numeric(visible["low"], errors="coerce")
    volume = pd.to_numeric(visible["volume"], errors="coerce")
    log_returns = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    downside = log_returns[log_returns < 0]
    range_log = np.log(high / low).replace([np.inf, -np.inf], np.nan)
    x = np.arange(len(close), dtype=float)
    valid_close = close.replace([np.inf, -np.inf], np.nan).dropna()
    trend_slope = None
    if len(valid_close) == len(close) and len(close) >= 2 and (close > 0).all():
        trend_slope = float(np.polyfit(x, np.log(close.to_numpy(dtype=float)), 1)[0])
    last_close = _finite(close.iloc[-1])
    metrics: Iterable[tuple[str, Any]] = (
        ("pre_log_ret", _return(float(close.iloc[0]), float(close.iloc[-1]), logarithmic=True)),
        ("pre_simple_ret", _return(float(close.iloc[0]), float(close.iloc[-1]))),
        ("realized_vol", log_returns.std(ddof=0) if not log_returns.empty else None),
        ("downside_vol", downside.std(ddof=0) if not downside.empty else 0.0),
        ("max_drawdown", _max_drawdown(close)),
        ("range_mean", range_log.mean()),
        ("range_zscore", _zscore(float(range_log.iloc[-1]), range_log)),
        ("volume_zscore", _zscore(float(volume.iloc[-1]), volume)),
        ("trend_slope", trend_slope),
        ("distance_to_high", _return(float(high.max()), last_close) if last_close is not None else None),
        ("distance_to_low", _return(float(low.min()), last_close) if last_close is not None else None),
    )
    rows.extend(_feature_row(sample, feature_version, window, name, value) for name, value in metrics)
    return pd.DataFrame(rows, columns=CONTEXT_COLUMNS)


def compute_multi_window_context_features(
    klines: pd.DataFrame,
    sample: dict[str, Any],
    windows: tuple[int, ...] = ALLOWED_LOOKBACK_BARS,
    feature_version: str = "context_v1",
) -> pd.DataFrame:
    frames = [
        compute_context_features_for_sample(klines, sample, window, feature_version)
        for window in windows
    ]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CONTEXT_COLUMNS)


__all__ = [
    "ALLOWED_LOOKBACK_BARS",
    "FORBIDDEN_CONTEXT_TOKENS",
    "build_context_feature_id",
    "compute_context_features_for_sample",
    "compute_multi_window_context_features",
    "validate_context_feature_name",
]
