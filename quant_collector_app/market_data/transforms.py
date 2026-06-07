from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

try:
    from app_config import BJT, UTC
except ImportError:  # pragma: no cover - package import path
    from ..app_config import BJT, UTC
from .types import PRICE_COLUMNS, interval_to_ms, validate_date_range


def _series_to_bjt(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    if getattr(parsed.dt, "tz", None) is None:
        return parsed.dt.tz_localize(BJT)
    return parsed.dt.tz_convert(BJT)


def normalize_kline_df(
    df: pd.DataFrame,
    start_dt_bjt: dt.datetime,
    end_dt_bjt: dt.datetime,
    interval: str,
    source_name: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    if df is None or df.empty:
        raise ValueError(f"{source_name} 没有K线数据。")

    missing_prices = [column for column in PRICE_COLUMNS if column not in df.columns]
    if missing_prices:
        raise ValueError(f"{source_name} 缺少必要价格字段：{', '.join(missing_prices)}")

    out = df.copy()
    for column in PRICE_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    if "open_time_ms" in out.columns:
        out["open_time_ms"] = pd.to_numeric(out["open_time_ms"], errors="coerce")
        out["open_time_bjt"] = pd.to_datetime(out["open_time_ms"], unit="ms", utc=True, errors="coerce").dt.tz_convert(BJT)
    elif "open_time_bjt" in out.columns:
        out["open_time_bjt"] = _series_to_bjt(out["open_time_bjt"])
        out["open_time_ms"] = (out["open_time_bjt"].dt.tz_convert(UTC).astype("int64") // 1_000_000).astype("Int64")
    else:
        raise ValueError(f"{source_name} 缺少 open_time_ms 或 open_time_bjt 字段。")

    if "close_time_ms" in out.columns:
        out["close_time_ms"] = pd.to_numeric(out["close_time_ms"], errors="coerce")
        out["close_time_bjt"] = pd.to_datetime(out["close_time_ms"], unit="ms", utc=True, errors="coerce").dt.tz_convert(BJT)
    elif "close_time_bjt" in out.columns:
        out["close_time_bjt"] = _series_to_bjt(out["close_time_bjt"])
        out["close_time_ms"] = (out["close_time_bjt"].dt.tz_convert(UTC).astype("int64") // 1_000_000).astype("Int64")
    else:
        out["close_time_ms"] = out["open_time_ms"] + interval_to_ms(interval) - 1
        out["close_time_bjt"] = pd.to_datetime(out["close_time_ms"], unit="ms", utc=True, errors="coerce").dt.tz_convert(BJT)

    before = len(out)
    out = out.dropna(subset=["open_time_bjt", "close_time_bjt", *PRICE_COLUMNS]).copy()
    dropped_invalid = before - len(out)
    before_time_order = len(out)
    out = out[out["close_time_bjt"] >= out["open_time_bjt"]].copy()
    dropped_invalid += before_time_order - len(out)
    invalid_ohlc_mask = (
        (out["high"] < out["low"])
        | (out["open"] < out["low"])
        | (out["open"] > out["high"])
        | (out["close"] < out["low"])
        | (out["close"] > out["high"])
    )
    invalid_ohlc = int(invalid_ohlc_mask.sum())
    if invalid_ohlc:
        out = out[~invalid_ohlc_mask].copy()
        dropped_invalid += invalid_ohlc
    invalid_volume = int((out["volume"] < 0).sum())
    if invalid_volume:
        out = out[out["volume"] >= 0].copy()
        dropped_invalid += invalid_volume
    for column in ("open_time_ms", "close_time_ms"):
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("int64")

    out_of_order = int((out["open_time_ms"].diff().dropna() < 0).sum())
    out = out.sort_values("open_time_bjt")
    before_dedup = len(out)
    out = out.drop_duplicates(subset=["open_time_bjt"], keep="last")
    dropped_duplicates = before_dedup - len(out)

    start, end = validate_date_range(start_dt_bjt, end_dt_bjt)
    out = out[(out["open_time_bjt"] >= start) & (out["open_time_bjt"] <= end)].copy()
    out = out.reset_index(drop=True)
    out["bar_index"] = np.arange(len(out), dtype=int)
    if out.empty:
        raise ValueError(f"{source_name} 清洗后没有落在所选日期范围内的K线。")

    return out, {
        "dropped_invalid": dropped_invalid,
        "dropped_duplicates": dropped_duplicates,
        "invalid_ohlc": invalid_ohlc,
        "invalid_volume": invalid_volume,
        "out_of_order": out_of_order,
    }


_normalize_kline_df = normalize_kline_df


__all__ = ["_normalize_kline_df", "normalize_kline_df"]
