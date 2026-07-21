from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

try:
    from market_data.types import interval_to_ms
except ImportError:  # pragma: no cover - package import path
    from ..market_data.types import interval_to_ms

from .data_versioning import attach_kline_data_version
from .kline_quality import validate_research_klines


REQUIRED_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]
REQUIRED_OBSERVATION_COLUMNS = ["observation_id", "symbol", "interval", "bar_index", "bar_time"]
TIME_COLUMNS = ("open_time", "timestamp")
CURRENT_BAR_CLOSE = "CURRENT_BAR_CLOSE"
NEXT_BAR_CONFIRMATION = "NEXT_BAR_CONFIRMATION"
DEFAULT_FEATURE_VERSION = "entry_context_features_v1"
DEFAULT_DECISION_TIMING_POLICY = "setup_bar_until_confirmation_allowed"
ENTRY_STRUCTURAL_FEATURE_VERSION = "entry-structural-features-v1"
ENTRY_STRUCTURAL_HISTORY_BARS = 61
POLICY_CURRENT_BAR_CLOSE = "current_bar_close"
POLICY_CONFIRMATION_BAR_INCLUDED = "confirmation_bar_included"
POLICY_SETUP_BAR_ONLY = "setup_bar_only"
FORBIDDEN_CONTEXT_FIELD_TOKENS = ("fwd", "future", "mfe", "mae", "hit_tp", "hit_sl")
FORBIDDEN_CONTEXT_FIELD_EXACT = {"pnl", "profit", "win"}
FEATURE_METADATA_COLUMNS = {
    "observation_id",
    "symbol",
    "interval",
    "bar_index",
    "bar_time",
    "setup_bar_index",
    "decision_bar_index",
    "feature_cutoff_bar_index",
    "feature_timing_policy",
    "decision_timing",
    "uses_next_bar_confirmation",
    "insufficient_history",
    "feature_version",
}
FEATURE_COLUMNS = [
    "observation_id",
    "symbol",
    "interval",
    "bar_index",
    "bar_time",
    "setup_bar_index",
    "decision_bar_index",
    "feature_cutoff_bar_index",
    "feature_timing_policy",
    "feature_version",
    "decision_timing",
    "uses_next_bar_confirmation",
    "prior_ret_5",
    "prior_ret_10",
    "prior_ret_20",
    "trend_slope_20",
    "distance_to_recent_high_20",
    "distance_to_recent_low_20",
    "drop_from_recent_high_20",
    "consecutive_bearish_bars",
    "largest_red_bar_pct_20",
    "down_move_duration",
    "body_ratio",
    "upper_shadow_ratio",
    "lower_shadow_ratio",
    "close_position_in_range",
    "range_pct",
    "reclaim_ratio",
    "volume_ratio_to_ma20",
    "volume_zscore_20",
    "volume_rank_100",
    "realized_vol_20",
    "atr_ratio_20",
    "range_zscore_20",
    "insufficient_history",
]
DEFAULT_FEATURE_COLS = tuple(column for column in FEATURE_COLUMNS if column not in FEATURE_METADATA_COLUMNS)


@dataclass(frozen=True, slots=True)
class StructuralFeatureValue:
    name: str
    values: tuple[float, ...]
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None


@dataclass(frozen=True, slots=True)
class StructuralFeatureGroup:
    name: str
    features: tuple[StructuralFeatureValue, ...]

    def feature(self, name: str) -> StructuralFeatureValue:
        return next(item for item in self.features if item.name == name)


@dataclass(frozen=True, slots=True)
class EntryStructuralFeatureSnapshot:
    symbol: str
    interval: str
    cutoff_time_utc_ms: int
    feature_version: str
    groups: tuple[StructuralFeatureGroup, ...]

    def group(self, name: str) -> StructuralFeatureGroup:
        return next(item for item in self.groups if item.name == name)


def build_entry_structural_feature_snapshot(
    klines: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    cutoff_time_utc_ms: int,
) -> EntryStructuralFeatureSnapshot:
    """Build the canonical v1.6 structural feature snapshot at a closed cutoff."""
    required = [
        "open_time_utc_ms",
        "close_time_utc_ms",
        "open",
        "high",
        "low",
        "close",
    ]
    if not isinstance(klines, pd.DataFrame):
        raise TypeError("klines must be a pandas DataFrame")
    _validate_columns(klines, required, "structural kline")
    cutoff = int(cutoff_time_utc_ms)
    ordered = klines.copy()
    ordered["_close_time"] = pd.to_numeric(
        ordered["close_time_utc_ms"], errors="coerce"
    )
    ordered = ordered[ordered["_close_time"] <= cutoff]
    ordered = ordered.sort_values("open_time_utc_ms", kind="stable").tail(
        ENTRY_STRUCTURAL_HISTORY_BARS
    )
    open_times = pd.to_numeric(ordered["open_time_utc_ms"], errors="coerce")
    expected_step = _structural_interval_ms(str(interval))
    ordered["_continuous_from_previous"] = (
        open_times.diff().eq(expected_step) & open_times.notna()
    )
    atrs = _structural_atrs(ordered, (5, 20, 60))
    path_features = tuple(
        _structural_path_feature(
            ordered,
            window,
            anchors,
            atr=atrs[window],
        )
        for window, anchors in ((5, 5), (20, 10), (60, 15))
    )
    candle_features = _structural_candle_features(
        ordered,
        atr20=atrs[20],
    )
    trend_features = _structural_trend_features(ordered, atrs=atrs)
    activity_features = _structural_activity_features(ordered)
    return EntryStructuralFeatureSnapshot(
        symbol=str(symbol).upper(),
        interval=str(interval),
        cutoff_time_utc_ms=cutoff,
        feature_version=ENTRY_STRUCTURAL_FEATURE_VERSION,
        groups=(
            StructuralFeatureGroup("price_path", path_features),
            StructuralFeatureGroup("candle_shape", candle_features),
            StructuralFeatureGroup("trend_volatility", trend_features),
            StructuralFeatureGroup("trading_activity", activity_features),
        ),
    )


def _structural_activity_features(
    ordered: pd.DataFrame,
) -> tuple[StructuralFeatureValue, ...]:
    names = (
        "quote_activity_20",
        "quote_activity_60",
        "trade_count_activity_20",
        "trade_count_activity_60",
        "average_trade_size_activity_20",
        "aggressor_current",
        "aggressor_5",
        "aggressor_20",
        "aggressor_delta",
    )
    required = {
        "quote_volume",
        "trade_count",
        "taker_buy_quote_volume",
    }
    if not required.issubset(ordered.columns):
        return tuple(
            StructuralFeatureValue(name, (), "ancillary_field_missing")
            for name in names
        )

    def positive_values(column: str, frame: pd.DataFrame) -> tuple[float, ...] | None:
        values: list[float] = []
        for raw_value in frame[column]:
            value = _finite(raw_value)
            if value is None or value <= 0:
                return None
            values.append(value)
        return tuple(values)

    def relative_activity(column: str, window: int) -> float | None:
        if not _structural_window_is_contiguous(ordered, window + 1):
            return None
        current_values = positive_values(column, ordered.tail(1))
        prior_values = positive_values(
            column,
            ordered.iloc[:-1].tail(window),
        )
        if current_values is None or prior_values is None or len(prior_values) != window:
            return None
        median = float(np.median(np.asarray(prior_values, dtype=float)))
        return math.log(current_values[0] / median) if median > 0 else None

    def positive_reason(column: str, window: int) -> str:
        label = "trade_count" if column == "trade_count" else "quote_volume"
        if len(ordered) >= window + 1 and not _structural_window_is_contiguous(
            ordered,
            window + 1,
        ):
            return "missing_bar_continuity"
        frame = ordered.tail(window + 1)
        values = tuple(_finite(value) for value in frame[column])
        if len(values) < window + 1 or any(value is None for value in values):
            return f"missing_{label}"
        if any(value == 0 for value in values):
            return f"zero_{label}"
        if any(value is not None and value < 0 for value in values):
            return f"negative_{label}"
        return f"invalid_{label}"

    average_size = None
    if _structural_window_is_contiguous(ordered, 21):
        current_quote = positive_values("quote_volume", ordered.tail(1))
        current_count = positive_values("trade_count", ordered.tail(1))
        prior_quote = positive_values("quote_volume", ordered.iloc[:-1].tail(20))
        prior_count = positive_values("trade_count", ordered.iloc[:-1].tail(20))
        if (
            current_quote is not None
            and current_count is not None
            and prior_quote is not None
            and prior_count is not None
            and len(prior_quote) == len(prior_count) == 20
        ):
            current_size = current_quote[0] / current_count[0]
            prior_sizes = tuple(
                quote / count
                for quote, count in zip(
                    prior_quote,
                    prior_count,
                    strict=True,
                )
            )
            median_size = float(
                np.median(np.asarray(prior_sizes, dtype=float))
            )
            if current_size > 0 and median_size > 0:
                average_size = math.log(current_size / median_size)

    def aggressor_values(window: int) -> tuple[float, ...] | None:
        frame = ordered.tail(window)
        if not _structural_window_is_contiguous(ordered, window):
            return None
        values: list[float] = []
        for _, row in frame.iterrows():
            quote = _finite(row["quote_volume"])
            taker_buy = _finite(row["taker_buy_quote_volume"])
            if (
                quote is None
                or quote <= 0
                or taker_buy is None
                or taker_buy < 0
                or taker_buy > quote
            ):
                return None
            values.append(2.0 * taker_buy / quote - 1.0)
        return tuple(values)

    current_aggressor = aggressor_values(1)
    last_five = aggressor_values(5)
    last_twenty = aggressor_values(20)
    aggressor_current = current_aggressor[0] if current_aggressor else None
    aggressor_5 = math.fsum(last_five) / 5 if last_five else None
    aggressor_20 = math.fsum(last_twenty) / 20 if last_twenty else None
    aggressor_delta = (
        aggressor_5 - aggressor_20
        if aggressor_5 is not None and aggressor_20 is not None
        else None
    )
    return (
        _structural_scalar("quote_activity_20", relative_activity("quote_volume", 20), positive_reason("quote_volume", 20)),
        _structural_scalar("quote_activity_60", relative_activity("quote_volume", 60), positive_reason("quote_volume", 60)),
        _structural_scalar("trade_count_activity_20", relative_activity("trade_count", 20), positive_reason("trade_count", 20)),
        _structural_scalar("trade_count_activity_60", relative_activity("trade_count", 60), positive_reason("trade_count", 60)),
        _structural_scalar(
            "average_trade_size_activity_20",
            average_size,
            (
                positive_reason("trade_count", 20)
                if positive_values("trade_count", ordered.tail(21)) is None
                else positive_reason("quote_volume", 20)
            ),
        ),
        _structural_scalar("aggressor_current", aggressor_current, "nonpositive_or_missing_quote_volume"),
        _structural_scalar("aggressor_5", aggressor_5, "nonpositive_or_missing_quote_volume"),
        _structural_scalar("aggressor_20", aggressor_20, "nonpositive_or_missing_quote_volume"),
        _structural_scalar("aggressor_delta", aggressor_delta, "nonpositive_or_missing_quote_volume"),
    )


def _structural_trend_features(
    ordered: pd.DataFrame,
    *,
    atrs: Mapping[int, float | None],
) -> tuple[StructuralFeatureValue, ...]:
    raw_closes = tuple(_finite(value) for value in ordered["close"])
    closes = (
        tuple(float(value) for value in raw_closes if value is not None)
        if all(value is not None and value > 0 for value in raw_closes)
        else ()
    )
    price_history_valid = len(closes) == len(raw_closes)

    def efficiency(window: int) -> float | None:
        if (
            len(closes) < window + 1
            or not price_history_valid
            or not _structural_window_is_contiguous(ordered, window + 1)
        ):
            return None
        values = closes[-(window + 1):]
        numerator = values[-1] - values[0]
        denominator = math.fsum(
            abs(values[index] - values[index - 1])
            for index in range(1, len(values))
        )
        return numerator / denominator if denominator > 0 else None

    def adjusted_slope(window: int) -> float | None:
        if (
            len(closes) < window
            or not price_history_valid
            or not _structural_window_is_contiguous(ordered, window)
        ):
            return None
        values = np.asarray(closes[-window:], dtype=float)
        log_values = np.log(values)
        slope = float(
            np.polyfit(np.arange(window, dtype=float), log_values, 1)[0]
        )
        sigma = float(np.std(np.diff(log_values), ddof=0))
        if not math.isfinite(sigma) or math.isclose(
            sigma,
            0.0,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            return None
        value = slope / sigma
        return value if math.isfinite(value) else None

    def ema_distance(window: int, atr20: float | None) -> float | None:
        if (
            len(closes) < window
            or not price_history_valid
            or atr20 is None
            or not _structural_window_is_contiguous(ordered, len(ordered))
        ):
            return None
        ema = math.fsum(closes[:window]) / window
        alpha = 2.0 / (window + 1.0)
        for value in closes[window:]:
            ema = alpha * value + (1.0 - alpha) * ema
        return (closes[-1] - ema) / atr20

    atr5 = atrs[5]
    atr20 = atrs[20]
    atr60 = atrs[60]
    current_close = closes[-1] if closes else None
    volatility_level = (
        atr20 / current_close
        if atr20 is not None
        and current_close is not None
        and current_close > 0
        else None
    )
    volatility_shock = (
        atr5 / atr20
        if atr5 is not None and atr20 is not None
        else None
    )
    volatility_regime = (
        atr20 / atr60
        if atr20 is not None and atr60 is not None
        else None
    )
    return (
        _structural_scalar("direction_efficiency_20", efficiency(20), "zero_or_invalid_direction_path"),
        _structural_scalar("direction_efficiency_60", efficiency(60), "zero_or_invalid_direction_path"),
        _structural_scalar("adjusted_slope_20", adjusted_slope(20), "zero_or_invalid_return_volatility"),
        _structural_scalar("adjusted_slope_60", adjusted_slope(60), "zero_or_invalid_return_volatility"),
        _structural_scalar("ema_distance_20", ema_distance(20, atr20), "atr_or_price_unavailable"),
        _structural_scalar("ema_distance_60", ema_distance(60, atr20), "atr_or_price_unavailable"),
        _structural_scalar("volatility_level", volatility_level, "atr_or_price_unavailable"),
        _structural_scalar("volatility_shock", volatility_shock, "atr_unavailable"),
        _structural_scalar("volatility_regime", volatility_regime, "atr_unavailable"),
    )


def _structural_candle_features(
    ordered: pd.DataFrame,
    *,
    atr20: float | None,
) -> tuple[StructuralFeatureValue, ...]:
    names = (
        "body_direction",
        "upper_wick_ratio",
        "lower_wick_ratio",
        "amplitude_atr_20",
        "bullish_ratio_5",
        "body_net_5",
        "max_upper_wick_5",
        "max_lower_wick_5",
        "range_position_20",
        "range_position_60",
    )
    if ordered.empty:
        return tuple(
            StructuralFeatureValue(name, (), "insufficient_history")
            for name in names
        )
    current = ordered.iloc[-1]
    open_value, high, low, close = (
        _finite(current[column])
        for column in ("open", "high", "low", "close")
    )
    candle_range = (
        high - low
        if high is not None and low is not None and high >= low
        else None
    )
    current_ohlc = (open_value, high, low, close)
    if not _structural_ohlc_is_valid(current_ohlc):
        shape_reason = "invalid_ohlc_bounds"
    elif candle_range is None or candle_range <= 0:
        shape_reason = "zero_or_invalid_range"
    else:
        shape_reason = None
    if shape_reason is None:
        assert open_value is not None and high is not None
        assert low is not None and close is not None and candle_range is not None
        body = (close - open_value) / candle_range
        upper = (high - max(open_value, close)) / candle_range
        lower = (min(open_value, close) - low) / candle_range
    else:
        body = upper = lower = None

    amplitude = (
        candle_range / atr20
        if candle_range is not None and atr20 is not None
        else None
    )
    last_five = ordered.tail(5)
    five_complete = _structural_window_is_contiguous(ordered, 5)
    five_ohlc = [
        tuple(_finite(row[column]) for column in ("open", "high", "low", "close"))
        for _, row in last_five.iterrows()
    ]
    five_valid = five_complete and all(
        _structural_ohlc_is_valid(values)
        for values in five_ohlc
    )
    typed_five_ohlc = (
        tuple(
            tuple(float(value) for value in values if value is not None)
            for values in five_ohlc
        )
        if five_valid
        else ()
    )
    bullish = (
        math.fsum(
            1.0 for values in typed_five_ohlc if values[3] > values[0]
        )
        / 5
        if five_valid
        else None
    )
    body_denominator = (
        math.fsum(values[1] - values[2] for values in typed_five_ohlc)
        if five_valid
        else 0.0
    )
    body_net = (
        math.fsum(values[3] - values[0] for values in typed_five_ohlc)
        / body_denominator
        if five_valid and body_denominator > 0
        else None
    )
    wick_ratios: list[tuple[float, float]] = []
    if five_valid:
        for values in typed_five_ohlc:
            item_open, item_high, item_low, item_close = values
            item_range = item_high - item_low
            if item_range <= 0:
                wick_ratios = []
                break
            wick_ratios.append(
                (
                    (item_high - max(item_open, item_close)) / item_range,
                    (min(item_open, item_close) - item_low) / item_range,
                )
            )

    def range_position(window: int) -> float | None:
        frame = ordered.tail(window)
        if (
            len(frame) < window
            or close is None
            or not _structural_window_is_contiguous(ordered, window)
        ):
            return None
        highs = tuple(_finite(value) for value in frame["high"])
        lows = tuple(_finite(value) for value in frame["low"])
        if any(value is None for value in (*highs, *lows)):
            return None
        high_values = tuple(float(value) for value in highs if value is not None)
        low_values = tuple(float(value) for value in lows if value is not None)
        width = max(high_values) - min(low_values)
        return (close - min(low_values)) / width if width > 0 else None

    return (
        _structural_scalar("body_direction", body, shape_reason),
        _structural_scalar("upper_wick_ratio", upper, shape_reason),
        _structural_scalar("lower_wick_ratio", lower, shape_reason),
        _structural_scalar("amplitude_atr_20", amplitude, "atr_unavailable"),
        _structural_scalar("bullish_ratio_5", bullish, "insufficient_or_invalid_5_bar_window"),
        _structural_scalar("body_net_5", body_net, "zero_or_invalid_5_bar_range"),
        _structural_scalar(
            "max_upper_wick_5",
            max((item[0] for item in wick_ratios), default=None),
            "zero_or_invalid_5_bar_range",
        ),
        _structural_scalar(
            "max_lower_wick_5",
            max((item[1] for item in wick_ratios), default=None),
            "zero_or_invalid_5_bar_range",
        ),
        _structural_scalar("range_position_20", range_position(20), "zero_or_invalid_20_bar_range"),
        _structural_scalar("range_position_60", range_position(60), "zero_or_invalid_60_bar_range"),
    )


def _structural_scalar(
    name: str,
    value: float | None,
    unavailable_reason: str | None,
) -> StructuralFeatureValue:
    if value is None or not math.isfinite(value):
        return StructuralFeatureValue(
            name,
            (),
            unavailable_reason or "non_finite_value",
        )
    return StructuralFeatureValue(name, (float(value),))


def _structural_path_feature(
    ordered: pd.DataFrame,
    window: int,
    anchor_count: int,
    *,
    atr: float | None,
) -> StructuralFeatureValue:
    name = f"path_{window}"
    if len(ordered) < window + 1:
        return StructuralFeatureValue(name, (), "insufficient_history")
    if not _structural_window_is_contiguous(ordered, window + 1):
        return StructuralFeatureValue(name, (), "missing_bar_continuity")
    window_frame = ordered.tail(window)
    closes = tuple(_finite(value) for value in window_frame["close"])
    if (
        atr is None
        or any(value is None or value <= 0 for value in closes)
        or closes[-1] is None
    ):
        return StructuralFeatureValue(name, (), "atr_or_price_unavailable")
    close_values = tuple(float(value) for value in closes if value is not None)
    positions = tuple(
        round(index * (window - 1) / (anchor_count - 1))
        for index in range(anchor_count)
    )
    first = close_values[positions[0]]
    last = close_values[-1]
    denominator = atr / last
    values = tuple(
        math.log(close_values[position] / first) / denominator
        for position in positions
    )
    return StructuralFeatureValue(name, values)


def _structural_atrs(
    ordered: pd.DataFrame,
    windows: tuple[int, ...],
) -> dict[int, float | None]:
    results = {window: None for window in windows}
    if len(ordered) < 2:
        return results
    values = {
        column: pd.to_numeric(ordered[column], errors="coerce").to_numpy(
            dtype=float
        )
        for column in ("open", "high", "low", "close")
    }
    open_values = values["open"]
    high_values = values["high"]
    low_values = values["low"]
    close_values = values["close"]
    current_ohlc_valid = (
        np.isfinite(open_values[1:])
        & np.isfinite(high_values[1:])
        & np.isfinite(low_values[1:])
        & np.isfinite(close_values[1:])
        & (open_values[1:] > 0)
        & (high_values[1:] > 0)
        & (low_values[1:] > 0)
        & (close_values[1:] > 0)
        & (high_values[1:] >= np.maximum(open_values[1:], close_values[1:]))
        & (low_values[1:] <= np.minimum(open_values[1:], close_values[1:]))
    )
    previous_close_valid = np.isfinite(close_values[:-1]) & (
        close_values[:-1] > 0
    )
    valid_ranges = current_ohlc_valid & previous_close_valid
    true_ranges = np.maximum.reduce(
        (
            high_values[1:] - low_values[1:],
            np.abs(high_values[1:] - close_values[:-1]),
            np.abs(low_values[1:] - close_values[:-1]),
        )
    )
    for window in windows:
        if not _structural_window_is_contiguous(ordered, window + 1):
            continue
        tail_valid = valid_ranges[-window:]
        if len(tail_valid) != window or not bool(tail_valid.all()):
            continue
        value = math.fsum(true_ranges[-window:].tolist()) / window
        if math.isfinite(value) and value > 0:
            results[window] = value
    return results


def _structural_window_is_contiguous(
    ordered: pd.DataFrame,
    bars: int,
) -> bool:
    if bars < 1 or len(ordered) < bars:
        return False
    if bars == 1:
        return True
    flags = ordered.tail(bars)["_continuous_from_previous"]
    return bool(flags.iloc[1:].all())


def _structural_ohlc_is_valid(
    values: tuple[float | None, float | None, float | None, float | None],
) -> bool:
    open_value, high, low, close = values
    if any(value is None or value <= 0 for value in values):
        return False
    assert open_value is not None and high is not None
    assert low is not None and close is not None
    return high >= max(open_value, close) and low <= min(open_value, close)


def _structural_interval_ms(interval: str) -> int:
    return interval_to_ms(interval)


@dataclass(frozen=True)
class FeatureSpec:
    feature_version: str = DEFAULT_FEATURE_VERSION
    lookback_windows: tuple[int, ...] = (5, 10, 20, 100)
    decision_timing_policy: str | None = DEFAULT_DECISION_TIMING_POLICY
    allow_confirmation_bar: bool = False
    feature_timing_policy: str | None = None
    strict_no_future: bool = True
    feature_cols: tuple[str, ...] = field(default_factory=lambda: DEFAULT_FEATURE_COLS)

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_version", str(self.feature_version or DEFAULT_FEATURE_VERSION))
        object.__setattr__(self, "lookback_windows", tuple(int(value) for value in self.lookback_windows))
        policy = None if self.decision_timing_policy is None else str(self.decision_timing_policy)
        object.__setattr__(self, "decision_timing_policy", policy)
        object.__setattr__(self, "allow_confirmation_bar", bool(self.allow_confirmation_bar))
        timing_policy = None if self.feature_timing_policy is None else _feature_timing_policy_name(str(self.feature_timing_policy))
        object.__setattr__(self, "feature_timing_policy", timing_policy)
        object.__setattr__(self, "strict_no_future", bool(self.strict_no_future))
        object.__setattr__(self, "feature_cols", tuple(str(value) for value in self.feature_cols))
        if not self.lookback_windows:
            raise ValueError("lookback_windows must not be empty")
        if any(value <= 0 for value in self.lookback_windows):
            raise ValueError("lookback_windows must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_version": self.feature_version,
            "lookback_windows": list(self.lookback_windows),
            "decision_timing_policy": self.decision_timing_policy,
            "allow_confirmation_bar": self.allow_confirmation_bar,
            "feature_timing_policy": self.feature_timing_policy,
            "strict_no_future": self.strict_no_future,
            "feature_cols": list(self.feature_cols),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FeatureSpec":
        return cls(
            feature_version=str(value.get("feature_version", DEFAULT_FEATURE_VERSION)),
            lookback_windows=tuple(value.get("lookback_windows", (5, 10, 20, 100))),
            decision_timing_policy=value.get("decision_timing_policy", DEFAULT_DECISION_TIMING_POLICY),
            allow_confirmation_bar=bool(value.get("allow_confirmation_bar", False)),
            feature_timing_policy=value.get("feature_timing_policy"),
            strict_no_future=bool(value.get("strict_no_future", True)),
            feature_cols=tuple(value.get("feature_cols", DEFAULT_FEATURE_COLS)),
        )

@dataclass(frozen=True)
class FeatureQualityReport:
    row_count: int
    feature_count: int
    nan_ratio_by_col: dict[str, float]
    constant_feature_cols: list[str]
    forbidden_fields_detected: list[str]
    min_bar_index: int | None
    max_bar_index: int | None
    feature_timing_policy: str | None = None
    allow_confirmation_bar: bool | None = None
    max_feature_cutoff_bar_index: int | None = None
    future_cutoff_violation_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "feature_count": self.feature_count,
            "nan_ratio_by_col": dict(self.nan_ratio_by_col),
            "constant_feature_cols": list(self.constant_feature_cols),
            "forbidden_fields_detected": list(self.forbidden_fields_detected),
            "min_bar_index": self.min_bar_index,
            "max_bar_index": self.max_bar_index,
            "feature_timing_policy": self.feature_timing_policy,
            "allow_confirmation_bar": self.allow_confirmation_bar,
            "max_feature_cutoff_bar_index": self.max_feature_cutoff_bar_index,
            "future_cutoff_violation_count": self.future_cutoff_violation_count,
        }

def build_entry_context_features(
    klines: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    windows: tuple[int, ...] = (5, 10, 20, 100),
    feature_spec: FeatureSpec | Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Build decision-time context features for entry-logic research."""
    if not isinstance(klines, pd.DataFrame):
        raise ValueError("klines must be a pandas DataFrame")
    if not isinstance(observations, pd.DataFrame):
        raise ValueError("observations must be a pandas DataFrame")
    spec = _coerce_feature_spec(feature_spec, windows)
    if observations.empty:
        result = pd.DataFrame(columns=FEATURE_COLUMNS)
        result.attrs["feature_version"] = spec.feature_version
        result.attrs["feature_spec"] = spec.to_dict()
        result.attrs["warnings"] = []
        result.attrs["feature_quality_report"] = build_feature_quality_report(result, feature_cols=spec.feature_cols, feature_spec=spec).to_dict()
        return result
    _validate_columns(klines, REQUIRED_OHLCV_COLUMNS, "kline")
    _validate_columns(observations, REQUIRED_OBSERVATION_COLUMNS, "observation")
    validate_research_klines(klines, context="strategy research")

    ordered = _ordered_klines(klines)
    warnings = _feature_cutoff_warnings(observations)
    rows = [_feature_row(ordered, observation, spec) for _, observation in observations.iterrows()]
    result = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    if not result.empty:
        for column in ("uses_next_bar_confirmation", "insufficient_history"):
            result[column] = result[column].astype(object)
    validate_no_forbidden_context_fields(result)
    quality_report = build_feature_quality_report(result, feature_cols=spec.feature_cols, feature_spec=spec)
    result.attrs["feature_version"] = spec.feature_version
    result.attrs["feature_spec"] = spec.to_dict()
    result.attrs["warnings"] = warnings
    result.attrs["feature_quality_report"] = quality_report.to_dict()
    versioned = attach_kline_data_version(
        result,
        klines,
        symbol=str(observations.iloc[0]["symbol"]),
        interval=str(observations.iloc[0]["interval"]),
    )
    versioned.attrs["feature_version"] = spec.feature_version
    versioned.attrs["feature_spec"] = spec.to_dict()
    versioned.attrs["warnings"] = warnings
    versioned.attrs["feature_quality_report"] = quality_report.to_dict()
    return versioned


def _feature_row(ordered: pd.DataFrame, observation: pd.Series, spec: FeatureSpec) -> dict[str, Any]:
    output_bar_index = int(_required_bar_index(observation.get("bar_index"), "bar_index"))
    timing = _decision_timing_name(observation.get("decision_timing") or CURRENT_BAR_CLOSE)
    setup_bar_index, decision_bar_index, feature_cutoff_bar_index, feature_timing_policy = _resolve_feature_cutoff(
        observation,
        spec,
        timing=timing,
    )
    visible = ordered[ordered["_bar_index"] <= feature_cutoff_bar_index].copy()
    current = visible[visible["_bar_index"] == feature_cutoff_bar_index]
    if current.empty:
        current_row = pd.Series(dtype=object)
    else:
        current_row = current.iloc[-1]
    shape = _shape_features(current_row, visible)
    drop = _drop_structure_features(visible)
    volume = _volume_features(visible)
    volatility = _volatility_features(visible)
    row = {
        "observation_id": str(observation["observation_id"]),
        "symbol": str(observation["symbol"]).upper(),
        "interval": str(observation["interval"]),
        "bar_index": output_bar_index,
        "bar_time": str(observation.get("bar_time") or _bar_time(current_row)),
        "setup_bar_index": setup_bar_index,
        "decision_bar_index": decision_bar_index,
        "feature_cutoff_bar_index": feature_cutoff_bar_index,
        "feature_timing_policy": feature_timing_policy,
        "feature_version": spec.feature_version,
        "decision_timing": timing,
        "uses_next_bar_confirmation": timing == NEXT_BAR_CONFIRMATION,
        "prior_ret_5": _prior_return(visible, 5),
        "prior_ret_10": _prior_return(visible, 10),
        "prior_ret_20": _prior_return(visible, 20),
        "trend_slope_20": _trend_slope(visible, 20),
        "distance_to_recent_high_20": _distance_to_recent_extreme(visible, "high", 20),
        "distance_to_recent_low_20": _distance_to_recent_extreme(visible, "low", 20),
        "drop_from_recent_high_20": drop["drop_from_recent_high_20"],
        "consecutive_bearish_bars": drop["consecutive_bearish_bars"],
        "largest_red_bar_pct_20": drop["largest_red_bar_pct_20"],
        "down_move_duration": drop["down_move_duration"],
        "body_ratio": shape["body_ratio"],
        "upper_shadow_ratio": shape["upper_shadow_ratio"],
        "lower_shadow_ratio": shape["lower_shadow_ratio"],
        "close_position_in_range": shape["close_position_in_range"],
        "range_pct": shape["range_pct"],
        "reclaim_ratio": shape["reclaim_ratio"],
        "volume_ratio_to_ma20": volume["volume_ratio_to_ma20"],
        "volume_zscore_20": volume["volume_zscore_20"],
        "volume_rank_100": volume["volume_rank_100"],
        "realized_vol_20": volatility["realized_vol_20"],
        "atr_ratio_20": volatility["atr_ratio_20"],
        "range_zscore_20": volatility["range_zscore_20"],
        "insufficient_history": len(visible) < max(spec.lookback_windows),
    }
    return row

def _feature_cutoff_warnings(observations: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    for _, row in observations.iterrows():
        timing = str(row.get("decision_timing") or CURRENT_BAR_CLOSE).upper()
        observation_id = str(row.get("observation_id") or "unknown")
        if timing == NEXT_BAR_CONFIRMATION and pd.isna(row.get("setup_bar_index")):
            warnings.append(f"feature_cutoff_fallback_to_bar_index: missing setup_bar_index for {observation_id}")
        if pd.isna(row.get("decision_bar_index")):
            warnings.append(f"feature_cutoff_fallback_to_bar_index: missing decision_bar_index for {observation_id}")
    return warnings

def _coerce_feature_spec(
    feature_spec: FeatureSpec | Mapping[str, Any] | None,
    windows: tuple[int, ...],
) -> FeatureSpec:
    if isinstance(feature_spec, FeatureSpec):
        return feature_spec
    if isinstance(feature_spec, Mapping):
        return FeatureSpec.from_dict(feature_spec)
    return FeatureSpec(lookback_windows=tuple(int(value) for value in windows))


def _resolve_feature_cutoff_bar(row: pd.Series, spec: FeatureSpec) -> int:
    """Return the last kline bar visible to context features for one observation."""
    timing = _decision_timing_name(row.get("decision_timing") or CURRENT_BAR_CLOSE)
    return _resolve_feature_cutoff(row, spec, timing=timing)[2]


def _resolve_feature_cutoff(
    row: pd.Series,
    spec: FeatureSpec,
    *,
    timing: str,
) -> tuple[int, int, int, str]:
    fallback = _finite(row.get("bar_index"))
    setup = _finite(row.get("setup_bar_index"))
    decision = _finite(row.get("decision_bar_index"))
    explicit_cutoff = _finite(row.get("feature_cutoff_bar_index"))
    if fallback is None:
        raise ValueError("observation bar_index must be numeric")
    if decision is None:
        decision = fallback
    if setup is None:
        setup = decision if timing == CURRENT_BAR_CLOSE else fallback
    setup_index = int(setup)
    decision_index = int(decision)
    fallback_index = int(fallback)
    if timing == CURRENT_BAR_CLOSE:
        if setup_index != decision_index:
            raise ValueError("CURRENT_BAR_CLOSE requires setup_bar_index == decision_bar_index")
        cutoff = decision_index
        policy = POLICY_CURRENT_BAR_CLOSE
    elif timing == NEXT_BAR_CONFIRMATION:
        policy = _next_bar_feature_policy(spec)
        cutoff = decision_index if policy == POLICY_CONFIRMATION_BAR_INCLUDED else setup_index
    else:
        raise ValueError(f"Unsupported decision_timing: {timing}")
    if explicit_cutoff is not None:
        explicit_index = int(explicit_cutoff)
        _validate_cutoff_bounds(explicit_index, setup_index, decision_index, field_name="feature_cutoff_bar_index")
    _validate_cutoff_bounds(cutoff, setup_index, decision_index, field_name="feature_cutoff_bar_index")
    if fallback_index != decision_index and timing == CURRENT_BAR_CLOSE:
        raise ValueError("CURRENT_BAR_CLOSE bar_index must match decision_bar_index")
    return setup_index, decision_index, int(cutoff), policy


def _validate_cutoff_bounds(cutoff: int, setup: int, decision: int, *, field_name: str) -> None:
    if cutoff > decision:
        raise ValueError(f"{field_name} cannot be after decision_bar_index")
    if cutoff < setup:
        raise ValueError(f"{field_name} cannot be before setup_bar_index")


def _next_bar_feature_policy(spec: FeatureSpec) -> str:
    if spec.feature_timing_policy in {POLICY_SETUP_BAR_ONLY, POLICY_CONFIRMATION_BAR_INCLUDED}:
        return str(spec.feature_timing_policy)
    return POLICY_CONFIRMATION_BAR_INCLUDED if spec.allow_confirmation_bar else POLICY_SETUP_BAR_ONLY


def _decision_timing_name(value: Any) -> str:
    text = str(value or CURRENT_BAR_CLOSE).upper()
    if text not in {CURRENT_BAR_CLOSE, NEXT_BAR_CONFIRMATION}:
        raise ValueError(f"Unsupported decision_timing: {value}")
    return text


def _feature_timing_policy_name(value: str) -> str:
    policy = str(value or "").strip().lower()
    if policy not in {POLICY_CURRENT_BAR_CLOSE, POLICY_CONFIRMATION_BAR_INCLUDED, POLICY_SETUP_BAR_ONLY}:
        raise ValueError(f"Unsupported feature_timing_policy: {value}")
    return policy


def _required_bar_index(value: Any, name: str) -> int:
    number = _finite(value)
    if number is None:
        raise ValueError(f"{name} must be numeric")
    return int(number)

def build_feature_quality_report(
    features: pd.DataFrame,
    *,
    feature_cols: tuple[str, ...] | list[str] | None = None,
    feature_spec: FeatureSpec | Mapping[str, Any] | None = None,
) -> FeatureQualityReport:
    if not isinstance(features, pd.DataFrame):
        raise ValueError("features must be a pandas DataFrame")
    spec = _coerce_feature_spec(feature_spec, (5, 10, 20, 100)) if feature_spec is not None else None
    columns = list(feature_cols) if feature_cols is not None else _infer_quality_feature_cols(features)
    columns = [column for column in columns if column in features.columns]
    nan_ratio_by_col: dict[str, float] = {}
    constant_cols: list[str] = []
    for column in columns:
        values = pd.to_numeric(features[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        nan_ratio_by_col[str(column)] = float(values.isna().mean()) if len(values) else 0.0
        clean = values.dropna()
        if not clean.empty and clean.nunique(dropna=True) <= 1:
            constant_cols.append(str(column))
    bar_index = pd.to_numeric(features["bar_index"], errors="coerce").dropna() if "bar_index" in features.columns else pd.Series(dtype=float)
    cutoff_index = (
        pd.to_numeric(features["feature_cutoff_bar_index"], errors="coerce").dropna()
        if "feature_cutoff_bar_index" in features.columns
        else pd.Series(dtype=float)
    )
    policy = _quality_policy(features, spec)
    return FeatureQualityReport(
        row_count=int(len(features)),
        feature_count=int(len(columns)),
        nan_ratio_by_col=nan_ratio_by_col,
        constant_feature_cols=constant_cols,
        forbidden_fields_detected=_forbidden_context_fields(features.columns),
        min_bar_index=int(bar_index.min()) if not bar_index.empty else None,
        max_bar_index=int(bar_index.max()) if not bar_index.empty else None,
        feature_timing_policy=policy,
        allow_confirmation_bar=spec.allow_confirmation_bar if spec is not None else None,
        max_feature_cutoff_bar_index=int(cutoff_index.max()) if not cutoff_index.empty else None,
        future_cutoff_violation_count=_future_cutoff_violation_count(features),
    )


def _quality_policy(features: pd.DataFrame, spec: FeatureSpec | None) -> str | None:
    if "feature_timing_policy" in features.columns and len(features):
        values = sorted(set(features["feature_timing_policy"].dropna().astype(str)))
        if len(values) == 1:
            return values[0]
        if values:
            return ",".join(values)
    return spec.feature_timing_policy if spec is not None else None


def _future_cutoff_violation_count(features: pd.DataFrame) -> int:
    required = {"feature_cutoff_bar_index", "decision_bar_index", "setup_bar_index"}
    if not required <= set(features.columns):
        return 0
    cutoff = pd.to_numeric(features["feature_cutoff_bar_index"], errors="coerce")
    decision = pd.to_numeric(features["decision_bar_index"], errors="coerce")
    setup = pd.to_numeric(features["setup_bar_index"], errors="coerce")
    violations = (cutoff > decision) | (cutoff < setup)
    return int(violations.fillna(False).sum())

def validate_no_forbidden_context_fields(features: pd.DataFrame) -> None:
    forbidden = _forbidden_context_fields(features.columns if isinstance(features, pd.DataFrame) else [])
    if forbidden:
        raise ValueError(f"forbidden context feature fields: {', '.join(forbidden)}")


def _infer_quality_feature_cols(features: pd.DataFrame) -> list[str]:
    columns: list[str] = []
    for column in features.columns:
        name = str(column)
        if name in FEATURE_METADATA_COLUMNS:
            continue
        if pd.to_numeric(features[column], errors="coerce").notna().any():
            columns.append(name)
    return columns


def _forbidden_context_fields(columns: Any) -> list[str]:
    forbidden: list[str] = []
    for column in columns:
        name = str(column)
        lowered = name.lower()
        token_hit = any(token in lowered for token in FORBIDDEN_CONTEXT_FIELD_TOKENS)
        exact_hit = any(
            lowered == token
            or lowered.startswith(f"{token}_")
            or lowered.endswith(f"_{token}")
            for token in FORBIDDEN_CONTEXT_FIELD_EXACT
        )
        if token_hit or exact_hit:
            forbidden.append(name)
    return sorted(forbidden)


def _ordered_klines(klines: pd.DataFrame) -> pd.DataFrame:
    ordered = klines.copy()
    if "bar_index" in ordered.columns:
        ordered["_bar_index"] = pd.to_numeric(ordered["bar_index"], errors="coerce")
    else:
        ordered["_bar_index"] = pd.to_numeric(pd.Series(ordered.index, index=ordered.index), errors="coerce")
    if ordered["_bar_index"].isna().any():
        raise ValueError("kline bar_index must be numeric")
    return ordered.reset_index(drop=True)


def _prior_return(visible: pd.DataFrame, bars: int) -> float:
    if len(visible) <= int(bars):
        return math.nan
    current = _finite(visible.iloc[-1].get("close"))
    prior = _finite(visible.iloc[-1 - int(bars)].get("close"))
    if current is None or prior is None or prior <= 0:
        return math.nan
    return current / prior - 1.0


def _trend_slope(visible: pd.DataFrame, window: int) -> float:
    closes = _numeric(visible.tail(int(window))["close"])
    closes = closes.dropna()
    closes = closes[closes > 0]
    if len(closes) < 2:
        return math.nan
    x = np.arange(len(closes), dtype=float)
    return _finite_or_nan(np.polyfit(x, np.log(closes.to_numpy(dtype=float)), 1)[0])


def _distance_to_recent_extreme(visible: pd.DataFrame, column: str, window: int) -> float:
    current_close = _finite(visible.iloc[-1].get("close")) if not visible.empty else None
    if current_close is None:
        return math.nan
    values = _numeric(visible.tail(int(window))[column]).dropna()
    if values.empty:
        return math.nan
    extreme = float(values.max()) if column == "high" else float(values.min())
    if extreme <= 0:
        return math.nan
    return current_close / extreme - 1.0


def _drop_structure_features(visible: pd.DataFrame) -> dict[str, float]:
    recent = visible.tail(20).copy()
    if recent.empty:
        return {
            "drop_from_recent_high_20": math.nan,
            "consecutive_bearish_bars": math.nan,
            "largest_red_bar_pct_20": math.nan,
            "down_move_duration": math.nan,
        }
    current_close = _finite(recent.iloc[-1].get("close"))
    highs = _numeric(recent["high"]).dropna()
    recent_high = float(highs.max()) if not highs.empty else math.nan
    drop = current_close / recent_high - 1.0 if current_close is not None and recent_high > 0 else math.nan

    consecutive = 0
    for _, row in recent.sort_values("_bar_index", ascending=False).iterrows():
        open_price = _finite(row.get("open"))
        close = _finite(row.get("close"))
        if open_price is None or close is None or close >= open_price:
            break
        consecutive += 1

    open_values = _numeric(recent["open"])
    close_values = _numeric(recent["close"])
    red = (open_values - close_values) / open_values.replace(0, np.nan)
    red = red.where(close_values < open_values).replace([np.inf, -np.inf], np.nan).dropna()
    largest_red = float(red.max()) if not red.empty else 0.0

    duration = math.nan
    if not highs.empty:
        high_position = int(highs.idxmax())
        current_position = int(recent.index[-1])
        try:
            duration = float(recent.index.get_loc(current_position) - recent.index.get_loc(high_position))
        except KeyError:
            duration = math.nan
    return {
        "drop_from_recent_high_20": _finite_or_nan(drop),
        "consecutive_bearish_bars": float(consecutive),
        "largest_red_bar_pct_20": _finite_or_nan(largest_red),
        "down_move_duration": _finite_or_nan(duration),
    }


def _shape_features(current: pd.Series, visible: pd.DataFrame) -> dict[str, float]:
    open_price = _finite(current.get("open"))
    high = _finite(current.get("high"))
    low = _finite(current.get("low"))
    close = _finite(current.get("close"))
    previous_close = _finite(visible.iloc[-2].get("close")) if len(visible) >= 2 else None
    if None in {open_price, high, low, close} or high <= low:
        return {
            "body_ratio": math.nan,
            "upper_shadow_ratio": math.nan,
            "lower_shadow_ratio": math.nan,
            "close_position_in_range": math.nan,
            "range_pct": math.nan,
            "reclaim_ratio": math.nan,
        }
    candle_range = high - low
    body = abs(close - open_price)
    upper_shadow = max(high - max(open_price, close), 0.0)
    lower_shadow = max(min(open_price, close) - low, 0.0)
    recent_low = _numeric(visible.tail(20)["low"]).dropna().min()
    reclaim = (close - float(recent_low)) / candle_range if pd.notna(recent_low) and candle_range > 0 else math.nan
    return {
        "body_ratio": body / candle_range,
        "upper_shadow_ratio": upper_shadow / candle_range,
        "lower_shadow_ratio": lower_shadow / candle_range,
        "close_position_in_range": (close - low) / candle_range,
        "range_pct": candle_range / previous_close if previous_close is not None and previous_close > 0 else math.nan,
        "reclaim_ratio": _finite_or_nan(reclaim),
    }


def _volume_features(visible: pd.DataFrame) -> dict[str, float]:
    current_volume = _finite(visible.iloc[-1].get("volume")) if not visible.empty else None
    if current_volume is None:
        return {"volume_ratio_to_ma20": math.nan, "volume_zscore_20": math.nan, "volume_rank_100": math.nan}
    prior20 = _numeric(visible.iloc[:-1].tail(20)["volume"]).dropna()
    ratio = math.nan
    zscore = math.nan
    if not prior20.empty:
        mean = float(prior20.mean())
        std = float(prior20.std(ddof=0))
        ratio = current_volume / mean if mean > 0 else math.nan
        zscore = (current_volume - mean) / std if std > 0 else 0.0
    last100 = _numeric(visible.tail(100)["volume"]).dropna()
    rank = float((last100 <= current_volume).mean()) if not last100.empty else math.nan
    return {
        "volume_ratio_to_ma20": _finite_or_nan(ratio),
        "volume_zscore_20": _finite_or_nan(zscore),
        "volume_rank_100": _finite_or_nan(rank),
    }


def _volatility_features(visible: pd.DataFrame) -> dict[str, float]:
    close = _numeric(visible["close"])
    log_returns = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    realized = float(log_returns.tail(20).std(ddof=0)) if len(log_returns.tail(20)) else math.nan

    high = _numeric(visible["high"])
    low = _numeric(visible["low"])
    previous_close = close.shift(1)
    true_ranges = pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1).replace([np.inf, -np.inf], np.nan)
    current_range = _finite((high.iloc[-1] - low.iloc[-1]) if len(high) and len(low) else math.nan)
    atr20 = float(true_ranges.tail(20).mean()) if true_ranges.tail(20).notna().any() else math.nan
    atr_ratio = current_range / atr20 if current_range is not None and atr20 > 0 else math.nan

    prior_ranges = (high.iloc[:-1] - low.iloc[:-1]).tail(20).replace([np.inf, -np.inf], np.nan).dropna()
    range_zscore = math.nan
    if current_range is not None and not prior_ranges.empty:
        std = float(prior_ranges.std(ddof=0))
        range_zscore = (current_range - float(prior_ranges.mean())) / std if std > 0 else 0.0
    return {
        "realized_vol_20": _finite_or_nan(realized),
        "atr_ratio_20": _finite_or_nan(atr_ratio),
        "range_zscore_20": _finite_or_nan(range_zscore),
    }


def _bar_time(row: pd.Series) -> str:
    for column in TIME_COLUMNS:
        if column in row and pd.notna(row.get(column)):
            return str(row.get(column))
    return ""


def _validate_columns(frame: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing {label} columns: {', '.join(missing)}")


def _numeric(values: Any) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _finite_or_nan(value: Any) -> float:
    number = _finite(value)
    return number if number is not None else math.nan


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "ENTRY_STRUCTURAL_FEATURE_VERSION",
    "ENTRY_STRUCTURAL_HISTORY_BARS",
    "EntryStructuralFeatureSnapshot",
    "FEATURE_COLUMNS",
    "FeatureQualityReport",
    "FeatureSpec",
    "StructuralFeatureGroup",
    "StructuralFeatureValue",
    "build_entry_context_features",
    "build_entry_structural_feature_snapshot",
    "build_feature_quality_report",
    "_resolve_feature_cutoff_bar",
    "validate_no_forbidden_context_fields",
]
