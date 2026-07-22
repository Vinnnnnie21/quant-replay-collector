from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Iterable

import pandas as pd


OHLCV_COLUMNS = {"open", "high", "low", "close", "volume"}
_RELATIVE_VOLUME_FEATURE = re.compile(
    r"^volume_(ratio|zscore|percentile)_(20|50)$"
)


class FeatureBuildError(ValueError):
    pass


@dataclass(frozen=True)
class OhlcvFeatureDefinition:
    feature_name: str
    category: str
    formula: str
    required_columns: tuple[str, ...]
    lookback_bars: int
    uses_future_data: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


OHLCV_FEATURE_DEFINITIONS = {
    "volume_ratio_20": OhlcvFeatureDefinition(
        "volume_ratio_20",
        "relative_volume",
        "volume / mean(volume[-20:-1])",
        ("volume",),
        20,
    ),
    "volume_ratio_50": OhlcvFeatureDefinition(
        "volume_ratio_50",
        "relative_volume",
        "volume / mean(volume[-50:-1])",
        ("volume",),
        50,
    ),
    "volume_zscore_20": OhlcvFeatureDefinition(
        "volume_zscore_20",
        "relative_volume",
        "(volume - mean(volume[-20:-1])) / std(volume[-20:-1])",
        ("volume",),
        20,
    ),
    "volume_percentile_50": OhlcvFeatureDefinition(
        "volume_percentile_50",
        "relative_volume",
        "rank(volume, volume[-50:-1])",
        ("volume",),
        50,
    ),
}


def registered_ohlcv_feature_names() -> set[str]:
    return set(OHLCV_FEATURE_DEFINITIONS)


def ohlcv_feature_registry_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [definition.to_dict() for definition in OHLCV_FEATURE_DEFINITIONS.values()]
    )


def build_ohlcv_feature_frame(
    frame: pd.DataFrame,
    *,
    required_features: Iterable[str],
) -> pd.DataFrame:
    data = frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    requested = tuple(dict.fromkeys(str(feature) for feature in required_features))
    unsupported = sorted(
        feature for feature in requested if feature not in OHLCV_FEATURE_DEFINITIONS
    )
    if unsupported:
        raise FeatureBuildError(f"Unsupported OHLCV features: {', '.join(unsupported)}")
    missing_columns = sorted(OHLCV_COLUMNS.difference(data.columns))
    if missing_columns:
        raise FeatureBuildError(f"OHLCV dataframe missing columns: {', '.join(missing_columns)}")
    volume = pd.to_numeric(data["volume"], errors="coerce").astype(float)
    for feature in requested:
        if feature.startswith("volume_ratio_"):
            lookback = _lookback(feature)
            mean = volume.shift(1).rolling(lookback, min_periods=lookback).mean()
            data[feature] = volume / mean
        elif feature == "volume_zscore_20":
            data[feature] = _volume_zscore(volume, 20)
        elif feature == "volume_percentile_50":
            data[feature] = _volume_percentile(volume, 50)
    return data


def _lookback(feature_name: str) -> int:
    match = _RELATIVE_VOLUME_FEATURE.fullmatch(feature_name)
    if match is None:
        raise FeatureBuildError(f"Unsupported relative-volume feature: {feature_name}")
    return int(match.group(2))


def _volume_zscore(volume: pd.Series, lookback: int) -> pd.Series:
    history = volume.shift(1).rolling(lookback, min_periods=lookback)
    mean = history.mean()
    std = history.std(ddof=0)
    return (volume - mean) / std.replace(0.0, math.nan)


def _volume_percentile(volume: pd.Series, lookback: int) -> pd.Series:
    result = pd.Series(math.nan, index=volume.index, dtype=float)
    for index in range(lookback, len(volume)):
        current = volume.iloc[index]
        window = volume.iloc[index - lookback : index].dropna()
        if len(window) != lookback or not math.isfinite(float(current)):
            continue
        result.iloc[index] = float((window <= current).mean())
    return result


__all__ = [
    "FeatureBuildError",
    "OHLCV_FEATURE_DEFINITIONS",
    "OhlcvFeatureDefinition",
    "build_ohlcv_feature_frame",
    "ohlcv_feature_registry_frame",
    "registered_ohlcv_feature_names",
]
