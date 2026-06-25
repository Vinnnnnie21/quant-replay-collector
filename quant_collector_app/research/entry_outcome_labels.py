from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import pandas as pd

from .data_versioning import attach_kline_data_version


REQUIRED_OHLCV_COLUMNS = ["high", "low", "close"]
REQUIRED_OBSERVATION_COLUMNS = ["observation_id", "bar_index"]
DEFAULT_HORIZONS = (3, 5, 10, 20)
DEFAULT_LABEL_VERSION = "entry_outcome_labels_v1"
DEFAULT_SAME_BAR_POLICY = "stop_loss_first"
DEFAULT_INSUFFICIENT_HORIZON_POLICY = "nan"
OUTCOME_COLUMNS = [
    "observation_id",
    "label_version",
    "fwd_ret_3",
    "fwd_ret_5",
    "fwd_ret_10",
    "fwd_ret_20",
    "mfe_10",
    "mae_10",
    "hit_tp_10",
    "hit_sl_10",
    "hit_tp_before_sl_10",
    "max_adverse_excursion_10",
    "max_favorable_excursion_10",
]


@dataclass(frozen=True)
class LabelSpec:
    label_version: str = DEFAULT_LABEL_VERSION
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    take_profit_pct: float = 0.02
    stop_loss_pct: float = 0.01
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    same_bar_policy: str = DEFAULT_SAME_BAR_POLICY
    insufficient_horizon_policy: str = DEFAULT_INSUFFICIENT_HORIZON_POLICY

    def __post_init__(self) -> None:
        object.__setattr__(self, "label_version", str(self.label_version or DEFAULT_LABEL_VERSION))
        object.__setattr__(self, "horizons", tuple(int(value) for value in self.horizons))
        object.__setattr__(self, "take_profit_pct", float(self.take_profit_pct))
        object.__setattr__(self, "stop_loss_pct", float(self.stop_loss_pct))
        object.__setattr__(self, "fee_bps", float(self.fee_bps))
        object.__setattr__(self, "slippage_bps", float(self.slippage_bps))
        object.__setattr__(self, "same_bar_policy", _same_bar_policy(self.same_bar_policy))
        object.__setattr__(self, "insufficient_horizon_policy", _insufficient_policy(self.insufficient_horizon_policy))
        if not self.horizons:
            raise ValueError("horizons must not be empty")
        if any(value <= 0 for value in self.horizons):
            raise ValueError("horizons must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label_version": self.label_version,
            "horizons": list(self.horizons),
            "take_profit_pct": self.take_profit_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "same_bar_policy": self.same_bar_policy,
            "insufficient_horizon_policy": self.insufficient_horizon_policy,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LabelSpec":
        return cls(
            label_version=str(value.get("label_version", DEFAULT_LABEL_VERSION)),
            horizons=tuple(value.get("horizons", DEFAULT_HORIZONS)),
            take_profit_pct=float(value.get("take_profit_pct", 0.02)),
            stop_loss_pct=float(value.get("stop_loss_pct", 0.01)),
            fee_bps=float(value.get("fee_bps", 0.0)),
            slippage_bps=float(value.get("slippage_bps", 0.0)),
            same_bar_policy=str(value.get("same_bar_policy", DEFAULT_SAME_BAR_POLICY)),
            insufficient_horizon_policy=str(value.get("insufficient_horizon_policy", DEFAULT_INSUFFICIENT_HORIZON_POLICY)),
        )


def build_entry_outcome_labels(
    klines: pd.DataFrame,
    observations: pd.DataFrame,
    *,
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    take_profit_pct: float = 0.02,
    stop_loss_pct: float = 0.01,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    same_bar_policy: str = DEFAULT_SAME_BAR_POLICY,
    insufficient_policy: str = "nan",
    label_spec: LabelSpec | Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Build post-event outcome labels; must not be used as entry logic model input."""
    if not isinstance(klines, pd.DataFrame):
        raise ValueError("klines must be a pandas DataFrame")
    if not isinstance(observations, pd.DataFrame):
        raise ValueError("observations must be a pandas DataFrame")
    spec = _coerce_label_spec(
        label_spec,
        horizons=horizons,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        same_bar_policy=same_bar_policy,
        insufficient_policy=insufficient_policy,
    )
    output_columns = outcome_columns_for_horizons(spec.horizons)
    if observations.empty:
        result = pd.DataFrame(columns=output_columns)
        result.attrs["label_version"] = spec.label_version
        result.attrs["label_spec"] = spec.to_dict()
        return result
    _validate_columns(klines, REQUIRED_OHLCV_COLUMNS, "kline")
    _validate_columns(observations, REQUIRED_OBSERVATION_COLUMNS, "observation")
    policy = spec.insufficient_horizon_policy
    ordered = _ordered_klines(klines)
    rows = []
    for _, observation in observations.iterrows():
        row = _label_row(
            ordered,
            observation,
            spec=spec,
            output_columns=output_columns,
        )
        if policy == "drop" and any(pd.isna(row.get(f"fwd_ret_{horizon}")) for horizon in spec.horizons):
            continue
        rows.append(row)
    result = pd.DataFrame(rows, columns=output_columns)
    result.attrs["label_version"] = spec.label_version
    result.attrs["label_spec"] = spec.to_dict()
    if {"symbol", "interval"} <= set(observations.columns):
        versioned = attach_kline_data_version(
            result,
            klines,
            symbol=str(observations.iloc[0]["symbol"]),
            interval=str(observations.iloc[0]["interval"]),
        )
        versioned.attrs["label_version"] = spec.label_version
        versioned.attrs["label_spec"] = spec.to_dict()
        return versioned
    return result


def outcome_columns_for_horizons(horizons: tuple[int, ...] | list[int]) -> list[str]:
    ordered_horizons = tuple(dict.fromkeys(int(value) for value in horizons))
    return [
        "observation_id",
        "label_version",
        *[f"fwd_ret_{horizon}" for horizon in ordered_horizons],
        "mfe_10",
        "mae_10",
        "hit_tp_10",
        "hit_sl_10",
        "hit_tp_before_sl_10",
        "max_adverse_excursion_10",
        "max_favorable_excursion_10",
    ]


def _label_row(
    ordered: pd.DataFrame,
    observation: pd.Series,
    *,
    spec: LabelSpec,
    output_columns: list[str],
) -> dict[str, Any]:
    bar_index = int(observation["bar_index"])
    event_rows = ordered[ordered["_bar_index"] == bar_index]
    event = event_rows.iloc[-1] if not event_rows.empty else pd.Series(dtype=object)
    base_close = _finite(event.get("close"))
    row = {column: math.nan for column in output_columns}
    row["observation_id"] = str(observation["observation_id"])
    row["label_version"] = spec.label_version
    for horizon in spec.horizons:
        column = f"fwd_ret_{horizon}"
        if column in row:
            row[column] = _forward_return(
                ordered,
                bar_index,
                base_close,
                horizon,
                fee_bps=spec.fee_bps,
                slippage_bps=spec.slippage_bps,
            )
    path10 = _future_window(ordered, bar_index, 10)
    if base_close is not None and base_close > 0 and len(path10) >= 10:
        path = _path_metrics(
            path10,
            base_close,
            take_profit_pct=spec.take_profit_pct,
            stop_loss_pct=spec.stop_loss_pct,
            same_bar_policy=spec.same_bar_policy,
        )
        row.update(path)
    return row


def _forward_return(
    ordered: pd.DataFrame,
    bar_index: int,
    base_close: float | None,
    horizon: int,
    *,
    fee_bps: float,
    slippage_bps: float,
) -> float:
    if base_close is None or base_close <= 0:
        return math.nan
    future = _future_window(ordered, bar_index, horizon)
    if len(future) < int(horizon):
        return math.nan
    close = _finite(future.iloc[-1].get("close"))
    if close is None:
        return math.nan
    round_trip_cost = 2.0 * (max(0.0, float(fee_bps)) + max(0.0, float(slippage_bps))) / 10000.0
    return close / base_close - 1.0 - round_trip_cost


def _path_metrics(
    future: pd.DataFrame,
    base_close: float,
    *,
    take_profit_pct: float,
    stop_loss_pct: float,
    same_bar_policy: str,
) -> dict[str, float | int]:
    highs = pd.to_numeric(future["high"], errors="coerce").dropna()
    lows = pd.to_numeric(future["low"], errors="coerce").dropna()
    if highs.empty or lows.empty:
        return {}
    mfe = float(highs.max() / base_close - 1.0)
    mae = float(lows.min() / base_close - 1.0)
    hit_tp = int(mfe >= float(take_profit_pct))
    hit_sl = int(mae <= -float(stop_loss_pct))
    hit_tp_before_sl = _hit_tp_before_sl(
        future,
        base_close,
        take_profit_pct=float(take_profit_pct),
        stop_loss_pct=float(stop_loss_pct),
        same_bar_policy=same_bar_policy,
    )
    return {
        "mfe_10": mfe,
        "mae_10": mae,
        "hit_tp_10": hit_tp,
        "hit_sl_10": hit_sl,
        "hit_tp_before_sl_10": hit_tp_before_sl,
        "max_adverse_excursion_10": mae,
        "max_favorable_excursion_10": mfe,
    }


def _hit_tp_before_sl(
    future: pd.DataFrame,
    base_close: float,
    *,
    take_profit_pct: float,
    stop_loss_pct: float,
    same_bar_policy: str,
) -> float:
    tp_price = base_close * (1.0 + max(0.0, take_profit_pct))
    sl_price = base_close * (1.0 - max(0.0, stop_loss_pct))
    for _, row in future.iterrows():
        high = _finite(row.get("high"))
        low = _finite(row.get("low"))
        if high is None or low is None:
            continue
        hit_sl = low <= sl_price
        hit_tp = high >= tp_price
        if hit_sl and hit_tp:
            if same_bar_policy == "take_profit_first":
                return 1.0
            if same_bar_policy == "ambiguous":
                return math.nan
            return 0.0
        if hit_sl:
            return 0.0
        if hit_tp:
            return 1.0
    return math.nan


def _future_window(ordered: pd.DataFrame, bar_index: int, horizon: int) -> pd.DataFrame:
    return ordered[ordered["_bar_index"] > int(bar_index)].head(int(horizon))


def _ordered_klines(klines: pd.DataFrame) -> pd.DataFrame:
    ordered = klines.copy()
    if "bar_index" in ordered.columns:
        ordered["_bar_index"] = pd.to_numeric(ordered["bar_index"], errors="coerce")
    else:
        ordered["_bar_index"] = pd.to_numeric(pd.Series(ordered.index, index=ordered.index), errors="coerce")
    if ordered["_bar_index"].isna().any():
        raise ValueError("kline bar_index must be numeric")
    return ordered.sort_values("_bar_index", kind="stable").reset_index(drop=True)


def _validate_columns(frame: pd.DataFrame, required: list[str], label: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing {label} columns: {', '.join(missing)}")


def _insufficient_policy(value: str) -> str:
    policy = str(value or "").lower()
    if policy not in {"nan", "drop"}:
        raise ValueError("insufficient_policy must be 'nan' or 'drop'")
    return policy


def _same_bar_policy(value: str) -> str:
    policy = str(value or "").lower()
    if policy not in {"stop_loss_first", "take_profit_first", "ambiguous"}:
        raise ValueError("same_bar_policy must be 'stop_loss_first', 'take_profit_first', or 'ambiguous'")
    return policy


def _coerce_label_spec(
    label_spec: LabelSpec | Mapping[str, Any] | None,
    *,
    horizons: tuple[int, ...] | list[int],
    take_profit_pct: float,
    stop_loss_pct: float,
    fee_bps: float,
    slippage_bps: float,
    same_bar_policy: str,
    insufficient_policy: str,
) -> LabelSpec:
    if isinstance(label_spec, LabelSpec):
        return label_spec
    if isinstance(label_spec, Mapping):
        return LabelSpec.from_dict(label_spec)
    return LabelSpec(
        horizons=tuple(int(value) for value in horizons),
        take_profit_pct=float(take_profit_pct),
        stop_loss_pct=float(stop_loss_pct),
        fee_bps=float(fee_bps),
        slippage_bps=float(slippage_bps),
        same_bar_policy=same_bar_policy,
        insufficient_horizon_policy=insufficient_policy,
    )


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "LabelSpec",
    "OUTCOME_COLUMNS",
    "build_entry_outcome_labels",
    "outcome_columns_for_horizons",
]
