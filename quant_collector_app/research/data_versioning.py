from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .kline_quality import (
    CANDLE_ID_ALGORITHM,
    attach_candle_ids,
    build_kline_quality_report,
    describe_multi_timeframe_anchor_rule,
)


HASH_COLUMNS = ("candle_id", "open", "high", "low", "close", "volume")
DATA_HASH_ALGORITHM = "sha256(canonical_symbol_interval_candle_id_ohlcv)"


def compute_data_hash(
    klines: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    hash_columns: Iterable[str] = HASH_COLUMNS,
) -> str:
    """Hash the exact OHLCV payload used for research in fixed order."""
    if not isinstance(klines, pd.DataFrame):
        raise ValueError("klines must be a pandas DataFrame")
    with_ids = attach_candle_ids(klines, symbol=symbol, interval=interval)
    columns = tuple(hash_columns)
    missing = [column for column in columns if column not in with_ids.columns]
    if missing:
        raise ValueError(f"Missing columns for data_hash: {', '.join(missing)}")
    records = []
    for _, row in with_ids.loc[:, list(columns)].iterrows():
        records.append({column: _canonical_value(row[column]) for column in columns})
    records = sorted(records, key=lambda item: tuple(str(item[column]) for column in columns))
    payload = {
        "symbol": str(symbol).upper(),
        "interval": str(interval),
        "hash_columns": list(columns),
        "records": records,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_data_version(
    klines: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    quality_report: dict[str, Any] | None = None,
    higher_timeframe_intervals: Iterable[str] | None = None,
) -> dict[str, Any]:
    data_hash = compute_data_hash(klines, symbol=symbol, interval=interval)
    report = quality_report or build_kline_quality_report(klines, symbol=symbol, interval=interval)
    higher_intervals = list(higher_timeframe_intervals or [])
    return {
        "data_version": f"kline_{data_hash[:16]}",
        "data_hash": data_hash,
        "data_hash_algorithm": DATA_HASH_ALGORITHM,
        "candle_id_algorithm": CANDLE_ID_ALGORITHM,
        "symbol": str(symbol).upper(),
        "interval": str(interval),
        "row_count": int(len(klines)),
        "first_open_time": report.get("first_open_time"),
        "last_open_time": report.get("last_open_time"),
        "quality_status": report.get("quality_status"),
        "quality_warnings": list(report.get("warnings") or []),
        "quality_report": dict(report),
        "multi_timeframe_anchor_rules": [
            describe_multi_timeframe_anchor_rule(interval, higher_interval)
            for higher_interval in higher_intervals
        ],
    }


def attach_data_version_metadata(frame: pd.DataFrame, data_version: dict[str, Any]) -> pd.DataFrame:
    """Attach data version metadata through DataFrame.attrs without changing table columns."""
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("frame must be a pandas DataFrame")
    out = frame.copy()
    out.attrs.update(
        {
            "data_version": data_version.get("data_version"),
            "data_hash": data_version.get("data_hash"),
            "data_hash_algorithm": data_version.get("data_hash_algorithm"),
            "candle_id_algorithm": data_version.get("candle_id_algorithm"),
            "data_quality_status": data_version.get("quality_status"),
            "data_quality_warnings": list(data_version.get("quality_warnings") or []),
            "data_quality_report": dict(data_version.get("quality_report") or {}),
            "multi_timeframe_anchor_rules": list(data_version.get("multi_timeframe_anchor_rules") or []),
        }
    )
    return out


def attach_kline_data_version(
    frame: pd.DataFrame,
    klines: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    quality_report: dict[str, Any] | None = None,
    higher_timeframe_intervals: Iterable[str] | None = None,
) -> pd.DataFrame:
    version = build_data_version(
        klines,
        symbol=symbol,
        interval=interval,
        quality_report=quality_report,
        higher_timeframe_intervals=higher_timeframe_intervals,
    )
    return attach_data_version_metadata(frame, version)


def _canonical_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not np.isfinite(number):
            return None
        return round(number, 12)
    return str(value)


__all__ = [
    "DATA_HASH_ALGORITHM",
    "HASH_COLUMNS",
    "attach_data_version_metadata",
    "attach_kline_data_version",
    "build_data_version",
    "compute_data_hash",
]
