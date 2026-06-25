from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

from .data_versioning import attach_data_version_metadata, build_data_version
from .kline_quality import build_candle_id


REQUIRED_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
TIME_COLUMNS = ("open_time", "timestamp")
SOURCE_ENTRY_OBSERVATION_CANDIDATE = "ENTRY_OBSERVATION_CANDIDATE"
CANDIDATE_SOURCES = frozenset({"rule_seeded", "manual_context", "model_ranked"})
DEFAULT_CANDIDATE_SOURCE = "rule_seeded"
CURRENT_BAR_CLOSE = "CURRENT_BAR_CLOSE"
NEXT_BAR_CONFIRMATION = "NEXT_BAR_CONFIRMATION"
OBSERVATION_COLUMNS = [
    "observation_id",
    "symbol",
    "interval",
    "bar_index",
    "bar_time",
    "setup_bar_index",
    "decision_bar_index",
    "setup_bar_time",
    "decision_bar_time",
    "candle_id",
    "candidate_source",
    "eligible_for_review",
    "candidate_reason",
    "decision_timing",
    "feature_cutoff_bar_index",
    "feature_timing_policy",
    "data_version",
    "source",
]


def generate_entry_observation_universe(
    klines: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    drop_lookback: int = 5,
    volume_lookback: int = 20,
    min_prior_drop_pct: float = 0.015,
    min_range_pct: float = 0.02,
    volume_ratio_threshold: float = 1.5,
    volume_zscore_threshold: float = 1.0,
    lower_shadow_ratio_threshold: float = 0.35,
    confirmation_body_ratio_threshold: float = 0.55,
    candidate_source: str = DEFAULT_CANDIDATE_SOURCE,
) -> pd.DataFrame:
    """Generate broad review candidates for entry-logic research.

    The output is an observation universe for later human labeling. It is not a
    trading signal and deliberately does not calculate future outcomes.
    """
    if not isinstance(klines, pd.DataFrame):
        raise ValueError("klines must be a pandas DataFrame")
    source = _candidate_source(candidate_source)
    if klines.empty:
        empty = pd.DataFrame(columns=OBSERVATION_COLUMNS)
        try:
            data_version = build_data_version(klines, symbol=symbol, interval=interval)
            return attach_data_version_metadata(empty, data_version)
        except ValueError:
            return empty
    _validate_input_columns(klines)
    ordered = _ordered_klines(klines)
    data_version = build_data_version(ordered.drop(columns=_internal_columns(ordered), errors="ignore"), symbol=symbol, interval=interval)
    data_version_id = str(data_version["data_version"])

    observations: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for position, (index_value, row) in enumerate(ordered.iterrows()):
        decision_bar_index = int(row["_qrc_bar_index"])
        setup = _visible_setup_metrics(
            ordered,
            position,
            drop_lookback=drop_lookback,
            volume_lookback=volume_lookback,
            min_prior_drop_pct=min_prior_drop_pct,
            min_range_pct=min_range_pct,
            volume_ratio_threshold=volume_ratio_threshold,
            volume_zscore_threshold=volume_zscore_threshold,
            lower_shadow_ratio_threshold=lower_shadow_ratio_threshold,
        )
        if setup["core_setup_ok"] and setup["lower_shadow_ok"]:
            _append_observation(
                observations,
                seen,
                symbol=symbol,
                interval=interval,
                setup_bar_index=decision_bar_index,
                decision_bar_index=decision_bar_index,
                setup_bar_time=_bar_time(row),
                decision_bar_time=_bar_time(row),
                decision_timing=CURRENT_BAR_CLOSE,
                candidate_source=source,
                data_version=data_version_id,
                reason_parts=[
                    "review_filter",
                    "prior_drop",
                    "range_expansion",
                    "volume_expansion",
                    "lower_shadow",
                ],
            )
            continue
        if position > 0 and _bullish_confirmation(row, confirmation_body_ratio_threshold):
            setup_row = ordered.iloc[position - 1]
            previous_setup = _visible_setup_metrics(
                ordered,
                position - 1,
                drop_lookback=drop_lookback,
                volume_lookback=volume_lookback,
                min_prior_drop_pct=min_prior_drop_pct,
                min_range_pct=min_range_pct,
                volume_ratio_threshold=volume_ratio_threshold,
                volume_zscore_threshold=volume_zscore_threshold,
                lower_shadow_ratio_threshold=lower_shadow_ratio_threshold,
            )
            if previous_setup["core_setup_ok"]:
                _append_observation(
                    observations,
                    seen,
                    symbol=symbol,
                    interval=interval,
                    setup_bar_index=int(setup_row["_qrc_bar_index"]),
                    decision_bar_index=decision_bar_index,
                    setup_bar_time=_bar_time(setup_row),
                    decision_bar_time=_bar_time(row),
                    decision_timing=NEXT_BAR_CONFIRMATION,
                    candidate_source=source,
                    data_version=data_version_id,
                    reason_parts=[
                        "review_filter",
                        "prior_drop",
                        "range_expansion",
                        "volume_expansion",
                        "bullish_confirmation",
                    ],
                )
    result = pd.DataFrame(observations, columns=OBSERVATION_COLUMNS)
    if not result.empty:
        result = result.sort_values(["bar_index", "decision_timing", "observation_id"], kind="stable").reset_index(drop=True)
        result["eligible_for_review"] = result["eligible_for_review"].astype(object)
    return attach_data_version_metadata(result, data_version)


def build_entry_observation_id(
    symbol: str,
    interval: str,
    decision_bar_index: int,
    candidate_source: str,
    data_version: str,
) -> str:
    payload = "|".join([str(symbol).upper(), str(interval), str(int(decision_bar_index)), candidate_source, data_version])
    return "entry_obs_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _validate_input_columns(klines: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_OHLCV_COLUMNS if column not in klines.columns]
    if missing:
        raise ValueError(f"Missing kline columns: {', '.join(missing)}")
    if not any(column in klines.columns for column in TIME_COLUMNS):
        raise ValueError("Missing kline time column: open_time or timestamp")


def _candidate_source(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in CANDIDATE_SOURCES:
        raise ValueError(f"Unsupported candidate_source: {value}")
    return normalized


def _ordered_klines(klines: pd.DataFrame) -> pd.DataFrame:
    ordered = klines.copy()
    time_column = next((column for column in TIME_COLUMNS if column in ordered.columns), None)
    if time_column is None:
        raise ValueError("Missing kline time column: open_time or timestamp")
    if ordered[time_column].isna().any():
        raise ValueError(f"missing {time_column}")
    time_values = ordered[time_column].astype(str)
    if time_values.duplicated().any():
        raise ValueError(f"duplicate {time_column}")
    ordered["_qrc_sort_time"] = pd.to_datetime(ordered[time_column], errors="coerce", utc=True)
    if ordered["_qrc_sort_time"].isna().any():
        raise ValueError(f"invalid {time_column}")

    if "bar_index" in ordered.columns:
        bar_indexes = pd.to_numeric(ordered["bar_index"], errors="coerce")
        if bar_indexes.isna().any():
            raise ValueError("missing bar_index")
        if bar_indexes.duplicated().any():
            raise ValueError("duplicate bar_index")
        ordered["_qrc_bar_index"] = bar_indexes.astype("int64")
        return ordered.sort_values(["_qrc_bar_index", "_qrc_sort_time"], kind="stable").reset_index(drop=True)

    index_values = pd.Series(ordered.index, index=ordered.index)
    numeric_index = pd.to_numeric(index_values, errors="coerce")
    if numeric_index.notna().all() and not numeric_index.duplicated().any():
        ordered["_qrc_bar_index"] = numeric_index.astype("int64")
        return ordered.sort_values(["_qrc_bar_index", "_qrc_sort_time"], kind="stable").reset_index(drop=True)

    ordered = ordered.sort_values("_qrc_sort_time", kind="stable").reset_index(drop=True)
    ordered["_qrc_bar_index"] = np.arange(len(ordered), dtype=int)
    return ordered


def _internal_columns(frame: pd.DataFrame) -> list[str]:
    return [column for column in frame.columns if str(column).startswith("_qrc_")]


def _append_observation(
    rows: list[dict[str, Any]],
    seen: set[tuple[int, str]],
    *,
    symbol: str,
    interval: str,
    setup_bar_index: int,
    decision_bar_index: int,
    setup_bar_time: str,
    decision_bar_time: str,
    decision_timing: str,
    candidate_source: str,
    data_version: str,
    reason_parts: list[str],
) -> None:
    key = (int(decision_bar_index), candidate_source)
    if key in seen:
        return
    seen.add(key)
    candle_id = build_candle_id(symbol, interval, decision_bar_time)
    feature_cutoff_bar_index = int(decision_bar_index) if decision_timing == CURRENT_BAR_CLOSE else int(setup_bar_index)
    feature_timing_policy = "current_bar_close" if decision_timing == CURRENT_BAR_CLOSE else "setup_bar_only"
    rows.append(
        {
            "observation_id": build_entry_observation_id(
                symbol,
                interval,
                int(decision_bar_index),
                candidate_source,
                data_version,
            ),
            "symbol": str(symbol).upper(),
            "interval": str(interval),
            "bar_index": int(decision_bar_index),
            "bar_time": str(decision_bar_time),
            "setup_bar_index": int(setup_bar_index),
            "decision_bar_index": int(decision_bar_index),
            "setup_bar_time": str(setup_bar_time),
            "decision_bar_time": str(decision_bar_time),
            "candle_id": candle_id,
            "candidate_source": candidate_source,
            "eligible_for_review": True,
            "candidate_reason": ",".join(reason_parts),
            "decision_timing": decision_timing,
            "feature_cutoff_bar_index": feature_cutoff_bar_index,
            "feature_timing_policy": feature_timing_policy,
            "data_version": data_version,
            "source": SOURCE_ENTRY_OBSERVATION_CANDIDATE,
        }
    )


def _visible_setup_metrics(
    ordered: pd.DataFrame,
    position: int,
    *,
    drop_lookback: int,
    volume_lookback: int,
    min_prior_drop_pct: float,
    min_range_pct: float,
    volume_ratio_threshold: float,
    volume_zscore_threshold: float,
    lower_shadow_ratio_threshold: float,
) -> dict[str, bool]:
    if position <= max(1, int(drop_lookback)) or position < 2:
        return {"core_setup_ok": False, "lower_shadow_ok": False}
    current = ordered.iloc[position]
    previous = ordered.iloc[position - 1]
    start = ordered.iloc[position - int(drop_lookback)]

    current_open = _finite(current.get("open"))
    current_high = _finite(current.get("high"))
    current_low = _finite(current.get("low"))
    current_close = _finite(current.get("close"))
    current_volume = _finite(current.get("volume"))
    previous_close = _finite(previous.get("close"))
    start_close = _finite(start.get("close"))
    if None in {current_open, current_high, current_low, current_close, current_volume, previous_close, start_close}:
        return {"core_setup_ok": False, "lower_shadow_ok": False}
    if current_high <= current_low or previous_close <= 0 or start_close <= 0:
        return {"core_setup_ok": False, "lower_shadow_ok": False}

    prior_return = previous_close / start_close - 1.0
    prior_drop_ok = prior_return <= -abs(float(min_prior_drop_pct))
    range_pct = (current_high - current_low) / previous_close
    range_ok = range_pct >= float(min_range_pct)
    volume_ok = _volume_ok(
        ordered,
        position,
        current_volume,
        lookback=volume_lookback,
        ratio_threshold=volume_ratio_threshold,
        zscore_threshold=volume_zscore_threshold,
    )
    candle_range = current_high - current_low
    lower_shadow = max(min(current_open, current_close) - current_low, 0.0)
    lower_shadow_ok = lower_shadow / candle_range >= float(lower_shadow_ratio_threshold)
    return {
        "core_setup_ok": bool(prior_drop_ok and range_ok and volume_ok),
        "lower_shadow_ok": bool(lower_shadow_ok),
    }


def _volume_ok(
    ordered: pd.DataFrame,
    position: int,
    current_volume: float,
    *,
    lookback: int,
    ratio_threshold: float,
    zscore_threshold: float,
) -> bool:
    start = max(0, position - int(lookback))
    prior = pd.to_numeric(ordered.iloc[start:position]["volume"], errors="coerce")
    prior = prior.replace([np.inf, -np.inf], np.nan).dropna()
    if prior.empty:
        return False
    mean = float(prior.mean())
    std = float(prior.std(ddof=0))
    ratio = current_volume / mean if mean > 0 else 0.0
    zscore = (current_volume - mean) / std if std > 0 else 0.0
    return bool(ratio >= float(ratio_threshold) or zscore >= float(zscore_threshold))


def _bullish_confirmation(row: pd.Series, body_ratio_threshold: float) -> bool:
    open_price = _finite(row.get("open"))
    high = _finite(row.get("high"))
    low = _finite(row.get("low"))
    close = _finite(row.get("close"))
    if None in {open_price, high, low, close} or high <= low or close <= open_price:
        return False
    return bool((close - open_price) / (high - low) >= float(body_ratio_threshold))


def _bar_index(row: pd.Series, index_value: Any, fallback: int) -> int:
    if "bar_index" in row and pd.notna(row.get("bar_index")):
        value = row.get("bar_index")
    else:
        value = index_value
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _bar_time(row: pd.Series) -> str:
    for column in TIME_COLUMNS:
        if column in row and pd.notna(row[column]):
            return str(row[column])
    return ""


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "OBSERVATION_COLUMNS",
    "CANDIDATE_SOURCES",
    "SOURCE_ENTRY_OBSERVATION_CANDIDATE",
    "build_entry_observation_id",
    "generate_entry_observation_universe",
]
