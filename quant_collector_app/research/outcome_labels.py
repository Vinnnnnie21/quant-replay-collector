from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd


ALLOWED_HORIZON_BARS = (5, 10, 20, 50)
ALLOWED_PRICING_BASIS = ("next_open", "event_close", "legacy_mid", "worst_case_same_bar")
DEFAULT_PRICING_BASIS = "next_open"
PRICING_BASIS_NOTES = {
    "next_open": "Signal at t; evaluation entry at t+1 open.",
    "event_close": "Research comparison basis only; assumes entry at event close.",
    "legacy_mid": "Legacy replay compatibility only; does not represent executable fill.",
    "worst_case_same_bar": "Conservative same-bar comparison basis only.",
}
OUTCOME_COLUMNS = [
    "outcome_label_id",
    "sample_id",
    "session_id",
    "label_version",
    "symbol",
    "interval",
    "bar_index",
    "horizon_bars",
    "pricing_basis",
    "fwd_ret",
    "mfe",
    "mae",
    "hit_tp",
    "hit_sl",
    "r_multiple",
    "insufficient_future_bars",
    "pricing_note",
    "created_at",
]


def validate_pricing_basis(value: str) -> str:
    basis = str(value or "").strip().lower()
    if basis not in ALLOWED_PRICING_BASIS:
        raise ValueError(f"Unsupported pricing_basis: {value}")
    return basis


def _validate_horizon_bars(horizon_bars: int) -> int:
    value = int(horizon_bars)
    if value not in ALLOWED_HORIZON_BARS:
        raise ValueError(f"Unsupported horizon_bars: {horizon_bars}")
    return value


def build_outcome_label_id(
    sample_id: str,
    label_version: str,
    horizon_bars: int,
    pricing_basis: str = DEFAULT_PRICING_BASIS,
) -> str:
    horizon = _validate_horizon_bars(horizon_bars)
    basis = validate_pricing_basis(pricing_basis)
    payload = "|".join([str(sample_id), str(label_version), str(horizon), basis])
    return "out_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _direction(sample: dict[str, Any]) -> str:
    return "SHORT" if str(sample.get("side") or "").upper() == "SHORT" else "LONG"


def _entry_price(event: pd.Series, post: pd.DataFrame, basis: str, side: str) -> float | None:
    if basis == "next_open":
        return _finite(post.iloc[0]["open"]) if not post.empty else None
    if basis == "event_close":
        return _finite(event["close"])
    if basis == "legacy_mid":
        high, low = _finite(event["high"]), _finite(event["low"])
        return (high + low) / 2.0 if high is not None and low is not None else None
    key = "high" if side == "LONG" else "low"
    return _finite(event[key])


def _return(entry: float, exit_price: float, side: str) -> float:
    return exit_price / entry - 1.0 if side == "LONG" else entry / exit_price - 1.0


def _metrics(
    entry: float,
    post: pd.DataFrame,
    side: str,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> dict[str, Any]:
    exit_price = _finite(post.iloc[-1]["close"])
    highs = pd.to_numeric(post["high"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    lows = pd.to_numeric(post["low"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if exit_price is None or entry <= 0 or highs.empty or lows.empty:
        return {"fwd_ret": None, "mfe": None, "mae": None, "hit_tp": None, "hit_sl": None, "r_multiple": None}
    if side == "LONG":
        mfe = float(highs.max() / entry - 1.0)
        mae = float(lows.min() / entry - 1.0)
    else:
        mfe = float(entry / lows.min() - 1.0)
        mae = float(entry / highs.max() - 1.0)
    fwd_ret = _return(entry, exit_price, side)
    return {
        "fwd_ret": _finite(fwd_ret),
        "mfe": _finite(mfe),
        "mae": _finite(mae),
        "hit_tp": int(mfe >= take_profit_pct),
        "hit_sl": int(mae <= -stop_loss_pct),
        "r_multiple": _finite(fwd_ret / stop_loss_pct) if stop_loss_pct > 0 else None,
    }


def compute_outcome_labels_for_sample(
    klines: pd.DataFrame,
    sample: dict[str, Any],
    horizon_bars: int,
    pricing_basis: str = DEFAULT_PRICING_BASIS,
    label_version: str = "outcome_v1",
    take_profit_pct: float = 0.02,
    stop_loss_pct: float = 0.01,
) -> pd.DataFrame:
    horizon = _validate_horizon_bars(horizon_bars)
    basis = validate_pricing_basis(pricing_basis)
    required = {"bar_index", "open", "high", "low", "close"}
    if not isinstance(klines, pd.DataFrame):
        raise ValueError(f"Missing kline columns: {sorted(required)}")
    missing = required.difference(klines.columns)
    if missing:
        raise ValueError(f"Missing kline columns: {sorted(missing)}")
    bar_index = int(sample["bar_index"])
    ordered = klines.sort_values("bar_index", kind="stable")
    event_rows = ordered[pd.to_numeric(ordered["bar_index"], errors="coerce") == bar_index]
    if event_rows.empty:
        raise ValueError(f"Missing event bar_index: {bar_index}")
    event = event_rows.iloc[-1]
    post = ordered[pd.to_numeric(ordered["bar_index"], errors="coerce") > bar_index].head(horizon)
    side = _direction(sample)
    insufficient = int(len(post) < horizon)
    values = {"fwd_ret": None, "mfe": None, "mae": None, "hit_tp": None, "hit_sl": None, "r_multiple": None}
    if not insufficient:
        entry = _entry_price(event, post, basis, side)
        if entry is not None and entry > 0:
            values = _metrics(entry, post, side, float(take_profit_pct), float(stop_loss_pct))
    row = {
        "outcome_label_id": build_outcome_label_id(sample["sample_id"], label_version, horizon, basis),
        "sample_id": str(sample["sample_id"]),
        "session_id": str(sample["session_id"]),
        "label_version": str(label_version),
        "symbol": str(sample["symbol"]).upper(),
        "interval": str(sample["interval"]),
        "bar_index": bar_index,
        "horizon_bars": horizon,
        "pricing_basis": basis,
        **values,
        "insufficient_future_bars": insufficient,
        "pricing_note": PRICING_BASIS_NOTES[basis],
        "created_at": sample.get("created_at") or datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return pd.DataFrame([row], columns=OUTCOME_COLUMNS)


def compute_multi_horizon_outcome_labels(
    klines: pd.DataFrame,
    sample: dict[str, Any],
    horizons: tuple[int, ...] = ALLOWED_HORIZON_BARS,
    pricing_basis: str = DEFAULT_PRICING_BASIS,
    label_version: str = "outcome_v1",
    take_profit_pct: float = 0.02,
    stop_loss_pct: float = 0.01,
) -> pd.DataFrame:
    frames = [
        compute_outcome_labels_for_sample(
            klines,
            sample,
            horizon,
            pricing_basis,
            label_version,
            take_profit_pct,
            stop_loss_pct,
        )
        for horizon in horizons
    ]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OUTCOME_COLUMNS)


__all__ = [
    "ALLOWED_HORIZON_BARS",
    "ALLOWED_PRICING_BASIS",
    "DEFAULT_PRICING_BASIS",
    "build_outcome_label_id",
    "compute_multi_horizon_outcome_labels",
    "compute_outcome_labels_for_sample",
    "validate_pricing_basis",
]
