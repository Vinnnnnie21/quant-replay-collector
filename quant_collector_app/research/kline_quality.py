from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

try:
    from market_data.types import interval_to_ms
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms


REQUIRED_KLINE_COLUMNS = ("open", "high", "low", "close", "volume")
TIME_COLUMNS = ("open_time_utc_ms", "open_time_ms", "open_time", "timestamp", "open_time_bjt")
CANDLE_ID_ALGORITHM = "sha256(symbol|interval|normalized_open_time)[:32]"


def build_candle_id(symbol: str, interval: str, open_time: Any, length: int = 32) -> str:
    """Build a stable candle identifier from symbol, interval and open time."""
    size = int(length)
    if size <= 0 or size > 64:
        raise ValueError("length must be between 1 and 64")
    payload = f"{str(symbol).upper()}|{str(interval)}|{_open_time_key(open_time)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:size]


def attach_candle_ids(
    klines: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    time_col: str | None = None,
    column: str = "candle_id",
) -> pd.DataFrame:
    """Return a copy with stable candle_id values; raw OHLCV columns are untouched."""
    if not isinstance(klines, pd.DataFrame):
        raise ValueError("klines must be a pandas DataFrame")
    resolved_time_col = _resolve_time_column(klines, time_col)
    if resolved_time_col is None:
        raise ValueError("Missing kline time column: open_time_utc_ms, open_time_ms, open_time, timestamp or open_time_bjt")
    out = klines.copy()
    open_times = _normalized_open_time_values(out[resolved_time_col])
    out[column] = [
        build_candle_id(symbol, interval, normalized if normalized is not None else raw)
        for raw, normalized in zip(out[resolved_time_col], open_times, strict=False)
    ]
    return out


def build_kline_quality_report(
    klines: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    time_col: str | None = None,
) -> dict[str, Any]:
    """Audit raw OHLCV quality without mutating or cleaning the input frame."""
    if not isinstance(klines, pd.DataFrame):
        raise ValueError("klines must be a pandas DataFrame")
    frame = klines.copy()
    row_count = int(len(frame))
    resolved_time_col = _resolve_time_column(frame, time_col)
    missing_required = [column for column in REQUIRED_KLINE_COLUMNS if column not in frame.columns]

    open_time_ms = _open_time_ms(frame[resolved_time_col]) if resolved_time_col else pd.Series([np.nan] * row_count)
    valid_open_time_ms = pd.to_numeric(open_time_ms, errors="coerce").dropna().astype("int64")
    unique_open_time_ms = valid_open_time_ms.drop_duplicates().sort_values(kind="stable")
    step_ms = interval_to_ms(interval)

    duplicate_bars = int(valid_open_time_ms.duplicated().sum())
    missing_time_rows = int(row_count - len(valid_open_time_ms))
    out_of_order_bars = int((valid_open_time_ms.diff().dropna() < 0).sum())
    missing_bars = _count_missing_bars(unique_open_time_ms, step_ms)
    expected_bars = _expected_bar_count(unique_open_time_ms, step_ms)

    invalid_ohlc_rows, non_numeric_ohlcv_rows = _ohlc_issues(frame)
    missing_volume_rows, negative_volume_rows = _volume_issues(frame)
    warnings = _quality_warnings(
        missing_required=missing_required,
        missing_time_rows=missing_time_rows,
        missing_bars=missing_bars,
        duplicate_bars=duplicate_bars,
        out_of_order_bars=out_of_order_bars,
        invalid_ohlc_rows=invalid_ohlc_rows,
        non_numeric_ohlcv_rows=non_numeric_ohlcv_rows,
        missing_volume_rows=missing_volume_rows,
        negative_volume_rows=negative_volume_rows,
    )
    quality_status = _quality_status(
        missing_required=missing_required,
        missing_time_rows=missing_time_rows,
        invalid_ohlc_rows=invalid_ohlc_rows,
        non_numeric_ohlcv_rows=non_numeric_ohlcv_rows,
        missing_volume_rows=missing_volume_rows,
        negative_volume_rows=negative_volume_rows,
        warnings=warnings,
    )
    invalid_rows = int(
        invalid_ohlc_rows
        + non_numeric_ohlcv_rows
        + missing_time_rows
        + missing_volume_rows
        + negative_volume_rows
    )
    return {
        "symbol": str(symbol).upper(),
        "interval": str(interval),
        "time_column": resolved_time_col,
        "row_count": row_count,
        "expected_bars": int(expected_bars),
        "actual_bars": int(len(unique_open_time_ms)),
        "missing_bars": int(missing_bars),
        "duplicate_bars": int(duplicate_bars),
        "out_of_order_bars": int(out_of_order_bars),
        "invalid_rows": int(invalid_rows),
        "invalid_ohlc_rows": int(invalid_ohlc_rows),
        "non_numeric_ohlcv_rows": int(non_numeric_ohlcv_rows),
        "missing_time_rows": int(missing_time_rows),
        "missing_volume_rows": int(missing_volume_rows),
        "negative_volume_rows": int(negative_volume_rows),
        "missing_required_columns": missing_required,
        "first_open_time": _iso_from_ms(unique_open_time_ms.iloc[0]) if len(unique_open_time_ms) else None,
        "last_open_time": _iso_from_ms(unique_open_time_ms.iloc[-1]) if len(unique_open_time_ms) else None,
        "interval_ms": int(step_ms),
        "candle_id_algorithm": CANDLE_ID_ALGORITHM,
        "quality_status": quality_status,
        "warnings": warnings,
    }


def describe_multi_timeframe_anchor_rule(primary_interval: str, higher_interval: str) -> dict[str, Any]:
    """Describe the no-future anchor rule used by replay and research features."""
    return {
        "primary_interval": str(primary_interval),
        "higher_interval": str(higher_interval),
        "position_anchor": "primary_open_time_containing_higher_timeframe_bar",
        "feature_anchor": "latest_completed_higher_timeframe_bar_at_or_before_primary_open_time",
        "no_future_higher_timeframe_bar": True,
        "purpose": "research_context_alignment_only",
    }


def _resolve_time_column(frame: pd.DataFrame, requested: str | None) -> str | None:
    if requested:
        return requested if requested in frame.columns else None
    for column in TIME_COLUMNS:
        if column in frame.columns:
            return column
    return None


def _normalized_open_time_values(values: pd.Series) -> list[str | None]:
    ms = _open_time_ms(values)
    result: list[str | None] = []
    for value in ms:
        if pd.isna(value):
            result.append(None)
        else:
            result.append(str(int(value)))
    return result


def _open_time_key(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if _looks_numeric(value):
        return str(int(float(value)))
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(timestamp):
        return str(value)
    if timestamp.tzinfo is not None:
        return timestamp.tz_convert("UTC").isoformat()
    return timestamp.isoformat()


def _open_time_ms(values: pd.Series) -> pd.Series:
    if values.empty:
        return pd.Series(dtype="float64")
    if pd.api.types.is_numeric_dtype(values) or values.dropna().map(_looks_numeric).all():
        return pd.to_numeric(values, errors="coerce")
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    result = pd.Series(np.nan, index=values.index, dtype="float64")
    valid = parsed.notna()
    if valid.any():
        result.loc[valid] = parsed.loc[valid].map(lambda value: int(value.timestamp() * 1000)).astype("float64")
    return result


def _looks_numeric(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _count_missing_bars(unique_open_time_ms: pd.Series, step_ms: int) -> int:
    if len(unique_open_time_ms) < 2:
        return 0
    missing = 0
    for diff in unique_open_time_ms.diff().dropna():
        if diff > step_ms:
            missing += max(0, int(diff // step_ms) - 1)
    return int(missing)


def _expected_bar_count(unique_open_time_ms: pd.Series, step_ms: int) -> int:
    if unique_open_time_ms.empty:
        return 0
    span = int(unique_open_time_ms.iloc[-1] - unique_open_time_ms.iloc[0])
    return int(span // step_ms) + 1


def _ohlc_issues(frame: pd.DataFrame) -> tuple[int, int]:
    present = [column for column in ("open", "high", "low", "close") if column in frame.columns]
    if len(present) < 4:
        return 0, 0
    numeric = {column: pd.to_numeric(frame[column], errors="coerce") for column in present}
    missing_numeric = pd.concat([numeric[column].isna() for column in present], axis=1).any(axis=1)
    high = numeric["high"]
    low = numeric["low"]
    open_price = numeric["open"]
    close = numeric["close"]
    invalid = (
        (high < pd.concat([open_price, close, low], axis=1).max(axis=1))
        | (low > pd.concat([open_price, close, high], axis=1).min(axis=1))
    )
    return int(invalid.fillna(False).sum()), int(missing_numeric.sum())


def _volume_issues(frame: pd.DataFrame) -> tuple[int, int]:
    if "volume" not in frame.columns:
        return int(len(frame)), 0
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    return int(volume.isna().sum()), int((volume < 0).fillna(False).sum())


def _quality_warnings(
    *,
    missing_required: list[str],
    missing_time_rows: int,
    missing_bars: int,
    duplicate_bars: int,
    out_of_order_bars: int,
    invalid_ohlc_rows: int,
    non_numeric_ohlcv_rows: int,
    missing_volume_rows: int,
    negative_volume_rows: int,
) -> list[str]:
    warnings: list[str] = []
    if missing_required:
        warnings.append("missing_required_columns")
    if missing_time_rows:
        warnings.append("missing_time")
    if missing_bars:
        warnings.append("missing_bars")
    if duplicate_bars:
        warnings.append("duplicate_bars")
    if out_of_order_bars:
        warnings.append("out_of_order")
    if invalid_ohlc_rows:
        warnings.append("invalid_ohlc")
    if non_numeric_ohlcv_rows:
        warnings.append("non_numeric_ohlcv")
    if negative_volume_rows:
        warnings.append("negative_volume")
    if missing_volume_rows:
        warnings.append("missing_volume")
    return warnings


def _quality_status(
    *,
    missing_required: list[str],
    missing_time_rows: int,
    invalid_ohlc_rows: int,
    non_numeric_ohlcv_rows: int,
    missing_volume_rows: int,
    negative_volume_rows: int,
    warnings: list[str],
) -> str:
    if (
        missing_required
        or missing_time_rows
        or invalid_ohlc_rows
        or non_numeric_ohlcv_rows
        or missing_volume_rows
        or negative_volume_rows
    ):
        return "FAIL"
    return "WARNING" if warnings else "PASS"


def _iso_from_ms(value: Any) -> str:
    return pd.to_datetime(int(value), unit="ms", utc=True).isoformat()


__all__ = [
    "CANDLE_ID_ALGORITHM",
    "REQUIRED_KLINE_COLUMNS",
    "TIME_COLUMNS",
    "attach_candle_ids",
    "build_candle_id",
    "build_kline_quality_report",
    "describe_multi_timeframe_anchor_rule",
]
